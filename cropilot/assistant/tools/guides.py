"""Guide search tools (over assistant.rag). Pesticide-dose passages are always excluded."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .registry import ToolError, register

TEXT_TOKEN_BUDGET = 1800  # total passage text per call, counted with the embedding model's tokenizer


def _ntok(text: str) -> int:
    from assistant.rag.chunker import ntok
    return ntok(text)


def passage_dict(p, text: str | None = None) -> dict:
    return {
        "chunk_id": p.chunk_id,
        "citation_text": p.citation,
        "section": p.section,
        "pages": p.printed_pages or (f"PDF {p.pdf_pages[0]}" if p.pdf_pages else ""),
        "kind": p.kind,
        "text": text if text is not None else p.text,
        "citation": p.to_citation(),
    }


def fit_passages(passages, budget: int = TEXT_TOKEN_BUDGET) -> list[dict]:
    """Keep passages in rank order until the token budget is used; trim the last one."""
    out, used = [], 0
    for p in passages:
        n = _ntok(p.text)
        if used + n <= budget:
            out.append(passage_dict(p))
            used += n
            continue
        left = budget - used
        if left > 120:  # worth keeping a trimmed piece
            words = p.text.split()
            keep = int(len(words) * left / max(n, 1))
            out.append(passage_dict(p, " ".join(words[:keep]) + " …"))
        break
    return out


def _unavailable(e: Exception) -> ToolError:
    return ToolError("Wyszukiwarka metodyk jest niedostępna (baza wektorowa nie odpowiada). "
                     "Uruchom: docker compose up -d qdrant")


class SearchGuidesIn(BaseModel):
    query: str = Field(description="Pytanie lub fraza po polsku, np. 'septorioza paskowana warunki rozwoju'.")
    crop: Literal["pszenica", "kukurydza", "zboza"] | None = Field(None, description="Uprawa (filtr).")
    audience: Literal["doradcy", "producenci"] | None = None
    k: int = Field(4, ge=1, le=8, description="Ile fragmentów zwrócić.")


@register("search_guides", """
Wyszukuje fragmenty oficjalnych metodyk integrowanej ochrony roślin (IOR) i zestawienia warunków
ryzyka. Używaj do pytań o objawy, warunki rozwoju chorób/szkodników, progi szkodliwości, terminy
lustracji, metody niechemiczne, agrotechnikę. Fragmenty z dawkami środków ochrony roślin są zawsze
pominięte. Zwraca listę {chunk_id, citation_text, section, pages, text}; cytuj po chunk_id.
Przykład: search_guides(query="próg szkodliwości mszyc", crop="pszenica").
""", SearchGuidesIn)
def search_guides(query: str, crop=None, audience=None, k: int = 4) -> dict:
    from assistant.rag.search import search
    from assistant.rag.store import QdrantUnavailable
    try:
        res = search(query, crop=crop, audience=audience, k=k, include_pesticide_doses=False)
    except QdrantUnavailable as e:
        raise _unavailable(e) from None
    return {"query": query, "passages": fit_passages(res)}


class GetPassageIn(BaseModel):
    chunk_id: str = Field(description="Id fragmentu, np. 'pszenica_doradcy:5.1:0007'.")
    with_neighbors: int = Field(0, ge=0, le=2, description="Ile sąsiednich fragmentów dołączyć z każdej strony.")


@register("get_passage", """
Zwraca pełny fragment metodyki po chunk_id (z search_guides), opcjonalnie z sąsiednimi fragmentami,
gdy potrzebny jest szerszy kontekst. Fragmentów z dawkami środków nie zwraca.
""", GetPassageIn)
def get_passage(chunk_id: str, with_neighbors: int = 0) -> dict:
    from assistant.rag.search import _store, get_passage as _get
    from assistant.rag.store import QdrantUnavailable
    try:
        ps = _get(chunk_id, with_neighbors=with_neighbors)
        flagged = {c for c, p in _store().get_by_chunk_id([p.chunk_id for p in ps]).items()
                   if p.get("has_pesticide_doses")}
    except QdrantUnavailable as e:
        raise _unavailable(e) from None
    if not ps:
        raise ToolError(f"Nie ma fragmentu o id „{chunk_id}”.")
    return {"passages": [passage_dict(p) for p in ps if p.chunk_id not in flagged],
            "omitted_dose_passages": len([p for p in ps if p.chunk_id in flagged])}


class RiskConditionsIn(BaseModel):
    crop: Literal["pszenica", "kukurydza", "burak", "slonecznik", "ziemniak"]
    threat: str | None = Field(None, description="Nazwa zagrożenia (dowolna forma, np. 'septoriozy paskowanej').")


@register("get_risk_conditions", """
Warunki sprzyjające chorobie/szkodnikowi z zestawienia ryzyk (ryzyka_zebrane.xlsx): temperatura,
wilgotność, inne czynniki. Nazwa zagrożenia może być odmieniona lub z literówką. Bez `threat`
zwraca wszystkie wiersze dla uprawy. Cytuj jako ryzyka_zebrane (arkusz, wiersz).
""", RiskConditionsIn)
def get_risk_conditions(crop: str, threat: str | None = None) -> dict:
    from assistant.rag.search import get_risk_conditions as _get
    rows = _get(crop, threat)
    keep = ("threat", "threat_type", "temperature_raw", "humidity_raw", "other_factors", "temp_min_c",
            "temp_max_c", "temp_opt_min_c", "temp_opt_max_c", "sheet", "row", "match_score")
    return {"crop": crop, "threat": threat,
            "rows": [{k: r.get(k) for k in keep} | {"chunk_id": f"ryzyka_zebrane:{r['crop']}.r{r['row']:03d}"}
                     for r in rows[:10 if threat is None else 3]]}
