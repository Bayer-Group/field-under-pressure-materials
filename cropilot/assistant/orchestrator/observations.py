"""
Observation flow: message -> (1 LLM call, JSON) draft -> code fills/validates -> farmer confirms ->
record_observation (idempotent) -> engine reassessment -> answer from a template (no LLM).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from assistant import domain
from assistant.tools.registry import ToolError, call

from .flows import FlowResult
from .llm import LLM, complete_json, log_usage
from .router import Route

log = logging.getLogger("assistant.orchestrator")

CATEGORY_PL = {"choroba": "choroba", "szkodnik": "szkodnik", "chwasty": "chwasty", "uszkodzenie": "uszkodzenie",
               "inne": "inne"}


KIND_PL = {"symptoms": "objawy na polu", "absence": "lustracja — pole czyste", "neighbour": "zgłoszenie od sąsiada",
           "treatment": "wykonany zabieg", "field_fact": "informacja o polu", "event": "zdarzenie (grad / wyleganie / zalanie)"}
MONTHS = {"stycz": 1, "lut": 2, "mar": 3, "kwie": 4, "maj": 5, "czerw": 6, "lip": 7, "sierp": 8, "wrze": 9,
          "pazdziern": 10, "listop": 11, "grud": 12}


def detect_kind(text: str, today: dt.date) -> tuple[str, dict]:
    """Report kind + engine facts from the farmer's words, by rules (no LLM). Default: symptoms."""
    t = domain.fold(text)
    facts: dict = {}
    # "położyło się zboże" is lodging; "położyłem pułapki" is not (A-28e)
    if m := re.search(r"\b(grad|wylegl|polegl|polozyl(?=\w* (sie|zboz|pszen|lan|kukur|rosl))|zalal|zalane|podtop)", t):
        word = m.group(1)
        facts["type"] = "hail" if word == "grad" else "flood" if word.startswith(("zal", "podtop")) else "lodging"
        return "event", facts
    if re.search(r"\b(sial\w*|zasial\w*|posial\w*|wysial\w*)\b", t) and (d := parse_pl_date(t, today, past_season=True)):
        facts["sowing_date"] = d.isoformat()
        return "field_fact", facts
    if re.search(r"nie oral|bez orki|nie orze|uproszczon|talerzow|siew bezposredni", t):
        facts["tillage"] = "reduced"
        return "field_fact", facts
    if re.search(r"\b(oprysk\w*al\w*|pryskal\w*|zrobil\w* zabieg|wykonal\w* zabieg)", t):
        return "treatment", facts
    if re.search(r"sasiad|u sasiada|w okolicy|we wsi", t):
        facts["distance_m"] = 300 if re.search(r"za drog|obok|przez miedz|zaraz", t) else 1500 if re.search(r"we wsi|w okolicy", t) else 1000
        return "neighbour", facts
    if re.search(r"czyst|nic nie (ma|znalazl|widac)|nie widze|brak objaw|zdrowe|bez objaw|nie ma (zadnych |zadnego )?(objaw|plam|szkodnik|mszyc|chorob)|nie znalazl", t):
        return "absence", facts
    return "symptoms", facts


def parse_pl_date(t: str, today: dt.date, past_season: bool = False) -> dt.date | None:
    """'8 pazdziernika', '25.09', '2024-09-25' (folded text) -> date not after today."""
    if m := re.search(r"(20\d\d)-(\d\d)-(\d\d)", t):
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    day = month = None
    for m in re.finditer(r"\b(\d{1,2})\s+([a-z]+)", t):  # "3 dni, 8 października": the first number + month (A-28e)
        mon = next((v for k, v in MONTHS.items() if m.group(2).startswith(k)), None)
        if mon:
            day, month = int(m.group(1)), mon
            break
    if day is None and (m := re.search(r"\b(\d{1,2})\.(\d{1,2})\b", t)):
        day, month = int(m.group(1)), int(m.group(2))
    if day is None:
        return None
    try:
        d = dt.date(today.year, month, day)
    except ValueError:
        return None
    return d if d <= today else dt.date(today.year - 1, month, day)


class DraftOut(BaseModel):
    field_id: int | None = None
    date: dt.date | None = None
    category: Literal["choroba", "szkodnik", "chwasty", "uszkodzenie", "inne"] | None = None
    threat: str | None = None
    severity: Literal["niskie", "srednie", "wysokie"] | None = None
    note: str = ""
    missing: list[str] = Field(default_factory=list)


