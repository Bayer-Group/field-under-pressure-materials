"""
Flows per question type. Code decides and fetches; the model writes. At most ONE LLM call per flow
(the observation extraction is its own single call).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from assistant import domain
from assistant.tools.registry import ToolError, call

from . import context as ctx
from . import guard
from .llm import LLM, LLMResult, log_usage, strip_think
from .prompts import build_messages
from .router import Route

log = logging.getLogger("assistant.orchestrator")


@dataclass
class FlowResult:
    text: str
    sources: list[dict] = field(default_factory=list)        # passages given to the model (citable)
    risk_citations: list[dict] = field(default_factory=list)
    focus_field_id: int | None = None
    updated_field_ids: list[int] = field(default_factory=list)
    chart: dict | None = None
    pending_action: dict | None = None
    meta: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- the one LLM call
SENTENCE_END = re.compile(r"[.!?…](\s*\[[^\]]+\])*[)\"”]?\s*$")


def fix_bold(text: str) -> str:
    """Remove nested **bold** (e.g. „**Lustracja **Za Stodołą** dziś**” -> „**Lustracja Za Stodołą dziś**”):
    Markdown cannot nest it and shows the asterisks. Line by line; a marker opens when followed by a
    non-space and preceded by a space or the line start."""
    out = []
    for line in text.split("\n"):
        res, depth, i = [], 0, 0
        while i < len(line):
            if line.startswith("**", i):
                prev = line[i - 1] if i else " "
                nxt = line[i + 2] if i + 2 < len(line) else " "
                opens = not nxt.isspace() and (prev.isspace() or prev in "([„\"-–" or depth == 0)
                if opens and depth == 0:
                    res.append("**"); depth = 1
                elif opens:
                    depth += 1                      # nested opener: drop
                elif depth > 1:
                    depth -= 1                      # its closer: drop
                else:
                    res.append("**"); depth = max(0, depth - 1)
                i += 2
                continue
            res.append(line[i]); i += 1
        joined = "".join(res)
        if depth >= 1:  # an opener never closed on this line: close it, or the asterisks show
            stripped = joined.rstrip()
            joined = stripped + "**" + joined[len(stripped):] if not stripped.endswith("**") else joined
        out.append(joined)
    return "\n".join(out)


def finish_sentence(text: str) -> str:
    """An answer cut by the output limit ends mid-sentence: drop the unfinished tail — back to the last
    whole sentence (with its [citations]) or the last whole line (list item). Call only for cut answers."""
    t = text.rstrip()
    if not t or SENTENCE_END.search(t):
        return t
    ends = [m.end() for m in re.finditer(r"[.!?…](\s*\[[^\]]+\])*(?=\s)", t)]
    ends += [m.start() for m in re.finditer(r"\n", t)]
    cut = max(ends, default=0)
    if cut < len(t) * 0.4:
        return t
    return t[:cut].rstrip()


def _clean(raw: str, truncated: bool) -> str:
    """The same post-processing for every answer the model writes (first try and regeneration)."""
    text = strip_think(raw)
    text = finish_sentence(text) if truncated else text
    return fix_bold(ctx.drop_off_field(text))


def ask_llm(llm: LLM, kind: str, context_lines, sources, question, history, instructions="",
            max_tokens: int | None = None, conversation_id=None) -> tuple[str, dict]:
    messages, info = build_messages(context_lines, sources, history, question, instructions)
    res: LLMResult = llm.complete(messages, max_tokens=max_tokens)
    calls = [log_usage(res, kind=kind, extra={"conversation_id": conversation_id})]
    text = _clean(res.text, res.truncated)
    doses = guard.find_doses(text)
    if doses:
        log.warning("dose in answer (%s): %s — regenerating once", kind, doses)
        retry = messages + [{"role": "assistant", "content": text}, {"role": "user", "content": guard.REGENERATE_NOTE}]
        res2 = llm.complete(retry, max_tokens=max_tokens)
        calls.append(log_usage(res2, kind=kind + ":regenerate", extra={"conversation_id": conversation_id}))
        text = _clean(res2.text, res2.truncated)
        if guard.find_doses(text):
            log.warning("dose again after regeneration — safe message")
            text = guard.SAFE_MESSAGE
    meta = {"llm_calls": calls, "prompt_info": info, "guard_triggered": bool(doses),
            "llm_errors": list(getattr(res, "fallback_errors", None) or []),
            "prompt": messages}  # the prompt is kept for `manage.py chat --show-prompt`, not stored in Message.meta
    return text, meta


# ----------------------------------------------------------------------------- dose requests
DOSE_INTENT = re.compile(r"\bdawk|ile (litr|ml|mililitr|gram|kilogram|kg)|\b(l|ml|g|kg)\s*/\s*ha|jaki(m|ego)? (srod|preparat|fungicyd|herbicyd|insektycyd)|"
                         r"czym (opryskac|pryskac|zwalczyc)|nazw\w* (srod|preparat)|jaki fungicyd|jaki herbicyd|jaki insektycyd")
DOSE_INSTRUCTION = ("Rolnik pyta o środek ochrony roślin lub dawkę. NIE podawaj nazw środków ani dawek. Napisz wprost, "
                    "że dobór środka i dawki jest według aktualnej etykiety i w porozumieniu z doradcą. Możesz opisać "
                    "progi szkodliwości, termin lustracji i metody niechemiczne z cytatami.")
LABEL_REFERRAL = "Dobór środka i dawki — zawsze według aktualnej etykiety środka; w razie wątpliwości skonsultuj się z doradcą."


def asks_for_dose(question: str) -> bool:
    return bool(DOSE_INTENT.search(domain.fold(question)))


def ensure_referral(text: str, question: str) -> str:
    if asks_for_dose(question) and "etykiet" not in text.lower():
        text = text.rstrip() + "\n\n" + LABEL_REFERRAL
    return text


# ----------------------------------------------------------------------------- general question
CROP_CODE = {"pszenica": 1110, "kukurydza": 1130}


def general(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    crop = route.crop
    crop_code = CROP_CODE.get(crop or "")
    t = domain.fold(question)
    from .router import RISK_INTENT, _any
    # "Co nadal grozi pszenicy?": the farm's own risks for that crop, not just the guides (A-24)
    if crop_code and not route.threats and _any(RISK_INTENT, t):
        return farm_summary(route, question, history, llm, conv_id, crop_code=crop_code)
    # "Czy jutro będzie padać?": the weather of the most endangered field (of that crop), said so (A-24)
    if ctx.asks_about_weather(question):
        s = call("get_farm_risk_summary")
        candidates = [f for f in s["fields"] if not crop_code or f.get("crop_code") == crop_code]
        if candidates:
            fid = candidates[0]["id"]
            lines = ctx.season_lines() + ctx.weather_lines(fid) + [
                f"Rolnik nie wskazał pola: pogoda pochodzi z siatki pola {candidates[0]['name']} (najbardziej zagrożone"
                + (f" pole uprawy {crop}" if crop_code else "") + "); pola gospodarstwa leżą blisko, powiedz o tym jednym zdaniem."]
            instructions = ("Odpowiedz na pytanie o pogodę liczbami z kontekstu (dni i wartości), 2–4 zdania; jeśli pogoda "
                            "sprzyja chorobom albo zabiegom, powiedz to jednym zdaniem.")
            text, meta = ask_llm(llm, route.type, lines, [], question, history, instructions, conversation_id=conv_id)
            meta["field_id"] = fid
            return FlowResult(text, meta=meta)
    sources, err = ctx.guide_sources([(question, crop, 4)], budget=1800, max_n=4)
    if route.threats and crop in ("pszenica", "kukurydza"):
        from core.models import Threat
        names = list(Threat.objects.filter(code__in=route.threats).values_list("name", flat=True))
        sources = ctx.risk_condition_sources(crop, names)[:1] + sources
    lines = ctx.season_lines() + ([f"Uprawa z pytania: {crop}"] if crop else []) + ([err] if err else [])
    other = domain.crop_in_text(question)
    if other and other not in domain.CROP_PL:  # rzepak, ziemniak…: no guides here, say so instead of guessing
        lines.append("Rolnik pyta o uprawę, dla której aplikacja nie ma metodyk (są tylko dla pszenicy i kukurydzy): "
                     "powiedz to jednym zdaniem i nie odpowiadaj z pamięci.")
    instructions = "Odpowiedz na pytanie na podstawie źródeł, z cytatami."
    if asks_for_dose(question):
        instructions += " " + DOSE_INSTRUCTION
    text, meta = ask_llm(llm, route.type, lines, sources, question, history, instructions, conversation_id=conv_id)
    return FlowResult(ensure_referral(text, question), sources=sources, meta=meta | {"dose_request": asks_for_dose(question)})


# ----------------------------------------------------------------------------- question about a field
INTENTS = [
    ("action", re.compile(r"\bco (\w+ ){0,3}(robic|zrobic|zrobie|robie|radzisz|polecasz)|\bjak (\w+ ){0,2}(zmniejszyc|ograniczyc|"
                          r"chronic|ochronic|zapobiec|uratowac|ratowac|walczyc|zwalczyc)|zmniejsz|ogranicz|zapobieg|\bochron|"
                          r"\bco dalej|\bco teraz|\bjakie (dzialania|kroki)")),
    ("symptoms", re.compile(r"objaw|jak (to )?wyglada|rozpozn|po czym (\w+ )?pozna|jak (\w+ )?sprawdzic|na co patrzec")),
    ("why", re.compile(r"dlaczego|czemu|\bskad\b|z jakiego powodu|\bpowod|na czerwono|na zolto")),
]
FOCUS = {
    "action": ("Rolnik pyta, CO ZROBIĆ. Pierwsze zdanie = najważniejsze działanie dziś, pogrubione. Potem lista "
               "punktowana działań: co i gdzie obejrzeć przy lustracji, próg dla obecnej fazy (jeśli jest w kontekście), okno zabiegu i kiedy dzwonić do "
               "doradcy, metody niechemiczne wykonalne teraz na polu (tylko ze źródeł). Powody ryzyka najwyżej "
               "w pół zdania, bez opisu objawów."),
    "symptoms": ("Rolnik pyta o OBJAWY. Zacznij od opisu objawów z metodyki (z cytatem), najważniejszy objaw pogrubiony: na jakim organie, jak "
                 "wyglądają, z czym ich nie pomylić. Na końcu jedno zdanie, co zrobić, jeśli je zobaczy."),
    "why": ("Rolnik pyta DLACZEGO. Zacznij od pogrubionego głównego powodu z silnika (pogoda, faza, przedplon — liczby z kontekstu), "
            "potem jedno zdanie z metodyki z cytatem i jedno zdanie, co zrobić teraz."),
    "why_action": ("Rolnik pyta DLACZEGO i CO ZROBIĆ. Najpierw powody z silnika w 1–2 zdaniach (liczby z kontekstu), "
                   "potem lista punktowana działań, najważniejsze pogrubione: lustracja (co i gdzie obejrzeć, próg dla obecnej fazy, jeśli jest), okno zabiegu, "
                   "kiedy dzwonić do doradcy. Objawy z metodyki najwyżej jednym zdaniem z cytatem."),
    "general": ("Odpowiedz wprost na pytanie w pierwszym zdaniu. Potem: dlaczego (powody z silnika), co mówi "
                "metodyka (z cytatem), co zrobić teraz."),
}


def question_intent(question: str) -> str:
    t = domain.fold(question)
    found = [name for name, pat in INTENTS if pat.search(t)]
    if "why" in found and "action" in found:
        return "why_action"
    return found[0] if found else "general"


def field_instructions(question: str, follow_up: bool) -> str:
    out = [FOCUS[question_intent(question)],
           "3–6 zdań, bez nagłówków i bez podsumowań na końcu. Głównie najgroźniejsze zagrożenie; drugie tylko "
           "jednym–dwoma zdaniami, jeśli też jest wysokie lub średnie. Nie wymieniaj pozostałych zagrożeń, "
           "chyba że rolnik o nie pyta.",
           "Rozbieżność silnika i metodyki zgłaszaj tylko wtedy, gdy naprawdę jest — inaczej nic o tym nie pisz."]
    if follow_up:
        out.append("To dopytanie w tej samej rozmowie: NIE powtarzaj powodów ani objawów z poprzedniej odpowiedzi "
                   "(<historia>), odpowiedz tylko na nowe pytanie.")
    return " ".join(out)


def _pick_field(route: Route) -> tuple[int | None, str]:
    if route.field_id:
        return route.field_id, route.field_source
    s = call("get_farm_risk_summary")
    if s["fields"]:
        return s["fields"][0]["id"], "highest_risk"
    return None, ""


def field_question(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    field_id, how = _pick_field(route)
    if field_id is None:
        return FlowResult("Nie mam jeszcze danych o polach gospodarstwa, więc nie mogę ocenić ryzyka.")
    lines = ctx.season_lines()
    risk_lines, focus, risk_cits = ctx.field_risk_context(field_id, route.threats or None, max_threats=2)
    lines += risk_lines
    if ctx.asks_about_weather(question):
        lines += ctx.weather_lines(field_id)
    if how == "highest_risk":
        lines.append("Uwaga: rolnik nie wskazał pola — wybrano pole o najwyższym ryzyku dziś; powiedz na początku, "
                     "którego pola dotyczy odpowiedź.")
    crop = route.crop or ctx.crop_of_code(call("get_field", field_id=field_id)["crop_code"])
    top = [t for t in focus][:2]
    queries = [(ctx.threat_query(t["threat"], crop), crop, 3, t["threat"]) for t in top]
    if route.threats or len(question.split()) > 6:  # a specific question adds its own search
        queries.append((question, crop, 3))
    sources, err = ctx.guide_sources(queries, budget=ctx.SOURCES_TOKEN_BUDGET, max_n=ctx.MAX_SOURCES)
    sources = ctx.risk_condition_sources(crop, [t["threat"] for t in top]) + sources
    sources = ctx.adapt_sources(sources[:ctx.MAX_SOURCES + 1], ctx.current_bbch(focus))
    lines += ctx.phase_rule_lines(focus)
    if err:
        lines.append(err)
    instructions = field_instructions(question, bool(history))
    if asks_for_dose(question):
        instructions += " " + DOSE_INSTRUCTION
    text, meta = ask_llm(llm, route.type, lines, sources, question, history, instructions, conversation_id=conv_id)
    meta["field_id"], meta["field_choice"] = field_id, how
    return FlowResult(ensure_referral(text, question), sources=sources, risk_citations=risk_cits,
                      focus_field_id=field_id if how not in ("selected", "conversation") else None, meta=meta)


# ----------------------------------------------------------------------------- farm overview
def farm_groups(s: dict, max_groups: int = 3) -> list[list[dict]]:
    """
    Each field's most dangerous threat, fields with the same threat and level in one group (three wheat fields
    with the same leaf spot are one point, not three), most urgent first; every crop of the farm gets at least its
    most urgent group, so maize is not left out when the wheat is worse.
    """
    crop_of = {f["id"]: f.get("crop_code") for f in s["fields"]}
    groups: dict[tuple, list[dict]] = {}
    for p in s.get("leaders") or s["most_urgent"]:
        groups.setdefault((p["threat_code"], p["level"]), []).append(p)
    ordered = sorted(groups.values(), key=lambda g: -max(p["score"] for p in g))
    picked = ordered[:max_groups]
    for g in ordered[max_groups:]:
        crop = crop_of.get(g[0]["field_id"])
        if crop not in {crop_of.get(x[0]["field_id"]) for x in picked}:
            picked.append(g)
    return picked


def compare_fields(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    """"Porównaj Klin i Górkę": each named field's main threats and reasons, then the model compares them."""
    lines = ctx.season_lines() + ["Porównywane pola (silnik):"]
    risk_cits, focus_all = [], []
    for fid in route.field_ids[:4]:
        risk_lines, focus, cits = ctx.field_risk_context(fid, None, max_threats=2)
        lines += risk_lines
        risk_cits += cits
        focus_all += focus
    crop = route.crop
    queries = [(ctx.threat_query(t["threat"], crop), crop, 2, t["threat"]) for t in focus_all[:2]]
    sources, err = ctx.guide_sources(queries, budget=1400, max_n=3) if queries else ([], None)
    if err:
        lines.append(err)
    instructions = ("Rolnik porównuje pola. Pierwsze zdanie: które pole jest bardziej zagrożone i czym (pogrubiona nazwa "
                    "pola). Potem po jednym punkcie listy na pole: główne zagrożenie, poziom i powód z silnika. Na końcu "
                    "jedno zdanie, od którego pola zacząć lustrację. Najwyżej 6 zdań.")
    text, meta = ask_llm(llm, "porownanie", lines, sources, question, history, instructions, conversation_id=conv_id)
    meta["field_id"] = route.field_ids[0]
    return FlowResult(ensure_referral(text, question), sources=sources, risk_citations=risk_cits, meta=meta)


