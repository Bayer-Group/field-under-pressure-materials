"""BM25 over `embed_text` with Polish tokenisation.

Stemming variants (config.BM25_STEMMER, both are built and stored in bm25.pkl):
  "stempel" - pystempel (polimorf tables)
  "trunc6"  - truncate tokens longer than 6 chars to 6 chars (cheap inflection heuristic)
"""
from __future__ import annotations

import contextlib
import io
import pickle
import re
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from . import config
from .store import matches

TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)?(?:\s?[-–−]\s?\d+(?:[.,]\d+)?)?|[^\W\d_]+", re.U)
STOP = set("""a aby ale albo ani aż bez bo by być był była było były co czy dla do gdy gdzie go i ich
ie im in jak jako jakie je jego jej jest jeszcze jeśli już każdy kiedy która które którego której który
których ku lub ma mają mi może można na nad nie niż nich np o od oraz po pod przez przy się są ta tak także
te tego tej ten to tu tych tylko tym w we więc z za ze że które oraz wg tzw m.in itp itd""".split())
STEMMERS = ("stempel", "trunc6")


@lru_cache(maxsize=1)
def _stempel():
    from pystempel import Stemmer
    with contextlib.redirect_stderr(io.StringIO()):
        return Stemmer.polimorf()


@lru_cache(maxsize=200_000)
def _stem(word: str, how: str) -> str:
    if how == "trunc6":
        return word[:6]
    s = _stempel()(word)
    return s or word


def tokenize(text: str, how: str = config.BM25_STEMMER) -> list[str]:
    out = []
    for t in TOKEN_RE.findall(text.lower()):
        if t[0].isdigit():
            out.append(re.sub(r"\s?[-–−]\s?", "-", t))
            continue
        if t in STOP or len(t) < 2:
            continue
        out.append(_stem(t, how))
    return out


def _meta(c: dict) -> dict:
    return {"crop": c["crop"], "audience": c["audience"], "doc_id": c["doc_id"], "kind": c["kind"],
            "has_pesticide_doses": c["flags"]["has_pesticide_doses"]}


def build(chunks: list[dict]) -> dict:
    data = {"chunk_ids": [c["chunk_id"] for c in chunks], "meta": [_meta(c) for c in chunks], "index": {}}
    for how in STEMMERS:
        data["index"][how] = BM25Okapi([tokenize(c["embed_text"], how) for c in chunks])
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.BM25_PKL, "wb") as f:
        pickle.dump(data, f)
    return data


@lru_cache(maxsize=1)
def load() -> dict:
    with open(config.BM25_PKL, "rb") as f:
        return pickle.load(f)


def query(q: str, filters: dict, limit: int = config.CANDIDATES,
          how: str | None = None) -> list[tuple[str, float]]:
    how = how or config.BM25_STEMMER
    data = load()
    scores = data["index"][how].get_scores(tokenize(q, how))
    mask = np.array([matches(m, filters) for m in data["meta"]], dtype=bool)
    scores = np.where(mask, scores, -np.inf)
    top = np.argsort(-scores)[:limit]
    return [(data["chunk_ids"][i], float(scores[i])) for i in top if np.isfinite(scores[i]) and scores[i] > 0]
