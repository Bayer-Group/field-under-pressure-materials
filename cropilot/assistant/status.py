"""
Is the chat usable? Read by GET /api/health/ (the frontend greys the chat out) and POST /api/chat/ (503).

    assistant_status() -> {"available", "llm", "rag", "reason"}

No call to the LLM: only the configuration (a provider with a key and a model, or ASSISTANT_LLM=fake). The RAG
check (BM25 file + a non-empty Qdrant collection, 1 s timeout) is cached for a minute.
"""

from __future__ import annotations

import os
import time

NO_LLM = "Asystent jest wyłączony: brak kluczy do modelu językowego. Mapa, ryzyka i wyjaśnienia działają normalnie."
NO_RAG = "Brak indeksu metodyk: asystent odpowiada bez cytatów z metodyk."
RAG_TTL_S = 60

_rag_cache: dict = {"at": 0.0, "ok": None}


def llm_ready() -> bool:
    if os.getenv("ASSISTANT_LLM", "").lower() == "fake":
        return True
    from assistant.orchestrator.llm import provider_configs

    return any(c["configured"] and c["model"] for c in provider_configs())


def rag_ready() -> bool:
    now = time.monotonic()
    if _rag_cache["ok"] is not None and now - _rag_cache["at"] < RAG_TTL_S:
        return _rag_cache["ok"]
    ok = False
    try:
        from assistant.rag import config

        if config.BM25_PKL.exists():
            from qdrant_client import QdrantClient

            ok = QdrantClient(url=config.QDRANT_URL, timeout=1).count(config.QDRANT_COLLECTION, exact=False).count > 0
    except Exception:  # Qdrant down, collection missing, client not installed
        ok = False
    _rag_cache.update(at=now, ok=ok)
    return ok


def assistant_status() -> dict:
    llm = llm_ready()
    rag = rag_ready()
    reason = NO_LLM if not llm else (NO_RAG if not rag else None)
    return {"available": llm, "llm": llm, "rag": rag, "reason": reason}
