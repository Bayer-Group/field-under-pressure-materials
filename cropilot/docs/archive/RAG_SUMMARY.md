# AI assistant: RAG module, summary of work so far

State as of 21 Nov 2026, branch `feat/chat-assistant`. The work is in commit `a704ecb` ("feat: implement basic RAG for methodologies") and merge commit `a09fee5` ("Merge branch 'main' into feat/chat-assistant"). One later fix is not committed yet: the venv instructions in `README.md` and `README_RAG.md`.

Usage details are in [README_RAG.md](../../assistant/README_RAG.md). This document records **what was built, how it fits into the app, and which decisions were taken and why**.

---

## 1. Scope

Built: the **retrieval layer** of the AI assistant. It parses the official crop-protection guides (PDF) and the risk spreadsheet (xlsx), chunks them, embeds them, and searches them with hybrid search (Qdrant vectors + BM25 with RRF). It exposes a clean Python API, CLI and Django management commands, evaluation, and tests.

Not built yet:
- `assistant/answer.py`, the `answer()` function the chat endpoint calls;
- LLM calls;
- the MCP server and its tools (read-only SQL, recording observations);
- any frontend.

The platform's chat endpoint still returns its placeholder answer.

---

## 2. Architecture

### Place in the system

```
docker-compose.yml (one file, repo root)
 ├─ db      Postgres 16 + pgvector        ← platform data (core), chat tables (assistant)
 └─ qdrant  Qdrant 1.20.2 (127.0.0.1:6333) ← RAG vectors (collection guides_mmlw_v1)

Django project (fieldpressure/)
 └─ assistant/ (Django app, owner: Ola)
     ├─ models.py, admin.py, migrations/   chat tables Conversation / Message (from the platform template)
     ├─ rag/                                RAG module, independent of Django
     ├─ management/commands/                rag_ingest, rag_search
     ├─ eval/                               questions.yaml, run_eval.py
     ├─ test_rag.py                         RAG tests (Django test runner)
     └─ data/                               generated index files (gitignored)

field-under-pressure-materials/metodyki/   (git submodule) 15 guide PDFs + ryzyka_zebrane.xlsx
```

- `assistant.rag` **does not import Django**. The future MCP server, the CLI and `answer()` can all import it directly.
- It reads the same repo-root `.env` (python-dotenv) and the same materials folder as `settings.MATERIALS_DIR`.

### Pipeline (`python manage.py rag_ingest`)

```
PDF ──pdf_parse──▶ pages.jsonl ──toc──▶ sections.json ──chunker(+flags)──▶ chunks.jsonl ─┐
xlsx ─excel_parse──────────────▶ risk_conditions.json + chunks ──────────────────────────┤
                                                                                         ▼
                           embed (mmlw, cache) ──▶ Qdrant (vectors + payload)   bm25 ──▶ bm25.pkl
```

| module | role |
|---|---|
| `config.py` | paths, `.env`, model, chunk sizes, fusion weights, Qdrant URL (`QDRANT_HOST`/`QDRANT_PORT` or `QDRANT_URL`) |
| `docs.py` | registry of the 15 PDFs (doc_id, file, crop, audience, core flag) → `docs.json`; title taken from page 1, or from the registry (3 PDFs) |
| `textfix.py` | whitespace / control characters / private-use bullets, cp1250→cp1252 mojibake repair |
| `pdf_parse.py` | PyMuPDF → `pages.jsonl`: running heads and page numbers removed, `printed_page` read from the page or inferred from the offset, hyphenation joined, paragraphs, tables, skipped pages with a reason |
| `toc.py` | table of contents → section tree (`sections.json`), each entry matched to a heading block on a PDF page; fallback detects headings from fonts |
| `chunker.py` | sections → `chunks.jsonl` (token limit, overlap, small-section merge, table chunks, sub-headings) |
| `flags.py` | `has_pesticide_doses`, `has_fertilizer_doses`, `is_legal` |
| `excel_parse.py` | messy sheets → `risk_conditions.json` (rows + notes, parsed temperatures) + chunks |
| `embed.py` | `sdadas/mmlw-retrieval-roberta-base`, `zapytanie: ` prefix for queries only, sha1 cache `emb_cache.npz` |
| `store.py` | `VectorStore` protocol + `QdrantStore` (cosine, 768, payload indexes, uuid5 ids, health check) |
| `bm25.py` | Polish tokenisation, stop words, two stemmers (`stempel`, `trunc6`), both stored in `bm25.pkl` |
| `search.py` | public API: `search`, `get_passage`, `get_page`, `get_risk_conditions`; `Passage.to_citation()` |
| `ingest.py`, `cli.py` | command-line entry points (also exposed as `manage.py rag_ingest` / `rag_search`) |

