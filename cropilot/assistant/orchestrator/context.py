"""Context for the prompt, built by code from the tools (no LLM): field, engine risks, guide sources."""
from __future__ import annotations

import logging
import re

from assistant import domain
from assistant.tools.guides import fit_passages
from assistant.tools.registry import ToolError, call

log = logging.getLogger("assistant.orchestrator")

SOURCES_TOKEN_BUDGET = 2000
MAX_SOURCES = 5
FACTOR_LABELS = {"avg_temperature": "średnia temp.", "avg_relative_humidity": "wilgotność wzgl.",
                 "total_precipitation": "opady", "min_temperature": "temp. min.", "max_temperature": "temp. maks."}


def _fmt(x, nd=2) -> str:
    return f"{x:.{nd}f}".replace(".", ",") if isinstance(x, (int, float)) else str(x)


MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
              "października", "listopada", "grudnia"]
WEEKDAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def pl_day(value) -> str:
    """2024-05-29 -> "środa, 29 maja" (the answer should say dates the way a farmer does; A-28d)."""
    import datetime as dt
    d = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])
    return f"{WEEKDAYS_PL[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]}"


def season_lines() -> list[str]:
    d = call("get_season_date")
    return [f"Data sezonu (dziś): {d['today']} ({pl_day(d['today'])}); prognoza do {d['forecast_until']} "
            f"({pl_day(d['forecast_until'])})."]


def field_line(field: dict) -> str:
    return f"Pole: {field['name']} (id {field['id']}; {field['crop']}, {_fmt(field['area_ha'], 1)} ha)"


ACTION_PL = {"wait": "czekać (ryzyko niskie albo poza wrażliwą fazą)",
             "monitor": "obserwować pole (lustracja)",
             "treat": "lustracja teraz; zabieg uzasadniony dopiero po przekroczeniu progu szkodliwości"}


def farmer_text(text: str, limit: int = 120) -> str:
    """The farmer's own words inside the prompt: data, never instructions (no tags, short)."""
    t = re.sub(r"[<>]", "", " ".join(str(text).split()))
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def _driver(d: dict) -> str:
    s = d.get("label", "")
    v = d.get("value")
    if v is not None and str(v) not in s and d.get("factor") != "growth_stage":
        unit = "" if d.get("unit") in ("0-1", None) else d["unit"]
        s += f" = {_fmt(v, 1) if isinstance(v, float) else v} {unit}".rstrip()
    if d.get("threshold") and d.get("factor") not in ("growth_stage",):
        s += f" (próg: {d['threshold']})"
    eff = d.get("effect")
    if isinstance(eff, (int, float)) and abs(eff) >= 0.01:
        s += f" [{'podnosi' if eff > 0 else 'obniża'} wynik o {_fmt(abs(eff))}]"
    if d.get("text"):
        s += f" (rolnik napisał: „{farmer_text(d['text'])}”)"
    return s


def growth_stage_line(threats: list[dict]) -> str | None:
    for t in threats:
        gs = (t.get("explanation") or {}).get("growth_stage")
        if gs:
            line = f"Faza rozwojowa (silnik): BBCH {gs.get('bbch')} — {gs.get('name', '')}"
            if gs.get("sowing_assumed"):
                line += f"; data siewu przyjęta: {gs['sowing_assumed']}"
            return line
    return None


def threat_lines(t: dict, with_factors: bool = True) -> list[str]:
    today = t["today"]
    rising = f", rośnie od {t['rising_days']} dni" if t.get("rising_days", 0) >= 2 else ""
    ref = f" [silnik:{t['threat_code']}]" if t.get("threat_code") else ""
    line = (f"- {t['threat']}{ref}: dziś {_fmt(today['score'])} ({today['level']}), trend {t['trend']}{rising}; "
            f"maks. w okresie {_fmt(t['max']['score'])} ({t['max']['level']}) dnia {t['max']['date']}")
    out = [line]
    expl = t.get("explanation") or {}
    if expl.get("summary"):
        out.append(f"  powody (silnik): {expl['summary']}")
    if with_factors and expl.get("drivers"):
        # the farmer's own reports first: the answer must mention them ("obejrzał pole i nie znalazł objawów")
        drivers = sorted(expl["drivers"], key=lambda d: d.get("factor") != "farmer_report")
        ds = "; ".join(_driver(d) for d in drivers[:5])
        out.append(f"  czynniki (silnik, od najważniejszego): {ds}")
    act = expl.get("action") or {}
    if act.get("type"):
        a = f"  zalecenie silnika: {ACTION_PL.get(act['type'], act['type'])}"
        if act.get("threshold"):
            bbch = ((expl.get("growth_stage") or {}).get("bbch"))
            thr = threshold_for_stage(act["threshold"], bbch)
            a += f"; próg (silnik, obecna faza): {thr}" if thr else \
                f"; silnik nie podaje progu dla obecnej fazy (BBCH {bbch}) — tylko lustracja na obecność objawów"
        if act.get("weather_window"):
            a += f"; najbliższe okno pogodowe na zabieg: {act['weather_window']}"
        out.append(a)
    if with_factors and expl.get("factors"):
        fs = "; ".join(f"{FACTOR_LABELS.get(f.get('variable'), f.get('variable'))} {f.get('value')} {f.get('unit', '')}"
                       f" (próg: {f.get('threshold', '?')})" for f in expl["factors"][:4])
        out.append(f"  czynniki: {fs}")
    return out


