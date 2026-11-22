"""A deterministic stand-in for the LLM (manage.py chat / chat_eval without --live).

It answers from the prompt itself: cites the first chunk ids of <zrodla>, echoes the engine's
reasons from <kontekst>, and extracts a simple observation draft in JSON mode. Good enough to
exercise routing, tools, citations, guard and state without any API call.
"""
from __future__ import annotations

import json
import re

from .llm import FakeLLM


def _section(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", text, re.S)
    return m.group(1) if m else ""


def _respond(messages: list[dict], json_mode: bool) -> str:
    user = messages[-1]["content"] if messages else ""
    if json_mode:
        msg = user.split("Wiadomość rolnika:")[-1].strip()
        low = msg.lower()
        cat = ("szkodnik" if any(w in low for w in ("mszyc", "gąsienic", "larw", "owad", "chrząszcz", "omacnic"))
               else "chwasty" if "chwast" in low else "uszkodzenie" if any(w in low for w in ("grad", "wyleg", "dzik"))
               else "choroba" if any(w in low for w in ("plam", "nalot", "rdz", "pleśń", "żółkn", "zgni")) else None)
        sev = "wysokie" if any(w in low for w in ("dużo", "mnóstwo", "całe pole", "silnie")) else None
        return json.dumps({"field_id": None, "date": None, "category": cat, "threat": None, "severity": sev,
                           "note": msg[:200], "missing": [] if cat else ["kategoria"]}, ensure_ascii=False)
    if "dawk" in user.lower() and "REGENERATE" in user:
        return "Dobór środka i dawki według aktualnej etykiety, skonsultuj z doradcą."
    ids = re.findall(r"^\[([a-z_]+:[^\]\s]+)\]", _section(user, "zrodla"), re.M)
    reasons = re.findall(r"powody \(silnik\): (.+)", _section(user, "kontekst"))
    summary = re.search(r"Podsumowanie wykresu \(liczby policzone przez aplikację\): (.+)", user)
    if summary:
        return "[FakeLLM] Komentarz do wykresu na podstawie podsumowania: " + summary.group(1)[:160] + "…"
    parts = ["[FakeLLM] Odpowiedź testowa bez modelu językowego."]
    if reasons:
        parts.append(f"Według silnika: {reasons[0]}")
    for cid in ids[:2]:
        parts.append(f"Metodyka opisuje to zagadnienie [{cid}].")
    if not ids:
        parts.append("Brak fragmentów metodyk w kontekście.")
    return " ".join(parts)


def demo_llm() -> FakeLLM:
    return FakeLLM(responses=_respond, name="fake", model="fake-demo")