### Public API (`assistant/rag/search.py`)

```python
search(query, crop=None, audience=None, k=6, include_pesticide_doses=False,
       mode="hybrid" | "dense" | "bm25") -> list[Passage]
get_passage(chunk_id, with_neighbors=0) -> list[Passage]
get_page(doc_id, printed_page) -> str
get_risk_conditions(crop, threat=None) -> list[dict]
Passage.to_citation() -> dict   # chat API citation format
```

- **Hybrid search**: dense top 30 + BM25 top 30, with the same filters, fused by RRF `1/(60+rank)` (weights in `config.py`).
- **Filters**:
  - `crop="pszenica"` also searches `zboza` (the GIORiN guide covers all cereals).
  - Chunks with `has_pesticide_doses` are **excluded by default** (project rule: no product or dose advice).
  - `is_legal` chunks have their score multiplied by 0.5.
  - `audience` always lets spreadsheet rows through.
- **Merging**: adjacent chunks of the same section are merged into one `Passage` (overlap removed, page ranges summed).
- **`get_risk_conditions`**: fuzzy match tolerant of inflection and typos (rapidfuzz on folded text plus 5-character prefixes).
- **Loading**: the model, the Qdrant client, BM25, pages and risks load lazily, once per process.
- **Qdrant down**: raises `QdrantUnavailable` with the message "Qdrant nie działa na … uruchom: docker compose up -d qdrant".

**Citation format (proposed to the team, not yet confirmed)**

PDF:
```json
{"type": "guide", "document": "metodyka_-_PSZENICA_-_www.pdf", "page": 79, "printed_page": 77, "section": "5. … > 5.1. …"}
```
- `page` is the PDF page, so the frontend can open `#page=79`.
- `printed_page` is the page number printed in the book.
- `printed_page` and `section` are extra keys on top of the format in `docs/interfaces.md`.

Spreadsheet:
```json
{"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": "pszenica", "row": 19}
```

### Chunk schema (`chunks.jsonl`, also the Qdrant payload minus `embed_text`)

```text
chunk_id ("pszenica_doradcy:5.1:0007", deterministic)
doc_id, doc_title, crop, audience
section_path, section_id, subheading
pdf_page_start/end, printed_page_start/end
kind (text | table | excel_row | excel_note)
text, embed_text ("{title} | {section path > subheading} | uprawa: {crop}\n\n{text}")
n_tokens, n_words
flags {has_pesticide_doses, has_fertilizer_doses, is_legal}
prev_id, next_id
spreadsheet chunks only: sheet, row, row_end
```

- The Qdrant point id is `uuid5(chunk_id)`, so ingest is idempotent.
- Payload indexes:
  - keyword: `crop`, `audience`, `doc_id`, `kind`, `chunk_id`, `section_id`;
  - bool: `has_pesticide_doses`, `is_legal`, `has_fertilizer_doses`.

---

## 3. What was done, step by step

### 3.1 Data checks before coding

Two things differed from the task spec:
- **`kukurydza_doradcy` outline**: the spec said no PDF has an outline, but this one has 3 junk entries (`aaaaaa`, title, `bbbbbb`). Structure was still rebuilt from the text TOC.
- **Mojibake**: 4 "dla producentów" PDFs have broken Polish characters (`Poznañ`, `redakcj¹`, `Pawe³`), only on the editorial page. Fixed with a character map.

### 3.2 Parsing PDFs (`pdf_parse.py`)

- **Running heads and footers**:
  - A line in the top or bottom 7% of the page is removed if it repeats on at least 3 pages. The spec's "≥ 30% of pages" rule misses chapter titles, which repeat only within their chapter.
  - Page numbers are read from lone numbers in a wider 12% band, because in `kukurydza_doradcy` the number sits at 8.6% from the bottom.
  - Outliers (e.g. years) are replaced by the value inferred from the offset.
