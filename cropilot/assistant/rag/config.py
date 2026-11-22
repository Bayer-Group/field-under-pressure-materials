"""Central configuration for the RAG module.

Independent of Django (the MCP server / CLI import it directly), but it reads the same
repo-root `.env` and uses the same materials folder as `settings.MATERIALS_DIR`.
Environment variables override the defaults (see .env.example, "Assistant" section).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ASSISTANT_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = ASSISTANT_DIR.parent

load_dotenv(REPO_DIR / ".env", override=False)  # real env vars win over .env


def _path(env: str, default: Path) -> Path:
    """Env path; relative values are resolved against the repo root (like DATA_DIR in settings)."""
    value = os.getenv(env)
    return (REPO_DIR / value).resolve() if value else default


# Organiser materials (git submodule) = settings.MATERIALS_DIR / "metodyki"
MATERIALS_DIR = REPO_DIR / "field-under-pressure-materials"
METODYKI_DIR = _path("METODYKI_DIR", MATERIALS_DIR / "metodyki")
# Generated RAG artefacts (pages, chunks, BM25, embedding cache). Gitignored.
DATA_DIR = _path("RAG_DATA_DIR", ASSISTANT_DIR / "data")
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "index"

DOCS_JSON = PROCESSED_DIR / "docs.json"
PAGES_JSONL = PROCESSED_DIR / "pages.jsonl"
SECTIONS_JSON = PROCESSED_DIR / "sections.json"
CHUNKS_JSONL = PROCESSED_DIR / "chunks.jsonl"
RISK_JSON = PROCESSED_DIR / "risk_conditions.json"
BM25_PKL = INDEX_DIR / "bm25.pkl"
EMB_CACHE = INDEX_DIR / "emb_cache.npz"

EXCEL_FILE = METODYKI_DIR / "ryzyka_zebrane.xlsx"
EXCEL_DOC_ID = "ryzyka_zebrane"
EXCEL_TITLE = "Zestawienie warunków ryzyka chorób i szkodników (ryzyka_zebrane.xlsx)"

# --- PDF parsing ---
HEADER_FOOTER_FRAC = 0.07       # top/bottom band treated as running head/foot
PAGE_NUM_FRAC = 0.12            # lone numbers in this band = printed page number
HEADER_REPEAT_FRAC = 0.30       # line must repeat on >= 30% of pages
MIN_WORDS_PAGE = 30
TABLE_MIN_RULES = 8             # prefilter: >= N horizontal and vertical rules
TABLE_MAX_EMPTY = 0.60

# --- Headings ---
HEADING_SIZE_RATIO = 1.15       # fallback detector (no TOC)
HEADING_MAX_CHARS = 120

# --- Chunking ---
CHUNK_TARGET_MIN_WORDS = 180
CHUNK_TARGET_MAX_WORDS = 280
CHUNK_MAX_TOKENS = 450
OVERLAP_MAX_WORDS = 50
SMALL_SECTION_WORDS = 60
TABLE_MAX_TOKENS = 420

# --- Embeddings ---
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "sdadas/mmlw-retrieval-roberta-base")
QUERY_PREFIX = "zapytanie: "
EMBED_BATCH = 32
EMBED_MAX_SEQ = 512

# --- Qdrant ---
QDRANT_URL = os.getenv("QDRANT_URL") or f"http://{os.getenv('QDRANT_HOST', 'localhost')}:{os.getenv('QDRANT_PORT', '6333')}"
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "guides_mmlw_v1")
UPSERT_BATCH = 192

# --- BM25 ---
BM25_STEMMER = os.getenv("RAG_BM25_STEMMER", "stempel")   # "stempel" | "trunc6"

# --- Search / fusion ---
CANDIDATES = 30
RRF_K = 60
RRF_WEIGHT_DENSE = 1.0
RRF_WEIGHT_BM25 = 1.0
LEGAL_PENALTY = 0.5
CROP_EXPANSION = {
    "farm": ["pszenica", "kukurydza", "zboza"],   # the demo farm's crops (no crop named in the question)
    "pszenica": ["pszenica", "zboza"],
    "zboza": ["zboza", "pszenica"],
}