EXTRACT_SYSTEM = ("Wyodrębniasz obserwację rolnika z pola do formularza. Zwracasz wyłącznie JSON z kluczami: "
                  "field_id (id z listy pól albo null), date (YYYY-MM-DD albo null), category (choroba|szkodnik|chwasty|"
                  "uszkodzenie|inne albo null), threat (nazwa z listy zagrożeń albo null — nie zgaduj), severity "
                  "(niskie|srednie|wysokie albo null), note (opis rolnika jego słowami, krótko), missing (lista "
                  "brakujących informacji). Nie wymyślaj pól ani zagrożeń spoza list.")


WEEKDAYS = ["poniedzial", "wtor", "srod", "czwart", "piat", "sobot", "niedziel"]  # folded stems, Monday first


def _relative_date(message: str, today: dt.date) -> dt.date | None:
    t = domain.fold(message)
    if "przedwczoraj" in t:
        return today - dt.timedelta(days=2)
    if "wczoraj" in t:
        return today - dt.timedelta(days=1)
    m = re.search(r"(\d+)\s+dni\s+temu", t)
    if m:
        return today - dt.timedelta(days=int(m.group(1)))
    m = re.search(r"\b(\d+|dwa|trzy)?\s*tygodni\w*\s+temu|\btydzien\s+temu", t)  # "tydzień temu", "2 tygodnie temu"
    if m:
        n = {"dwa": 2, "trzy": 3}.get(m.group(1) or "", int(m.group(1)) if (m.group(1) or "").isdigit() else 1)
        return today - dt.timedelta(days=7 * n)
    for k, name in enumerate(WEEKDAYS):  # "w poniedziałek": the last such day before today
        if re.search(rf"\bw\s+{name}", t):
            back = (today.weekday() - k) % 7 or 7
            return today - dt.timedelta(days=back)
    if "dzis" in t or "dzisiaj" in t or "rano" in t:
        return today
    return None


SYMPTOM_WORDS = re.compile(r"objaw|plam|nalot|przebarw|zolkn|brazow|wiedn|zamier|uszkodz|zeruj|wygryz|otwor|"
                           r"chodnik|zlaman|deformac|gnic|zgnil|skrecan|kolonie|pustul|pierscien")


def symptom_snippet(text: str, threat_name: str, limit: int = 260) -> str:
    """For a Markdown table: the cells of the row about this threat; otherwise the start of the text."""
    key = domain.fold(threat_name).split()[:2]
    for line in text.splitlines():
        if line.startswith("|") and key and all(k[:5] in domain.fold(line) for k in key):
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
            text = " — ".join(cells[1:]) if len(cells) > 1 else cells[0]
            break
    else:  # prose: start at the first sentence about symptoms, not at a description of the insect or fungus
        sentences = re.split(r"(?<=[.;!?])\s+", text)
        i = next((k for k, x in enumerate(sentences) if SYMPTOM_WORDS.search(domain.fold(x))), 0)
        text = " ".join(sentences[i:])
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def draft_text(d: dict) -> str:
    sev = {"niskie": "niskie", "srednie": "średnie", "wysokie": "wysokie"}.get(d.get("severity") or "", "nie podano")
    lines = [f"**Szkic obserwacji** ({KIND_PL.get(d.get('kind'), 'obserwacja')})", f"- pole: {d['field']}",
             f"- data: {d['date']}", f"- kategoria: {d['category']}", f"- zagrożenie: {d.get('threat') or 'nie wskazano'}"]
    if d.get("kind") in (None, "symptoms"):
        lines.append(f"- nasilenie: {sev}")
    facts = d.get("facts") or {}
    if facts.get("sowing_date"):
        lines.append(f"- data siewu: {facts['sowing_date']}")
    if facts.get("tillage"):
        lines.append("- uprawa: bez orki (uproszczona)" if facts["tillage"] == "reduced" else "- uprawa: orka")
    if facts.get("distance_m"):
        lines.append(f"- odległość od pola: ok. {facts['distance_m']} m")
    if facts.get("type"):
        lines.append(f"- zdarzenie: {({'hail': 'grad', 'lodging': 'wyleganie', 'flood': 'zalanie'})[facts['type']]}")
    lines.append(f"- opis: {d['note']}")
    return "\n".join(lines)