def farm_summary(route: Route, question: str, history, llm: LLM, conv_id=None, crop_code: int | None = None) -> FlowResult:
    """crop_code: only the fields of that crop ("Co grozi pszenicy?")."""
    if len(route.field_ids) >= 2:
        return compare_fields(route, question, history, llm, conv_id)
    s = call("get_farm_risk_summary")
    if crop_code:
        ids = {f["id"] for f in s["fields"] if f.get("crop_code") == crop_code}
        s = s | {"fields": [f for f in s["fields"] if f["id"] in ids],
                 "leaders": [p for p in s.get("leaders", []) if p["field_id"] in ids],
                 "most_urgent": [p for p in s["most_urgent"] if p["field_id"] in ids]}
    lines = ctx.season_lines() + ["Najpilniejsze zagrożenia gospodarstwa (silnik; pola z tym samym zagrożeniem razem):"]
    groups = farm_groups(s)
    picked = [g[0] for g in groups]
    for g in groups:
        p = g[0]
        names = ", ".join(f"{x['field']} (id {x['field_id']}, {ctx._fmt(x['score'])})" for x in g)
        lines.append(f"- {p['threat']} [silnik:{p['threat_code']}] — {p['level']}, trend {p['trend']}; pola: {names}; "
                     f"powody (silnik, {p['field']}): {p['explanation']}")
    lines.append("Wszystkie pola (maks. ryzyko dziś): " + "; ".join(
        f"{f['name']} {ctx._fmt(f['max_score']) if f['max_score'] is not None else '—'} ({f['max_level']})" for f in s["fields"]))
    crops = {}
    for p in picked:
        crop = ctx.crop_of_code(next(f["crop_code"] for f in s["fields"] if f["id"] == p["field_id"]))
        crops.setdefault(p["threat"], crop)
    threats = list(crops.items())[:2]
    sources, err = ctx.guide_sources([(ctx.threat_query(t, c), c, 2, t) for t, c in threats], budget=1600, max_n=4)
    if err:
        lines.append(err)
    instructions = ("Omów TYLKO zagrożenia z listy „Najpilniejsze zagrożenia”, od najpilniejszego. Każde to osobny punkt "
                    "listy zaczynający się od pogrubionych nazw pól, których dotyczy: zagrożenie, powód z silnika i JEDNO "
                    "konkretne działanie wykonalne teraz (np. lustracja), z cytatem metodyki, jeśli pasuje; 1–2 zdania na "
                    "punkt, całość najwyżej 8 zdań. Pozostałe pola wspomnij jednym zdaniem na końcu (bez wymyślania "
                    "powodów). Bez podsumowań i bez uwag o zgodności silnika z metodyką.")
    if asks_for_dose(question):
        instructions += " " + DOSE_INSTRUCTION
    sources = ctx.adapt_sources(sources, None)  # several fields and stages: only the greenhouse/garden filter
    text, meta = ask_llm(llm, route.type, lines, sources, question, history, instructions, conversation_id=conv_id)
    if picked:  # a follow-up ("co mam zrobić?") continues with the most urgent field
        meta["field_id"] = picked[0]["field_id"]
    # "Które pole jest najbardziej zagrożone?": the map shows the answer's first field (unless one is selected)
    focus = picked[0]["field_id"] if picked and route.field_source != "selected" else None
    return FlowResult(ensure_referral(text, question), sources=sources, focus_field_id=focus,
                      risk_citations=[p["citation"] for g in groups for p in g], meta=meta)