- **Printed page vs PDF page**: the offset is constant per document (−2 for wheat, −1 for maize advisors); missing pages are inferred. GIORiN has no printed page numbers, so its citations use the PDF page.
- **Headings**: in the wheat guide they are not bold. They are ArialMT on top of MinionPro body text, so heading detection also uses "different font family than the body".
- **Hyphenation**: `słowo-\nlowercase` is joined. Real dashes and ranges are kept.
- **Paragraphs**: split on first-line indent (not on a hanging indent), on a short line ending in a full stop, on a vertical gap, and on a style change. A paragraph continued from the previous page (`cont`) is glued back.
- **Chart axis labels** (short, smaller font) are removed.
- **Tables** (`find_tables`):
  - `table.extract()` mangled numbers (`78,9` → `789 ,`) and `get_textbox` bled into neighbouring cells. Cell text is therefore built from `get_text("words")` assigned by word centre, in MuPDF reading order (some header cells hold rotated text).
  - Junk tables (1 column, > 60% empty cells) are rejected.
  - `find_tables` takes about 1 s per page and a process pool made it *slower* on macOS. It runs only on pages with ruling lines, and the results are cached by PDF sha1.
- **Skipped pages**, recorded with a reason: cover, editorial page, TOC, nearly empty pages (photo pages).

### 3.3 Sections (`toc.py`)

- **Inline TOC**: wrapped entries are joined, and both Arabic and Roman numbering is parsed. Arabic numbers restart under each Roman chapter, so ids look like `IV.3.1`.
- **Leaders**: four kinds are handled: `....`, `����`, a tab, and a single dot glued to the page number.
- **Matching**: each entry is matched to a heading block near the expected PDF page, using rapidfuzz, the heading style and the section number. Matching records the page and the block index, so a section can start mid-page.
- **Columnar TOC** (added for `jeczmien_doradcy`): titles end with dots and the page numbers come as a separate column. They are paired per page in order. Unnumbered chapter titles get their number from the next `N.x` entry.
- **GIORiN** (no TOC): bold uppercase disease headings form level 1 and numbered sub-sections form level 2. Two consecutive headings (the two bunts) are merged into one section.

### 3.4 Flags (`flags.py`)

- **`has_pesticide_doses`**:
  - set when the lowest-level section title matches *chemiczne metody / łączne stosowanie herbicydów / zaprawianie / odporność … na środki ochrony / dobór środka ochrony roślin*;
  - or when the text contains a dose (`l|ml|g|kg/ha`) near herbicide/fungicide/środek/… words. Spray volume (`ciecz`), fertilising, nitrogen and sowing rates are excluded.
  - Bug fixed: "Niechemiczne" used to match "chemiczne".
  - "Progi szkodliwości" (economic thresholds) sections under chemical methods are intentionally **not** flagged, because the assistant needs thresholds.
  - Audited: every unflagged chunk with a `…/ha` dose near pesticide words was checked; all 4 were correct negatives (nitrogen dose, spray volume).
- **`has_fertilizer_doses`**: flag only, not excluded.
- **`is_legal`**: legal-regulation chapters, down-weighted rather than excluded.

### 3.5 Chunking (`chunker.py`)

- A chunk never crosses the lowest-level section.
- **Size**: target 180–280 words, hard limit **≤ 450 tokens of the model's tokenizer**. Polish averages 1.54 tokens per word, so the token limit is what binds.
- **Overlap**: 1–2 sentences (≤ 50 words), within the same section, and not across a sub-heading.
- **Small sections** (< 60 words) are carried into the next chunk of the same parent.
- **Tables** are separate chunks:
  - the caption becomes the context line (and is no longer duplicated as a text chunk);
  - long tables are split by rows with the header repeated;
  - "Tabela N. Cd." continuations inherit the previous header.
- **Sub-headings** outside the TOC: bold or different-family font, ≤ 12 words, a single sentence; text after " – " is dropped (e.g. "Omacnica prosowianka"). They start a new chunk and go into the contextual header.
- **Hard guarantee**: `emit()` re-splits any chunk over the limit, word by word measured with the tokenizer. This fixed 6 oversized chunks in the all-crops set (max 697 tokens).
- `chunk_id = {doc_id}:{section_id}:{seq:04d}` is deterministic; a test checks this.

### 3.6 Spreadsheet (`excel_parse.py`)

- **Table headers**: a row with ≥ 2 cells where one names the threat column (choroba/agrofag/szkodnik), or ≥ 2 cells name conditions. A helper row below it (`dzień | noc`, or the temperature/humidity sub-row in the beet sheet) is appended to the column names.
- **Temperature columns** are found by header or by data: the sunflower column "Warunki sprzyjające rozwojowi" holds °C values.
- **Temperature parsing**:
  - `4-18` → 4/18;
  - `ok 20` → 20/20 with `temp_approx`;
  - `25–30°C (optimum 18–22°C)` → 25/30 + optimum 18/22;
  - `> 30°` → min 30;
  - several ranges in one cell, or words only → `null` (no guessing).