def observation(route: Route, question: str, history, llm: LLM, state, selected_field, conv_id=None) -> FlowResult:
    today = dt.date.fromisoformat(call("get_season_date")["today"])
    fields = call("list_fields")["fields"]
    prev = route.previous_draft  # "tak, ale to było na polu Klin": correct the pending draft, don't start over
    if prev:
        question = (f"{prev.get('note') or ''}\nPoprawka rolnika do tej obserwacji (ważniejsza niż powyższe): {question}")
        if not route.field_id and prev.get("field_id"):
            route.field_id = prev["field_id"]
    crop_code = route.crop and {"pszenica": 1110, "kukurydza": 1130}.get(route.crop)
    if route.field_id:
        crop_code = next((f["crop_code"] for f in fields if f["id"] == route.field_id), crop_code)
    from core.models import Threat
    threat_names = list(Threat.objects.filter(**({"crop_id": crop_code} if crop_code else {}))
                        .values_list("name", flat=True)[:40])
    user = (f"Data sezonu (dziś): {today}\nZaznaczone pole: "
            f"{(selected_field.name + ' (id ' + str(selected_field.id) + ')') if selected_field else 'brak'}\n"
            f"Pola: {[{'id': f['id'], 'nazwa': f['name'], 'uprawa': f['crop']} for f in fields]}\n"
            f"Zagrożenia uprawy: {threat_names}\nWiadomość rolnika: {question}")
    out, res = complete_json(llm, [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user}],
                             DraftOut, max_tokens=300)
    meta = {"llm_calls": [log_usage(res, kind="obserwacja", extra={"conversation_id": conv_id})], "extracted": out.model_dump(mode="json")}

    # code decides: field, date, threat
    valid_ids = {f["id"] for f in fields}
    field_id = out.field_id if out.field_id in valid_ids else None
    field_id = route.field_id or field_id or (selected_field.id if selected_field else None)
    date = (_relative_date(question, today) or (out.date if out.date and out.date <= today else None)
            or (dt.date.fromisoformat(prev["date"]) if prev and prev.get("date") else None) or today)
    threat = None
    if field_id:
        fcrop = next(f["crop_code"] for f in fields if f["id"] == field_id)
        t = domain.threat_by_code_or_name(out.threat, fcrop) if out.threat else None
        # the router's match is deterministic (aliases: "gąsienice w łodygach" -> omacnica); the model's guess
        # wins only if it is one of those ("stonka" for "gąsienice w łodygach" would raise the wrong risk)
        routed = {x.code: x for x in Threat.objects.filter(code__in=route.threats, crop_id=fcrop)}
        if routed and (t is None or t.code not in routed):
            t = next(routed[c] for c in route.threats if c in routed)
        threat = t
    kind, facts = detect_kind(question, today)
    category = out.category or ("choroba" if threat and threat.category != "pest" else "szkodnik" if threat else None)
    if kind == "field_fact":
        category = "inne"
    elif kind == "event":
        category = "uszkodzenie"
    elif kind in ("absence", "treatment", "neighbour") and category is None:
        category = "choroba"  # the engine: absence -> all threats, treatment -> all fungal, neighbour -> disease group
    elif kind == "symptoms" and category in ("chwasty", "inne"):
        kind = None  # weeds / other notes: stored, but not a disease or pest report for the engine (it skips them)

    missing = []
    if field_id is None:
        missing.append("pole")
    if category is None:
        missing.append("kategoria")
    if missing:
        names = ", ".join(f["name"] for f in fields)
        asks = []
        if "pole" in missing:
            asks.append(f"którego pola dotyczy (np. {names}) — możesz też zaznaczyć je na mapie")
        if "kategoria" in missing:
            asks.append("czy to choroba, szkodnik, chwasty czy uszkodzenie")
        return FlowResult("Chętnie zapiszę obserwację. Napisz proszę " + " oraz ".join(asks) + ".", meta=meta)

    fname = next(f["name"] for f in fields if f["id"] == field_id)
    draft = {"draft_id": uuid.uuid4().hex[:12], "field_id": field_id, "field": fname, "date": date.isoformat(),
             "category": category, "threat_code": threat.code if threat else None,
             "threat": threat.name if threat else None, "severity": out.severity if kind == "symptoms" else None,
             "note": re.sub(r"[<>]", "", (out.note or question)).strip()[:500], "kind": kind, "facts": facts}
    state.set_draft(draft)
    text = draft_text(draft) + "\n\nZapisać tę obserwację? (tak / nie)"
    sources = []
    if threat:  # one guide passage about symptoms, so the farmer can compare with what they see
        from .context import guide_sources
        crop = domain.crop_pl(next(f["crop_code"] for f in fields if f["id"] == field_id))
        sources, _ = guide_sources([(f"{threat.name} objawy", crop, 2, threat.name)], budget=350, max_n=1)
        if sources:
            snippet = symptom_snippet(sources[0]["text"], threat.name)
            text += f"\n\nObjawy według metodyki, do porównania z tym, co widzisz: „{snippet}” [{sources[0]['chunk_id']}]"
    return FlowResult(text, sources=sources, focus_field_id=None if route.field_source == "selected" else field_id,
                      pending_action={"type": "confirm_observation", "draft": draft}, meta=meta)