# ----------------------------------------------------------------------------- charts
WEATHER_WORDS = {"opad": "total_precipitation", "deszcz": "total_precipitation",
                 "wilgot": "avg_relative_humidity", "temperatur": "avg_temperature", "cieplo": "avg_temperature"}


def chart(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    q = domain.fold(question)
    fields = route.field_ids or ([route.field_id] if route.field_id else [])
    if not fields:
        fid, _ = _pick_field(route)
        fields = [fid] if fid else []
    if not fields:
        return FlowResult("Nie mam danych o polach, więc nie mogę narysować wykresu.")
    threat = route.threats[0] if route.threats else None
    note = ""
    if threat is None:
        asked = domain.resolve_threats(question)  # a threat of another crop ("septorioza" on a maize field)?
        r = call("get_field_risks", field_id=fields[0])
        if not r["threats"]:
            return FlowResult("Na tym polu nie ma teraz istotnych zagrożeń do pokazania na wykresie.")
        threat = r["threats"][0]["threat_code"]
        if asked:
            note = (f"„{asked[0].name}” nie dotyczy uprawy tego pola, więc pokazuję jego najgroźniejsze zagrożenie: "
                    f"{r['threats'][0]['threat']}.\n\n")
    variable = next((v for k, v in WEATHER_WORDS.items() if k in q), None)
    try:
        if variable:
            res = call("chart_weather_vs_risk", field_id=fields[0], variable=variable, threat=threat)
        else:
            res = call("chart_risk_timeline", field_ids=fields[:6], threat=threat)
    except ToolError as e:
        return FlowResult(f"Nie mogę przygotować wykresu: {e}")
    import json
    summary = json.dumps(res["summary"], ensure_ascii=False, default=str)
    lines = ctx.season_lines() + [f"Podsumowanie wykresu (liczby policzone przez aplikację): {summary}"]
    text, meta = ask_llm(llm, route.type, lines, [], question, [],
                         "Napisz 1–2 zdania komentarza do wykresu, używając WYŁĄCZNIE liczb z podsumowania. "
                         "Nie cytuj metodyk.", max_tokens=700, conversation_id=conv_id)  # reasoning models think first
    return FlowResult(note + text, risk_citations=res.get("citations", []), chart=res["chart"],
                      meta=meta | {"chart_summary": res["summary"]})


# ----------------------------------------------------------------------------- out of scope
CAPABILITIES = ("Jestem asystentem agronomicznym dla pszenicy i kukurydzy w tym gospodarstwie. Mogę: wyjaśnić, "
                "dlaczego pole jest zagrożone (na podstawie oceny ryzyka), podać warunki rozwoju chorób i szkodników "
                "z oficjalnych metodyk integrowanej ochrony roślin (z cytatami), pokazać wykres ryzyka lub pogody, "
                "podsumować najpilniejsze pola i zapisać Twoją obserwację z pola. Nie doradzam środków ochrony "
                "roślin ani dawek.")


THANKS_REPLY = "Proszę bardzo. Jeśli coś się zmieni na polu, napisz albo zaznacz pole na mapie."


def out_of_scope(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    if route.reason == "thanks":
        return FlowResult(THANKS_REPLY, meta={"llm_calls": []})
    return FlowResult(CAPABILITIES, meta={"llm_calls": []})


def complex_question(route: Route, question: str, history, llm: LLM, conv_id=None) -> FlowResult:
    """Agent mode is optional (step G); without it complex questions use the single-call flows."""
    if route.field_id or route.field_ids:
        return field_question(route, question, history, llm, conv_id)
    return farm_summary(route, question, history, llm, conv_id)


def strip_markdown_noise(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()
