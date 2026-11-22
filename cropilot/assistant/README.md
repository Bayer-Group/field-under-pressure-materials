# AI assistant

**Owner:** Ola

The chatbot. It answers from the official guides (RAG) and from the platform's data (through MCP): it explains risks, answers questions with citations, and records the farmer's observations.

> **Ola, please confirm or change** (details in [docs/interfaces.md → Chat](../docs/interfaces.md#chat)):
> 1. The **citation format**: `{"type": "guide", "document": "<pdf file name>", "page": 34}` and `{"type": "risk", "field_id": 3, "threat_code": "...", "date": "YYYY-MM-DD"}`.
> 2. The **`answer()` function** you implement (below), with the platform owning the HTTP endpoints and the chat tables.
> 3. **Free-form lookups as read-only SQL**, not ORM code (below).

## What the rest of the system expects

**One function, `answer()`,** in `assistant/answer.py`. The platform's `POST /api/chat/` saves the user's message, calls it, and saves and returns the reply. Until it exists, the endpoint returns a placeholder answer.

```python
def answer(conversation: Conversation, message: str, selected_field: Field | None) -> Reply:
    # Reply: text (markdown), citations, focus_field_id (optional), updated_field_ids
```

- `selected_field` is `None` when the farmer hasn't selected a field (On the frontend map by clicking).
- `focus_field_id` makes the map zoom to a field (if for example the chatbot mentions it); `updated_field_ids` makes the frontend reload fields whose risks changed (requeries the db for new risk assessment).
- Not in this version: charts and streaming. The answer appears all at once after a "thinking…" indicator.

## Guide search (RAG) — built

Search over the guide PDFs and the risk spreadsheet lives in [`rag/`](rag/); full docs (pipeline, chunk schema, evaluation, known limits) in [README_RAG.md](README_RAG.md).

```bash
docker compose up -d                       # db + qdrant (the vector store), one compose file at the repo root
python manage.py rag_ingest                # build the index (~4 min the first time, then ~1 min)
python manage.py rag_search "w jakiej temperaturze rozwija się septorioza paskowana" --crop pszenica
python manage.py test assistant
```

```python
from assistant.rag.search import search, get_passage, get_page, get_risk_conditions

passages = search("septorioza paskowana warunki", crop="pszenica", k=6)   # pesticide-dose passages excluded by default
citations = [p.to_citation() for p in passages]                           # -> Reply.citations
```

Proposed `guide` citation (answers point 1 above; extra keys are additive):
`{"type": "guide", "document": "metodyka_-_PSZENICA_-_www.pdf", "page": 79, "printed_page": 77, "section": "5. … > 5.1. …"}`.
`page` is the PDF page (1-based, so the frontend can open `file.pdf#page=79`); `printed_page` is the number printed in the book, which is what the farmer sees.
The spreadsheet: `{"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": "pszenica", "row": 19}`.

## Talking to the rest of the system

- **Chat tables are yours:** `Conversation` and `Message` live in this app (not `core`). The first version is in [`models.py`](models.py) for convenience (details in [docs/interfaces.md → Chat tables](../docs/interfaces.md#chat-tables)); from now on you change them and create their migrations.
- **MCP is yours:** which tools exist, what they allow and what they refuse.
  - **Free-form lookups** run as **SQL through the read-only connection** `django.db.connections["readonly"]`: that database user can only `SELECT`, and queries are time-limited and row-capped. Never run model-written ORM/Python code: that is arbitrary code execution. The platform provides the read-only user.
  - **Changes** only through narrow tools, e.g. "record an observation" into the planned `Observation` table in `core`. After recording one, call `engine.predict(field_ids=[field.id], start=observation_date)` and return the field in `updated_field_ids`.
- **Guides:** the PDFs and the risk spreadsheet are in the organiser submodule: [`field-under-pressure-materials/metodyki/`](../field-under-pressure-materials/metodyki/) (available in code as `settings.MATERIALS_DIR`). The database image includes pgvector, if you want the RAG index in Postgres.
- **Platform data:** every table, column and unit is described in [docs/database.md](../docs/database.md); start with its [rules](../docs/database.md#rules-for-every-component) and [helper methods](../docs/database.md#using-the-models).
- **The date is `core.clock.today()`,** never `date.today()`. The demo replays a past season, so "this week" or "yesterday" in a farmer's question means relative to that date.
- **Read through the helpers,** so the assistant never sees data the farmer couldn't have yet:
  - risks: `field.risks.season_so_far()` and `field.risks.coming_days()`, each with its `explanation` (the same reasons the map shows);
  - weather: `WeatherDaily.objects.observed()` and `WeatherForecastDaily.objects.current()`;
  - soil: `field.soil_cells()`; crop history: `field.crop_years`; threats: `Threat` (refer to them by `code`).
- **Units are the dataset's** (wind in km/h, humidity in %, risk score 0–1). Say the unit when quoting a value.

## Asystent: narzędzia, MCP, orkiestrator

Status: built on the synthetic dev farm. The real platform import, the decision engine (`engine.predict`) and the read-only DB role don't exist yet; the assistant handles their absence (see "Known limitations").

### Setup

```bash
uv pip install -r requirements.txt         # adds openai, mcp, pydantic (section "AI assistant (Ola)")
docker compose up -d                       # db + qdrant
python manage.py migrate
python manage.py rag_ingest                # guide index (once)
python manage.py assistant_dev_seed        # SYNTHETIC farm for development: 5 fields, threats, weather, toy risks
# .env (see .env.example, section "Assistant"):
#   GEMINI_API_KEY / GROQ_API_KEY, then pick models with:
python manage.py llm_models                # set GEMINI_MODEL / GROQ_MODEL from this list
```

`ASSISTANT_LLM=fake` makes `POST /api/chat/` answer with a fake model (frontend work without keys).

### Commands

| Command | What it does |
|---------|--------------|
| `python manage.py chat "pytanie" [--field ID\|nazwa] [--conversation ID] [--live] [--show-prompt] [--chart-out f.json]` | ask the assistant; FakeLLM by default, `--live` = real API; shows route, prompt size, LLM usage, citations |
| `python manage.py chat_eval [--live] [--only id,…]` | runs `eval/chat_scenarios.yaml` (22 scenarios); `--live` estimates usage and asks first |
| `python manage.py mcp_server` | MCP server (stdio) with the same tools |
| `python manage.py llm_models` | models offered by each configured provider |
| `python manage.py assistant_dev_seed [--wipe]` | synthetic farm (marked `DEV_` / `dev_seed`); `--wipe` removes it |
| `python manage.py test assistant` | all assistant tests (no real LLM; RAG tests skip without Qdrant) |

### Chat endpoint (built here, per docs/interfaces.md)

`POST /api/chat/ {conversation_id, message, field_id}` → `{conversation_id, message: {id, role, text, citations, focus_field_id, updated_field_ids, created_at}}`; `GET /api/chat/conversations/`, `GET /api/chat/conversations/{id}/`. Wired with one line in `fieldpressure/urls.py`. Route, LLM usage, chart spec and observation draft are stored in `Message.meta`.

### Tools (`assistant/tools/`, one definition each — orchestrator and MCP share them)

| Tool | Writes | What |
|------|--------|------|
| `search_guides`, `get_passage`, `get_risk_conditions` | – | guides (RAG, dose passages always excluded), risk spreadsheet rows |
| `get_season_date`, `list_fields`, `get_field` | – | demo date, fields, field details (no geometry) |
| `get_field_risks` | – | engine risk per threat: score, the engine's level, trend, max, engine explanation; ≤ today + 7 |
| `get_farm_risk_summary` | – | top threats per field, most urgent field × threat pairs |
| `get_weather` | – | observed + forecast; weekly aggregation for ranges > 31 days |
| `get_observations` | – | farmer observations of a field |
| `chart_risk_timeline`, `chart_weather_vs_risk`, `chart_farm_overview` | – | Vega-Lite spec + `summary` computed in code |
| `record_observation` | yes | idempotent save to `core.Observation` + `engine.predict` (MCP: only with `confirm=true`; never offered to an agent loop) |
| `run_readonly_sql` | – | disabled until `ASSISTANT_ENABLE_SQL=1` **and** a `readonly` DB exists |

### Flows (`assistant/orchestrator/`) — code decides, the model writes, ≤ 1 LLM call per question

| Route (router, no LLM) | Flow |
|------------------------|------|
| `pytanie_ogolne` | guide search (crop from the question/threat) → 1 call; dose questions get an extra rule + a guaranteed referral to the label |
| `pytanie_o_pole` | field: selected → named → highest risk today; RAG queries **from the engine's top threats**, + spreadsheet conditions; structure: why (engine) / guides (cited) / what to do / discrepancies |
| `podsumowanie_farmy` | 3 most urgent field × threat pairs (one per field) + guides for 2 threats → 1 call |
| `wykres` | chart tool (params by code) → 1 short call commenting only the code's `summary` |
| `obserwacja` → `potwierdzenie` | 1 JSON call → draft validated by code → "tak" → `record_observation` → template answer (no LLM); repeated "tak" = no duplicate |
| `poza_zakresem` | fixed answer, no LLM |

Citations: the model writes `[chunk_id]`; `citations.finalize` turns known ids into `[1]`, `[2]` with `Passage.to_citation()` (+ `"ref"`), drops ids it was never given. Risk citations (`type: risk`) come from the engine data. Guard: a pesticide dose in the answer → one regeneration → fixed safe message. Usage: `logs/llm_usage.jsonl` (gitignored) and `Message.meta.llm_calls`.

### MCP

```bash
npx @modelcontextprotocol/inspector .venv/bin/python manage.py mcp_server     # from the repo root
```

Claude Desktop (`claude_desktop_config.json`), absolute paths:

```json
{"mcpServers": {"field-under-pressure": {
  "command": "/ABS/PATH/teamSzaletGeoHackaton/.venv/bin/python",
  "args": ["/ABS/PATH/teamSzaletGeoHackaton/manage.py", "mcp_server"]}}}
```

Logs go to stderr; stdout carries only the protocol. The server warms up the embedding model, BM25, Qdrant and the DB before serving (~5 s).

### Known limitations

- **No engine yet**: observations are saved but `reassessment.status = "unavailable"`; risk explanations in dev data are synthetic.
- **Risk levels** come from the engine's `explanation.level`; fallback cut-offs < 0.33 / < 0.66 as in `engine/scoring.py` and the map (`assistant/domain.py`).
- **Observations** are written to `core.Observation` (the interim `assistant.Observation` rows were moved; the table is kept empty for the engine's adapter).
- **SQL tool off**: no read-only role.
- **Agent mode (step G) not built**: complex questions use the single-call flows.
- **No live run yet**: `.env` has no LLM keys; everything was verified with FakeLLM. Answer quality, Polish style and real citation behaviour need `chat_eval --live`.
- Token counts before the call are estimates (characters / 3, deliberately high).
