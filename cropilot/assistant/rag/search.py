"""Public API of the RAG module (imported later by the MCP server).

    search(query, crop=None, audience=None, k=6, include_pesticide_doses=False, mode="hybrid")
    get_passage(chunk_id, with_neighbors=0)
    get_page(doc_id, printed_page)
    get_risk_conditions(crop, threat=None)

Everything heavy (model, Qdrant client, BM25, pages) is loaded lazily, once per process.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Literal

from . import config

Mode = Literal["hybrid", "dense", "bm25"]
CROP_ALIASES = {"burak cukrowy": "burak", "słonecznik": "slonecznik", "zboża": "zboza", "żyto": "zyto",
                "jęczmień": "jeczmien", "pszenżyto": "pszenzyto"}


@dataclass
class Passage:
    chunk_id: str
    doc_id: str
    doc_title: str
    crop: str
    audience: str
    section: str
    printed_pages: str
    pdf_pages: tuple[int, int] | None
    kind: str
    text: str
    score: float
    citation: str                      # human-readable, e.g. "Metodyka … (doradcy), s. 70–71"
    document: str = ""                 # source file name in field-under-pressure-materials/metodyki/
    printed_page: int | None = None    # first printed page (what the book says)
    sheet: str | None = None           # spreadsheet rows only
    row: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_citation(self) -> dict:
        """Citation in the chat API format (docs/interfaces.md -> Chat -> Citations).

        guide PDF:   {"type": "guide", "document": "<pdf file>", "page": <PDF page, 1-based>,
                      "printed_page": <page number printed in the book or null>, "section": "..."}
        spreadsheet: {"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": "...", "row": n}
        `page` is the PDF page (so a viewer can open `file.pdf#page=N`); printed_page and
        section are extra keys for display.
        """
        if self.sheet is not None:
            return {"type": "guide", "document": self.document, "sheet": self.sheet, "row": self.row}
        return {"type": "guide", "document": self.document,
                "page": self.pdf_pages[0] if self.pdf_pages else None,
                "printed_page": self.printed_page, "section": self.section}


# ----------------------------------------------------------------------------- lazy resources
@lru_cache(maxsize=1)
def _store():
    from .store import QdrantStore
    return QdrantStore()


def _norm_crop(crop: str | None) -> str | None:
    if crop is None:
        return None
    c = crop.strip().lower()
    return CROP_ALIASES.get(c, c)


def build_filters(crop: str | None = None, audience: str | None = None,
                  include_pesticide_doses: bool = False, doc_id: str | list[str] | None = None) -> dict:
    f: dict = {"exclude_pesticide": not include_pesticide_doses}
    c = _norm_crop(crop)
    if c:
        f["crop"] = config.CROP_EXPANSION.get(c, [c])
    if audience:
        # spreadsheet rows have audience "zestawienie" and are always allowed
        f["audience"] = [audience, "zestawienie"]
    if doc_id:
        f["doc_id"] = [doc_id] if isinstance(doc_id, str) else list(doc_id)
    return f


# ----------------------------------------------------------------------------- formatting
def _pages_str(a, b) -> str:
    if a is None:
        return ""
    return f"{a}" if a == b or b is None else f"{a}–{b}"


def _citation(p: dict) -> str:
    if p["doc_id"] == config.EXCEL_DOC_ID:
        rows = p.get("row"), p.get("row_end")
        r = f"wiersz {rows[0]}" if rows[0] == rows[1] or rows[1] is None else f"wiersze {rows[0]}–{rows[1]}"
        return f"{p['doc_title']}, arkusz „{p.get('sheet')}”, {r}"
    pr = _pages_str(p.get("printed_page_start"), p.get("printed_page_end"))
    if pr:
        return f"{p['doc_title']} ({p['audience']}), s. {pr}"
    return f"{p['doc_title']} ({p['audience']}), s. PDF {_pages_str(p.get('pdf_page_start'), p.get('pdf_page_end'))}"


def _section(p: dict) -> str:
    s = " > ".join(p.get("section_path") or [])
    if p.get("subheading"):
        s += f" > {p['subheading']}"
    return s


def to_passage(p: dict, score: float) -> Passage:
    pdf = (p["pdf_page_start"], p["pdf_page_end"]) if p.get("pdf_page_start") is not None else None
    return Passage(
        chunk_id=p["chunk_id"], doc_id=p["doc_id"], doc_title=p["doc_title"], crop=p["crop"],
        audience=p["audience"], section=_section(p),
        printed_pages=_pages_str(p.get("printed_page_start"), p.get("printed_page_end")),
        pdf_pages=pdf, kind=p["kind"], text=p["text"], score=round(float(score), 5), citation=_citation(p),
        document=_document_file(p["doc_id"]), printed_page=p.get("printed_page_start"),
        sheet=p.get("sheet"), row=p.get("row"),
    )


@lru_cache(maxsize=None)
def _document_file(doc_id: str) -> str:
    if doc_id == config.EXCEL_DOC_ID:
        return config.EXCEL_FILE.name
    from .docs import REGISTRY
    return next((d.file for d in REGISTRY if d.doc_id == doc_id), "")


# ----------------------------------------------------------------------------- fusion / dedup
def rrf(rankings: list[tuple[list[str], float]], k: int = config.RRF_K) -> dict[str, float]:
    out: dict[str, float] = {}
    for ids, w in rankings:
        for rank, cid in enumerate(ids, start=1):
            out[cid] = out.get(cid, 0.0) + w / (k + rank)
    return out


def _strip_overlap(a: str, b: str) -> str:
    """Remove the prefix of b that repeats the tail of a (chunk overlap)."""
    for n in range(min(len(a), len(b), 400), 20, -1):
        if a.endswith(b[:n]):
            return b[n:].lstrip()
    return b


def _merge_neighbors(items: list[tuple[dict, float]]) -> list[tuple[dict, float]]:
    """Merge results that are adjacent chunks of the same section into one passage."""
    by_id = {p["chunk_id"]: (p, s) for p, s in items}
    used: set[str] = set()
    out = []
    for p, s in items:
        if p["chunk_id"] in used:
            continue
        group = [p]
        used.add(p["chunk_id"])
        # walk backwards and forwards through neighbours present in the results
        cur = p
        while cur.get("prev_id") in by_id and cur["prev_id"] not in used \
                and by_id[cur["prev_id"]][0]["section_id"] == p["section_id"] and p["kind"] == "text":
            cur = by_id[cur["prev_id"]][0]
            group.insert(0, cur)
            used.add(cur["chunk_id"])
        cur = p
        while cur.get("next_id") in by_id and cur["next_id"] not in used \
                and by_id[cur["next_id"]][0]["section_id"] == p["section_id"] and p["kind"] == "text":
            cur = by_id[cur["next_id"]][0]
            group.append(cur)
            used.add(cur["chunk_id"])
        if len(group) == 1:
            out.append((p, s))
            continue
        merged = dict(group[0])
        text = group[0]["text"]
        for g in group[1:]:
            text = text + "\n\n" + _strip_overlap(text, g["text"])
        merged["text"] = text
        for k in ("pdf_page", "printed_page"):
            starts = [g[f"{k}_start"] for g in group if g.get(f"{k}_start") is not None]
            ends = [g[f"{k}_end"] for g in group if g.get(f"{k}_end") is not None]
            merged[f"{k}_start"] = min(starts) if starts else None
            merged[f"{k}_end"] = max(ends) if ends else None
        merged["chunk_id"] = group[0]["chunk_id"]
        merged["merged_ids"] = [g["chunk_id"] for g in group]
        out.append((merged, max(by_id[g["chunk_id"]][1] for g in group)))
    return out


# ----------------------------------------------------------------------------- search
def search(query: str, crop: str | None = None, audience: str | None = None,
           k: int = 6, include_pesticide_doses: bool = False,
           mode: Mode = "hybrid", bm25_stemmer: str | None = None,
           merge: bool = True) -> list[Passage]:
    """Hybrid (dense + BM25, RRF) search over the guides and the risk spreadsheet.

    By default chunks flagged `has_pesticide_doses` are excluded (project rule: the
    assistant gives no product/dose advice). Chunks about legal regulations are
    down-weighted (x LEGAL_PENALTY) after fusion.
    """
    from . import bm25
    from .embed import encode_query

    f = build_filters(crop, audience, include_pesticide_doses)
    store = _store()
    payloads: dict[str, dict] = {}
    dense: list[tuple[str, float]] = []
    sparse: list[tuple[str, float]] = []
    if mode in ("hybrid", "dense"):
        for cid, score, p in store.query(encode_query(query), f, config.CANDIDATES):
            dense.append((cid, score))
            payloads[cid] = p
    if mode in ("hybrid", "bm25"):
        sparse = bm25.query(query, f, config.CANDIDATES, how=bm25_stemmer)
        missing = [c for c, _ in sparse if c not in payloads]
        payloads.update(store.get_by_chunk_id(missing))

    if mode == "hybrid":
        scores = rrf([([c for c, _ in dense], config.RRF_WEIGHT_DENSE),
                      ([c for c, _ in sparse], config.RRF_WEIGHT_BM25)])
    else:
        scores = dict(dense if mode == "dense" else sparse)
    for cid in scores:
        if payloads.get(cid, {}).get("is_legal"):
            scores[cid] *= config.LEGAL_PENALTY
    ranked = sorted(((payloads[c], s) for c, s in scores.items() if c in payloads), key=lambda x: -x[1])
    ranked = ranked[: max(2 * k, k + 4)]
    if merge:
        ranked = _merge_neighbors(ranked)
    return [to_passage(p, s) for p, s in ranked[:k]]


def get_passage(chunk_id: str, with_neighbors: int = 0) -> list[Passage]:
    """The chunk plus up to `with_neighbors` chunks before and after it (same document)."""
    store = _store()
    got = store.get_by_chunk_id([chunk_id])
    if chunk_id not in got:
        return []
    center = got[chunk_id]
    before, after = [], []
    cur = center
    for _ in range(with_neighbors):
        if not cur.get("prev_id"):
            break
        cur = store.get_by_chunk_id([cur["prev_id"]]).get(cur["prev_id"])
        if not cur:
            break
        before.insert(0, cur)
    cur = center
    for _ in range(with_neighbors):
        if not cur.get("next_id"):
            break
        cur = store.get_by_chunk_id([cur["next_id"]]).get(cur["next_id"])
        if not cur:
            break
        after.append(cur)
    return [to_passage(p, 1.0 if p is center else 0.0) for p in before + [center] + after]


@lru_cache(maxsize=1)
def _pages_index() -> dict[tuple[str, int], list[dict]]:
    idx: dict[tuple[str, int], list[dict]] = {}
    with open(config.PAGES_JSONL) as f:
        for line in f:
            p = json.loads(line)
            if p["printed_page"] is not None:
                idx.setdefault((p["doc_id"], p["printed_page"]), []).append(p)
    return idx


def get_page(doc_id: str, printed_page: int) -> str:
    """Clean text of a printed page (tables appended as Markdown). '' if unknown."""
    pages = _pages_index().get((doc_id, int(printed_page)), [])
    out = []
    for p in pages:
        parts = [p["text"]] + [t["markdown"] for t in p["tables"]]
        out.append("\n\n".join(x for x in parts if x))
    return "\n\n".join(out)


# ----------------------------------------------------------------------------- risks
@lru_cache(maxsize=1)
def _risks() -> list[dict]:
    return json.loads(config.RISK_JSON.read_text())


def _fold(s: str) -> str:
    s = s.lower().replace("ł", "l")
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"[^a-z0-9 ]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip()


def _prefix_cover(q: str, name: str) -> float:
    """% of query words that match a name word by prefix (3 letters for short words, 4 otherwise).
    Catches Polish case endings that change early letters: rdzy/rdza, brunatnej/brunatna."""
    qw = [w for w in q.split() if len(w) >= 3]
    nw = name.split()
    if not qw:
        return 0.0
    def pre(w):
        return w[:3] if len(w) <= 5 else w[:4]
    hit = sum(any(n.startswith(pre(w)) for n in nw) for w in qw)
    return 100.0 * hit / len(qw)


def _stem5(s: str, n: int = 5) -> str:
    return " ".join(w[:n] for w in s.split())


def get_risk_conditions(crop: str, threat: str | None = None, min_score: float = 70) -> list[dict]:
    """Rows of risk_conditions.json for a crop; `threat` is matched fuzzily
    (inflection / typos tolerant). Sorted by match score (field `match_score`)."""
    from rapidfuzz import fuzz

    c = _norm_crop(crop)
    rows = [r for r in _risks() if r["crop"] == c and r["kind"] == "row"]
    if not threat:
        return rows
    q = _fold(threat)
    scored = []
    for r in rows:
        name = _fold(re.sub(r"\(.*?\)", "", r["threat"]))
        # token_set handles extra words ("septorioza paskowana liści pszenicy");
        # partial_ratio on 5-char prefixes handles inflection ("septoriozy paskowanej")
        sc = max(fuzz.token_set_ratio(q, name), fuzz.token_set_ratio(_stem5(q), _stem5(name)),
                 _prefix_cover(q, name))
        if sc >= min_score:
            scored.append((sc, r))
    scored.sort(key=lambda x: -x[0])
    return [r | {"match_score": round(sc, 1)} for sc, r in scored]
