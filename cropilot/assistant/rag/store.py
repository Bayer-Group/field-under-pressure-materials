"""Vector store: thin abstraction + Qdrant implementation (server in Docker).

Filters are a small backend-neutral dict shared with BM25:
  {"crop": [..], "audience": [..], "doc_id": [..], "kind": [..], "exclude_pesticide": bool}
"""
from __future__ import annotations

import uuid
from typing import Protocol

import numpy as np

from . import config

NAMESPACE = uuid.UUID("6f1c2a52-4f7e-4a0e-9c55-6b2f1f0d2a11")
KEYWORD_FIELDS = ["crop", "audience", "doc_id", "kind", "chunk_id", "section_id"]
BOOL_FIELDS = ["has_pesticide_doses", "is_legal", "has_fertilizer_doses"]


class QdrantUnavailable(RuntimeError):
    pass


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, chunk_id))


def payload_of(chunk: dict) -> dict:
    p = {k: v for k, v in chunk.items() if k not in ("embed_text",)}
    p.update(chunk.get("flags", {}))  # flat bool fields for indexed filtering
    return p


class VectorStore(Protocol):
    def upsert(self, chunks: list[dict], vectors: np.ndarray) -> None: ...
    def query(self, vector: np.ndarray, filters: dict, limit: int) -> list[tuple[str, float, dict]]: ...
    def get_by_chunk_id(self, chunk_ids: list[str]) -> dict[str, dict]: ...


class QdrantStore:
    def __init__(self, url: str = config.QDRANT_URL, collection: str = config.QDRANT_COLLECTION):
        from qdrant_client import QdrantClient
        self.url, self.collection = url, collection
        self.client = QdrantClient(url=url, timeout=30)
        self.health()

    # -- admin
    def health(self) -> None:
        try:
            self.client.get_collections()
        except Exception as e:  # connection refused, timeout, ...
            raise QdrantUnavailable(
                f"Qdrant nie działa na {self.url} ({type(e).__name__}). Uruchom w katalogu repo: "
                f"docker compose up -d qdrant"
            ) from None

    def ensure(self, dim: int, rebuild: bool = False) -> None:
        from qdrant_client import models as m
        exists = self.client.collection_exists(self.collection)
        if exists and rebuild:
            self.client.delete_collection(self.collection)
            exists = False
        if not exists:
            self.client.create_collection(
                self.collection, vectors_config=m.VectorParams(size=dim, distance=m.Distance.COSINE))
            for f in KEYWORD_FIELDS:
                self.client.create_payload_index(self.collection, f, field_schema=m.PayloadSchemaType.KEYWORD)
            for f in BOOL_FIELDS:
                self.client.create_payload_index(self.collection, f, field_schema=m.PayloadSchemaType.BOOL)

    def delete_docs(self, doc_ids: list[str]) -> None:
        from qdrant_client import models as m
        if self.client.collection_exists(self.collection):
            self.client.delete(self.collection, points_selector=m.FilterSelector(
                filter=m.Filter(must=[m.FieldCondition(key="doc_id", match=m.MatchAny(any=doc_ids))])), wait=True)

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    # -- data
    def upsert(self, chunks: list[dict], vectors: np.ndarray) -> None:
        from qdrant_client import models as m
        for i in range(0, len(chunks), config.UPSERT_BATCH):
            pts = [m.PointStruct(id=point_id(c["chunk_id"]), vector=v.tolist(), payload=payload_of(c))
                   for c, v in zip(chunks[i:i + config.UPSERT_BATCH], vectors[i:i + config.UPSERT_BATCH])]
            self.client.upsert(self.collection, points=pts, wait=True)

    @staticmethod
    def _filter(f: dict):
        from qdrant_client import models as m
        must, must_not = [], []
        for key in ("crop", "audience", "doc_id", "kind"):
            if f.get(key):
                must.append(m.FieldCondition(key=key, match=m.MatchAny(any=list(f[key]))))
        if f.get("exclude_pesticide"):
            must_not.append(m.FieldCondition(key="has_pesticide_doses", match=m.MatchValue(value=True)))
        return m.Filter(must=must or None, must_not=must_not or None)

    def query(self, vector: np.ndarray, filters: dict, limit: int = config.CANDIDATES):
        res = self.client.query_points(self.collection, query=vector.tolist(), query_filter=self._filter(filters),
                                       limit=limit, with_payload=True)
        return [(p.payload["chunk_id"], float(p.score), p.payload) for p in res.points]

    def get_by_chunk_id(self, chunk_ids: list[str]) -> dict[str, dict]:
        if not chunk_ids:
            return {}
        res = self.client.retrieve(self.collection, ids=[point_id(c) for c in chunk_ids], with_payload=True)
        return {p.payload["chunk_id"]: p.payload for p in res}


def matches(meta: dict, f: dict) -> bool:
    """Same filter semantics in Python (used by BM25)."""
    for key in ("crop", "audience", "doc_id", "kind"):
        if f.get(key) and meta.get(key) not in f[key]:
            return False
    if f.get("exclude_pesticide") and meta.get("has_pesticide_doses"):
        return False
    return True