def field_risk_context(field_id: int, threat_codes: list[str] | None = None, max_threats: int = 3):
    """(context lines, focus threats [dicts], risk citations) for a field, today-3 … today+7."""
    lines, focus = [], []
    if threat_codes:
        for code in threat_codes[:2]:
            try:
                r = call("get_field_risks", field_id=field_id, threat=code)
                focus += r["threats"]
            except ToolError as e:
                log.info("threat %s: %s", code, e)
        field = call("get_field", field_id=field_id)
        rest = []
    else:
        r = call("get_field_risks", field_id=field_id)
        field = r["field"]
        focus = r["threats"][:max_threats]
        rest = [t["threat"] for t in r["threats"][max_threats:]] + r.get("other_threats_low", [])
    lines.append(field_line(field))
    gs = growth_stage_line(focus)
    if gs:
        lines.append(gs)
    lines.append("Ryzyko według silnika decyzyjnego (poziomy silnika: <0,33 niskie, <0,66 średnie, wyżej wysokie):")
    if not focus:
        lines.append("- brak danych o ryzyku dla tego pola w okresie dziś−3 … dziś+7")
    for t in focus:
        lines += threat_lines(t)
    if rest:
        lines.append(f"Pozostałe zagrożenia (niższe ryzyko): {', '.join(rest[:8])}{'…' if len(rest) > 8 else ''}")
    return lines, focus, [t["citation"] for t in focus]


def risk_condition_sources(crop: str | None, threat_names: list[str]) -> list[dict]:
    """Rows of the risk spreadsheet as citable sources (chunk ids ryzyka_zebrane:{crop}.r{row})."""
    if crop not in ("pszenica", "kukurydza"):
        return []
    out = []
    for name in threat_names[:2]:
        rows = call("get_risk_conditions", crop=crop, threat=name)["rows"][:1]
        for r in rows:
            parts = [f"temperatura: {r['temperature_raw']}" if r.get("temperature_raw") else "",
                     f"wilgotność: {r['humidity_raw']}" if r.get("humidity_raw") else "",
                     f"inne: {r['other_factors']}" if r.get("other_factors") else ""]
            out.append({"chunk_id": r["chunk_id"], "citation_text": f"Zestawienie warunków ryzyka, arkusz „{r['sheet']}”, wiersz {r['row']}",
                        "section": "", "kind": "excel_row",
                        "text": f"Warunki sprzyjające ({r['threat']}): " + "; ".join(p for p in parts if p),
                        "citation": {"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": r["sheet"], "row": r["row"]}})
    return out


def guide_sources(queries: list[tuple[str, str | None, int]], budget: int = SOURCES_TOKEN_BUDGET,
                  max_n: int = MAX_SOURCES, exclude: set[str] | None = None) -> tuple[list[dict], str | None]:
    """Run several searches, interleave by rank, dedupe, fit the token budget.
    Returns (sources, error message or None)."""
    from assistant.rag.search import search
    from assistant.rag.store import QdrantUnavailable
    results = []
    try:
        for query in queries:  # (query, crop, k[, topic]); no crop -> only the farm's crops' guides
            q, crop, k = query[:3]
            topic = query[3] if len(query) > 3 else None
            found = search(q, crop=crop or "farm", k=k + (3 if topic else 0), include_pesticide_doses=False)
            if topic:  # a passage cited for a threat must be about that threat
                found = [p for p in found if about(p.text, p.section, topic)][:k]
            results.append(found)
    except QdrantUnavailable:
        return [], "Wyszukiwarka metodyk jest niedostępna — odpowiadaj bez cytatów z metodyk i powiedz o tym."
    except Exception as e:  # noqa: BLE001 - no index yet (bm25.pkl missing, collection not created): answer without it
        log.warning("guide search failed (%s: %s); answering without guide sources", type(e).__name__, e)
        return [], ("Indeks metodyk nie jest zbudowany (python manage.py rag_ingest) — odpowiadaj bez cytatów z "
                    "metodyk i powiedz o tym jednym zdaniem.")
    seen = set(exclude or ())
    merged = []
    for i in range(max((len(r) for r in results), default=0)):
        for r in results:
            if i < len(r) and r[i].chunk_id not in seen:
                seen.add(r[i].chunk_id)
                merged.append(r[i])
    return fit_passages(merged[:max_n * 2], budget)[:max_n], None