- **`threat_type`**: choroba / szkodnik, and `inne` for ambiguous headers ("Agrofag", "Szkodnik / choroba").
- **Notes**: text blocks (pH, BBCH list, "Dodatkowe zagrożenia", "Warunki niesprzyjające") become `note` records. A title belongs only to the block right after it.
- **Result**: 106 records (94 rows, 12 notes), each also a chunk.

### 3.7 Embeddings, Qdrant, BM25

- **Embeddings**: `sdadas/mmlw-retrieval-roberta-base` on MPS. The first full encoding of 1418 passages took 165 s (8.6/s); re-ingests take seconds thanks to the cache.
- **Qdrant**:
  - image pinned to v1.20.2 to match `qdrant-client` 1.20 (v1.15 gave a version warning);
  - collection `guides_mmlw_v1`, cosine distance, dimension 768;
  - upserts in batches of 192, with `wait=True`;
  - `--rebuild` recreates the collection, otherwise only the touched documents are replaced.
- **API checks**: `qdrant-client` 1.20 has only `query_points` (no `search`), and PyMuPDF 2.1 has `find_tables`. Both were checked against the installed versions.
- **BM25**: rank-bm25 on `embed_text`; pystempel's `polimorf` table gives good lemmas (septoriozy → septorioza).

### 3.8 Evaluation (`eval/questions.yaml`, `eval/run_eval.py`)

- **Questions**: 29, plus 3 dose traps.
  - 13 wheat, 12 maize, 4 cereals in general;
  - question types: weather conditions, symptoms, thresholds, BBCH, pH, crop rotation, non-chemical methods;
  - every expected phrase was checked with grep.
- **`expected` format** extended: `contains` can also be a list of phrases that must all be present.

| mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| dense | 0.72 | 0.93 | 1.00 | 0.833 |
| bm25 / stempel | 0.86 | 1.00 | 1.00 | 0.931 |
| bm25 / trunc6 | 0.93 | 1.00 | 1.00 | 0.954 |
| **hybrid / stempel** (default) | 0.86 | 1.00 | **1.00** | 0.920 |
| hybrid / trunc6 | 0.83 | 1.00 | 1.00 | 0.891 |

- **Target hybrid hit@5 ≥ 0.8**: met.
- **Traps**: 0 `has_pesticide_doses` chunks in the top 5.
- **Caveat**: the set is lenient. Any chunk of the right document containing the phrase counts as a hit, and the questions use the guides' wording, which favours BM25. Paraphrased and colloquial questions are still needed.

### 3.9 Integration with the team's app template (after merging `main`)

- **One Docker Compose file**: Qdrant became the `qdrant` service in the root `docker-compose.yml`, next to `db`. It listens on `127.0.0.1` only and uses the named volume `qdrant_storage`. `assistant/docker-compose.qdrant.yml` was removed.
- **Paths**:
  - guides come from the submodule `field-under-pressure-materials/metodyki/` (the same as `settings.MATERIALS_DIR`);
  - generated files go to `assistant/data/`;
  - both can be overridden via `METODYKI_DIR` / `RAG_DATA_DIR` in `.env`.
- **`.env.example`**: `QDRANT_HOST` and `QDRANT_PORT` added to the "Assistant (Ola)" section.
- **`.gitignore`**: the broad `data/` and `metodyki/` entries were replaced by `/assistant/data/`.
- **Package**: the code is imported as `assistant.rag` and all commands run from the repo root.
- **Management commands**: `python manage.py rag_ingest` and `python manage.py rag_search`.
- **Tests**: moved from pytest (`assistant/tests/`, `pytest.ini`) to the Django test runner (`assistant/test_rag.py`, run by `python manage.py test`). They skip, rather than fail, when there is no index or Qdrant is down.
- **Dependencies**:
  - per the team's choice, `requirements.txt` stays the single source: pinned RAG packages are in the "AI assistant (Ola)" section;
  - the temporary `pyproject.toml` / `uv.lock` were removed;
  - uv is used only as the installer (`uv venv --seed`, `uv pip install -r requirements.txt`, `uv run …`).
- **Python 3.11+ required**, because of pymupdf 2.1; the root README now says 3.11+ and `.python-version` is 3.12.
- **pip outside the venv**: `uv venv` without `--seed` creates a venv without pip, so `pip` fell through to the system Python 3.10. Fixed by adding pip to `.venv`; the README now says `uv venv --seed` and explains the symptom.
- **Docs**:
  - `assistant/README.md` got a "Guide search (RAG)" section and the citation proposal;
  - the root README got Qdrant in the setup, a `rag_ingest` step and Python 3.11+;
  - `README_RAG.md` has the new commands.

---

## 4. Current index (all 15 PDFs + spreadsheet)

