"""Embeddings with sdadas/mmlw-retrieval-roberta-base (+ on-disk cache).

Queries MUST be prefixed with "zapytanie: "; passages are encoded without a prefix
(model card). Cache key = sha1(model name + embed_text).
"""
from __future__ import annotations

import hashlib
import logging
import time
from functools import lru_cache

import numpy as np

from . import config

log = logging.getLogger(__name__)


def _device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer
    dev = _device()
    t = time.time()
    model = SentenceTransformer(config.EMBED_MODEL, device=dev)
    model.max_seq_length = config.EMBED_MAX_SEQ
    log.info("model %s loaded on %s in %.1fs", config.EMBED_MODEL, dev, time.time() - t)
    return model


def dim() -> int:
    m = get_model()
    return m.get_embedding_dimension() if hasattr(m, "get_embedding_dimension") \
        else m.get_sentence_embedding_dimension()


def encode_queries(queries: list[str]) -> np.ndarray:
    q = [config.QUERY_PREFIX + x for x in queries]
    return get_model().encode(q, normalize_embeddings=True, convert_to_numpy=True)


def encode_query(query: str) -> np.ndarray:
    return encode_queries([query])[0]


def _key(text: str) -> str:
    return hashlib.sha1((config.EMBED_MODEL + "\x00" + text).encode()).hexdigest()


def _load_cache() -> dict[str, np.ndarray]:
    if not config.EMB_CACHE.exists():
        return {}
    z = np.load(config.EMB_CACHE)
    return dict(zip(z["keys"].tolist(), z["vecs"]))


def _save_cache(cache: dict[str, np.ndarray]) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    keys = np.array(list(cache.keys()))
    vecs = np.stack(list(cache.values())).astype(np.float32) if cache else np.zeros((0, 768), np.float32)
    tmp = config.EMB_CACHE.with_suffix(".tmp.npz")
    np.savez(tmp, keys=keys, vecs=vecs)
    tmp.replace(config.EMB_CACHE)


def encode_passages(texts: list[str], verbose: bool = True) -> np.ndarray:
    """Encode passages (no prefix), reusing cached vectors."""
    cache = _load_cache()
    keys = [_key(t) for t in texts]
    missing = [i for i, k in enumerate(keys) if k not in cache]
    if missing:
        t = time.time()
        model = get_model()
        vecs = model.encode([texts[i] for i in missing], normalize_embeddings=True,
                            batch_size=config.EMBED_BATCH, convert_to_numpy=True,
                            show_progress_bar=verbose)
        for i, v in zip(missing, vecs):
            cache[keys[i]] = v.astype(np.float32)
        _save_cache(cache)
        if verbose:
            dt = time.time() - t
            print(f"[embed] encoded {len(missing)} new passages on {model.device} in {dt:.1f}s "
                  f"({len(missing) / max(dt, 1e-6):.1f}/s); cached {len(texts) - len(missing)}")
    elif verbose:
        print(f"[embed] all {len(texts)} passages served from cache")
    return np.stack([cache[k] for k in keys])