WEATHER_WORDS = re.compile(r"pogod|deszcz|opad|pada|padac|temperatur|zimn|ciepl|upal|wiatr|wilgot|przymroz|prognoz|susz|burz")


def asks_about_weather(question: str) -> bool:
    return bool(WEATHER_WORDS.search(domain.fold(question)))


def weather_lines(field_id: int) -> list[str]:
    """Compact daily weather for the field: the last 3 observed days + the forecast (code, no LLM)."""
    import datetime as dt
    today = dt.date.fromisoformat(call("get_season_date")["today"])
    try:
        w = call("get_weather", field_id=field_id, date_from=today - dt.timedelta(days=3),
                 variables=["min_temperature", "max_temperature", "total_precipitation", "avg_relative_humidity",
                            "avg_wind_speed"])
    except ToolError as e:
        return [f"Pogoda: brak danych ({e})."]
    out = ["Pogoda dla pola (ostatnie dni = obserwacja, dalej = prognoza; °C, mm/dzień, %, km/h):"]
    def v(x, unit: str) -> str:
        return "brak danych" if x is None else f"{str(x).replace('.', ',')} {unit}"

    for d in w["days"]:
        rain = v(d["total_precipitation"], "mm")  # observed rain is IMERG (satellite) anyway
        temp = ("brak danych" if d["min_temperature"] is None or d["max_temperature"] is None
                else f"{str(d['min_temperature']).replace('.', ',')}–{str(d['max_temperature']).replace('.', ',')} °C")
        out.append(f"- {d['date']} ({pl_day(d['date'])}) {'prognoza' if d['source'] == 'forecast' else 'obserwacja'}: {temp}, opad {rain}, "
                   f"wilgotność względna {v(d['avg_relative_humidity'], '%')}, wiatr {v(d['avg_wind_speed'], 'km/h')}")
    return out


def mentions(text: str, topic: str) -> bool:
    """Does the text name the topic (a threat name)? Inflection-tolerant: every main word of the topic
    by its first 5 letters (rdza/rdzy, omacnica/omacnicy); words in brackets and short words ignored."""
    words = [w for w in domain.fold(re.sub(r"\(.*?\)", "", topic)).split() if len(w) >= 4][:2]
    t = domain.fold(text)
    stems = [w[:5] if len(w) > 6 else w[:max(3, len(w) - 1)] for w in words]  # rdza/rdzy -> "rdz"
    return bool(stems) and all(re.search(rf"\b{re.escape(s)}", t) for s in stems)


def about(text: str, section: str, topic: str) -> bool:
    """Is a passage about the threat? Prose: the name anywhere (or in the section title). A Markdown table: only
    a row whose first cell names it — a table of leaf spots lists the threat under "możliwość pomylenia" too (A-26)."""
    rows = [line for line in text.splitlines() if line.lstrip().startswith("|")]
    if len(rows) < 2:
        return mentions(text + " " + section, topic)
    if mentions(section, topic):
        return True
    first_cells = [line.strip().strip("|").split("|")[0] for line in rows]
    prose = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("|"))
    return any(mentions(c, topic) for c in first_cells) or mentions(prose, topic)


def threat_query(name: str, crop: str | None) -> str:
    return f"{name} {crop or ''} warunki rozwoju objawy ograniczanie niechemiczne lustracja".strip()


def crop_of_code(code: int | None) -> str | None:
    return domain.CROP_PL.get(code or -1)


# ----------------------------------------------------------------------------- sources fit for today
# Growth stages named in the guides -> BBCH range (cereals and maize). A threshold sentence that names
# only stages far from today's stage is about another part of the season.
PHASES = [(r"kielk|wschod|wschodz", 0, 19), (r"\bliscia?\b|faz\w* (\d-)?\d+ lisc|\d+[-–]\d+ lisci", 10, 19),
          (r"krzewien|krzewi", 20, 29), (r"strzelan\w* w zdzbl|\bzdzbl\w* (sie )?wydluz", 30, 39),
          (r"lisc\w* flagow|nabrzmiew|bbch 3[7-9]|bbch 4", 37, 49), (r"klosz|wyrzucan\w* wiech", 50, 59),
          (r"kwitn", 60, 69), (r"dojrzew|dojrzal|mleczn|woskow|pelna dojrz|rozw\w* ziarn", 70, 92)]