Qdrant points = chunks = **3978**.
- Tokens per chunk: min 37, median 339, p95 439, max 446. 0 chunks over 450.
- Kinds: 2874 text, 998 table, 94 spreadsheet rows, 12 spreadsheet notes.
- Flags: `has_pesticide_doses` 450, `has_fertilizer_doses` 168, `is_legal` 109.

The core set (5 PDFs + spreadsheet) has **1403** chunks, with flags `has_pesticide_doses` 210, `has_fertilizer_doses` 36 and `is_legal` 27.

| doc_id | crop | audience | pages (skipped) | tables | chunks (text/table) | TOC entries matched |
|---|---|---|---|---|---|---|
| kukurydza_doradcy | kukurydza | doradcy | 248 (39) | 64 | 525 (418/107) | 73/73 |
| kukurydza_producenci | kukurydza | producenci | 70 (14) | 28 | 153 (108/45) | 34/36 |
| pszenica_doradcy | pszenica | doradcy | 224 (36) | 73 | 431 (285/146) | 48/48 |
| pszenica_producenci | pszenica | producenci | 70 (15) | 32 | 141 (79/62) | 35/36 |
| zboza_giorin | zboza | producenci | 24 (4) | 2 | 47 (44/3) | 33/33 (from fonts) |
| jeczmien_doradcy | jeczmien | doradcy | 199 (21) | 51 | 416 (315/101) | 38/42 |
| jeczmien_producenci | jeczmien | producenci | 72 (11) | 18 | 154 (125/29) | 36/36 |
| owies_doradcy | owies | doradcy | 142 (32) | 36 | 246 (189/57) | 30/38 |
| owies_producenci | owies | producenci | 50 (7) | 21 | 105 (75/30) | 35/35 |
| zyto_producenci | zyto | producenci | 56 (15) | 21 | 112 (79/33) | 34/36 |
| pszenzyto_doradcy | pszenzyto | doradcy | 208 (31) | 56 | 374 (270/104) | 41/41 |
| pszenzyto_producenci | pszenzyto | producenci | 60 (16) | 14 | 125 (106/19) | 35/36 |
| burak_doradcy | burak | doradcy | 188 (27) | 66 | 337 (228/109) | 130/130 |
| ziemniak_doradcy | ziemniak | doradcy | 252 (32) | 56 | 458 (342/116) | 46/47 |
| slonecznik_doradcy | slonecznik | doradcy | 160 (24) | 27 | 248 (211/37) | 40/40 |
| ryzyka_zebrane | 5 sheets | — | — | — | 106 (94 rows / 12 notes) | — |

Every document has 100% of its content pages assigned to a section.

**Tests**: `python manage.py test` runs 42/42 OK, of which 22 are the assistant's (chat models + RAG). `manage.py check` reports no issues.

---

## 5. Known limitations and heuristics to refine

- **Hyphenation**: a compound word split across lines ("młynarsko-/piekarniczym") loses its hyphen.
- **Paragraphs and sub-headings** are style heuristics. They are weaker in the "dla producentów" PDFs, where a lot of body text is bold.
- **Tables**:
  - tables without ruling lines stay plain text;
  - for a multi-row header, only the first header row is repeated in each table part.
- **Unmatched TOC entries**: 19 of 707 (owies_doradcy 8, jeczmien_doradcy 4, plus 1–2 in several "producenci" guides). These sections start at the page computed from the offset, at block 0.
- **GIORiN** has no printed page numbers, so citations say "s. PDF n".
- **Pesticide flag**: in practice it comes from section titles. A dose mentioned in prose inside an unflagged section depends on the regex.
- **Spreadsheet**: the temperature unit is not stated in the wheat sheet, so °C is assumed only in the `*_c` fields; the raw text is kept.
- **Evaluation set** is lenient (see 3.8). It only covers wheat, maize and cereals.

## 6. Next steps

1. `assistant/answer.py`: `answer(conversation, message, selected_field) -> Reply` using `search()` plus an LLM, with `Passage.to_citation()` filling `Reply.citations`.
2. MCP tools: guide search (wrapping `search` / `get_passage` / `get_risk_conditions`), read-only SQL through `connections["readonly"]`, and recording observations followed by `engine.predict(...)`.
3. Confirm the citation format with Jan and Szymek (`page` = PDF page; extra `printed_page` / `section`).
4. A harder evaluation set (paraphrases, colloquial symptoms, other crops).
5. Optional: move the vectors into Postgres pgvector, which would remove the `qdrant` service. `VectorStore` keeps this swap local to `store.py`.