def confirmation(route: Route, question: str, state, conv_id=None) -> FlowResult:
    draft = state.draft
    t = domain.fold(question)
    if draft is None:
        return FlowResult("Nie mam żadnej obserwacji do zapisania.")
    if t.split(" ")[0] in {"nie", "anuluj", "rezygnuje", "odrzuc", "stop"} or t in {"nie trzeba", "nie zapisuj"}:
        state.set_draft(None)
        if draft.get("saved_observation_id"):
            return FlowResult(f"Ta obserwacja jest już zapisana (nr {draft['saved_observation_id']}), więc nie mogę "
                              "jej anulować. Jeśli coś się nie zgadza, opisz to jeszcze raz, a zapiszę poprawioną.")
        return FlowResult("Dobrze, nie zapisuję tej obserwacji.")
    key = hashlib.sha256(f"{conv_id}:{draft['draft_id']}".encode()).hexdigest()[:64]
    try:
        res = call("record_observation", field_id=draft["field_id"], date=draft["date"], category=draft["category"],
                   threat=draft.get("threat_code"), severity=draft.get("severity"), note=draft["note"],
                   idempotency_key=key, kind=draft.get("kind"), facts=draft.get("facts") or None)
    except ToolError as e:
        return FlowResult(f"Nie udało się zapisać obserwacji: {e}")
    draft["saved_observation_id"] = res["observation_id"]
    state.set_draft(draft)  # kept, so a repeated "tak" is answered without a duplicate
    if not res["created"]:
        return FlowResult(f"Ta obserwacja jest już zapisana (nr {res['observation_id']}).",
                          meta={"observation_id": res["observation_id"]})
    r = res["reassessment"]
    text = f"Zapisałem obserwację nr {res['observation_id']} dla pola {draft['field']} ({draft['date']})."
    updated = []
    if r["status"] == "ok":
        updated = r.get("recomputed_field_ids") or [draft["field_id"]]
        ch = r.get("changed", {})
        if ch:
            def _change(c, v):
                b, a = v["before"] or {}, v["after"]
                if b.get("level") == a["level"]:  # same level: show the score change
                    return f"{a.get('threat', c)}: {a['level']} ({b.get('score', 0):.2f} → {a['score']:.2f})".replace(".", ",")
                return f"{a.get('threat', c)}: {b.get('level', '—')} → {a['level']}"
            parts = [_change(c, v) for c, v in list(ch.items())[:3]]
            text += " Silnik przeliczył ryzyko pola: " + "; ".join(parts) + "."
        else:
            text += " Silnik przeliczył ryzyko pola — poziomy zagrożeń na dziś się nie zmieniły."
        others = [i for i in updated if i != draft["field_id"]]
        if others:
            from core.models import Field
            text += (" Przeliczył też sąsiednie pola tej samej uprawy: "
                     + ", ".join(Field.objects.filter(pk__in=others).values_list("name", flat=True)) + ".")
    elif r["status"] == "unavailable":
        text += " Silnik decyzyjny nie jest jeszcze podłączony, więc ryzyko pola nie zostało przeliczone."
    else:
        text += " Ponowna ocena ryzyka się nie udała; obserwacja jest zapisana, spróbuj przeliczyć później."
    return FlowResult(text, updated_field_ids=updated,
                      focus_field_id=None if route.field_source == "selected" else draft["field_id"],
                      meta={"observation_id": res["observation_id"], "reassessment_status": r["status"]})