THRESHOLD_WORDS = re.compile(r"%|\bprog|\bszt\b|osobnik|na 1 m|na roslin|na lisc|na klos")
# advice for greenhouses, gardens and allotments, or against the law on a farm field
# Whole words or phrases only: "wietrz" alone also matched "powietrza" (every humidity sentence), "rozsad" matched
# "rozsądny", "inspekt" matched "inspektor" (PIORiN) and "palenie" matched "zapalenie".
NOT_FIELD = re.compile(r"\bszklarn|\btunel\w* foliow|\bpod oslon(a|ami)\b|\binspekt(y|ach|ow)?\b|\bogrod(u|zie|y|ach|ow)?\b|"
                       r"\bogrodk|\bdoniczk|\brozsad(a|y|e|zie|ami)?\b|\bwietrzeni\w*|\bwietrzyc\b|\bcyrkulacj\w* powietrza|"
                       r"\bspal\w* (resztk|reszt|slom|liscie|roslin)|\bpaleni[aeu]\b|\bpalic\b|"
                       r"\bzbiera\w* (recznie|reka)")
SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+")
# advice that can only be done after harvest or before sowing: kept, but marked as next season's once the crop grows
NEXT_SEASON = re.compile(r"resztk\w* (pozniw|roslin)|\bprzyora|\bzaora|\borka\b|\borke\b|\bpodoryw|plodozmian|"
                         r"\bdob\w* odmian|odmian\w* (odporn|mniej podatn)|termin\w* siewu|gestos\w* siewu|zaprawian")


def current_bbch(threats: list[dict]) -> int | None:
    for t in threats:
        gs = (t.get("explanation") or {}).get("growth_stage") or {}
        if gs.get("bbch") is not None:
            try:
                return int(gs["bbch"])
            except (TypeError, ValueError):
                return None
    return None


def _phase_ranges(folded: str) -> list[tuple[int, int]]:
    out = [(lo, hi) for pat, lo, hi in PHASES if re.search(pat, folded)]
    out += [(int(b), int(b)) for b in re.findall(r"bbch\s*(\d{1,2})", folded)]
    return out


def fit_for_today(text: str, bbch: int | None) -> str:
    """Drop sentences that do not apply on a farm field today: threshold sentences of growth stages far
    from today's (more than 10 BBCH away) and greenhouse/garden advice."""
    kept = []
    for sent in SENT_SPLIT.split(text):
        f = domain.fold(sent)
        if NOT_FIELD.search(f):
            continue
        if bbch is not None and (THRESHOLD_WORDS.search(f) or "%" in sent):
            ranges = _phase_ranges(f)
            if ranges and not any(lo - 10 <= bbch <= hi + 10 for lo, hi in ranges):
                continue
        if bbch is not None and bbch >= 30 and NEXT_SEASON.search(f):
            sent = sent.rstrip() + " (rada na przyszły sezon)"
        kept.append(sent)
    return " ".join(kept)


def adapt_sources(sources: list[dict], bbch: int | None) -> list[dict]:
    out = []
    for s in sources:
        text = fit_for_today(s["text"], bbch)
        if len(text) >= 40 or s.get("kind") == "excel_row":
            out.append(s | {"text": text or s["text"]})
    return out


def phase_rule_lines(threats: list[dict]) -> list[str]:
    bbch = current_bbch(threats)
    if bbch is None:
        return []
    return [f"Progi szkodliwości: podawaj TYLKO próg dla obecnej fazy (BBCH {bbch}) — zalecenie silnika albo "
            "próg ze źródeł, który wprost dotyczy tej fazy. Jeśli źródła nie podają progu dla tej fazy, napisz, "
            "że metodyka nie podaje progu na tę fazę, i zaproponuj lustrację na obecność objawów."]


def threshold_for_stage(threshold: str, bbch) -> str:
    """The engine's threshold text lists several stages ("Krzewienie: 10-15 % …; strzelanie w źdźbło:
    5 % liści."). Keep the parts about today's stage (±10 BBCH) and the parts naming no stage."""
    try:
        bbch = int(bbch)
    except (TypeError, ValueError):
        return threshold
    keep = []
    for part in re.split(r";\s*", threshold.strip().rstrip(".")):
        ranges = _phase_ranges(domain.fold(part))
        if not ranges or any(lo - 10 <= bbch <= hi + 10 for lo, hi in ranges):
            keep.append(part)
    return "; ".join(keep)


def drop_off_field(text: str) -> str:
    """Remove sentences of the answer that give greenhouse/garden advice (the model sometimes adds them)."""
    lines = []
    for line in text.split("\n"):  # line by line: keeps Markdown paragraphs and list items
        if not line.strip():
            lines.append(line)
            continue
        kept = [s for s in SENT_SPLIT.split(line) if not NOT_FIELD.search(domain.fold(s))]
        if kept:
            lines.append(" ".join(kept))
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or text
