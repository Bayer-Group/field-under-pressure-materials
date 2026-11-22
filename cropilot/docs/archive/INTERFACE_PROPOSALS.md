# Interface proposals from the assistant (Ola)

Changes to shared contracts that the assistant needs. Nothing here is applied to other people's
code: each item says what the assistant does **until** it is accepted. For Jan, Szymek, Bartek, Kuba.

| # | Proposal | For | Status |
|---|----------|-----|--------|
| 1 | `core.Observation` table | Jan + Szymek (schema), Bartek (reads) | done: the assistant writes it; interim rows moved (table kept empty for the engine's adapter) |
| 2 | Read-only database role + `readonly` connection | Jan + Szymek | proposed (needed before the SQL tool is enabled) |
| 3 | Risk levels (cut-offs of the 0–1 score) | Bartek, Kuba | agreed: engine `level` / 0.33–0.66; engine README to fix |
| 4 | `Risk.explanation` format | Bartek, Kuba | assistant reads the starting-point format defensively |
| 5 | Guide citation: extra keys `printed_page`, `section`; spreadsheet citations | Jan + Szymek (chat UI) | proposed |
| 6 | `Reply` extensions: `chart`, `pending_action`, `meta` | Jan + Szymek (chat endpoint/UI) | proposed |
| 7 | Chart format: Vega-Lite v5 | Jan + Szymek, Kuba | proposed |
| 8 | Chat endpoint `POST /api/chat/` built in the `assistant` app | Jan + Szymek | assistant builds it to the agreed contract unless you prefer to |

---

## 1. `core.Observation` — done

`core.Observation` exists (docs/database.md -> Observation). The assistant's `record_observation`
writes it: `kind` from the farmer's words (rules in code), `category` disease / pest / weeds / damage /
other, `severity` 0.3 / 0.6 / 0.9, `distance_m` for neighbour reports, engine facts in `details`
(`sowing_date`, `tillage`, `resistant_to`, `type`, `scope`) plus `source`, the chat draft and the
reassessment status. The interim `assistant.Observation` rows were moved in one migration
(`assistant/0003`) and nothing writes there any more, so no report counts twice. The empty table
stays because the engine's adapter and its tests still read it: **Bartek**, drop the adapter when
convenient and the assistant will drop the table. `predict()` is called with its default end (which now covers the
precomputed days) and `PredictResult.field_ids` gives the fields to reload.

## 2. Read-only role and `connections["readonly"]`

docs/interfaces.md promises a `readonly` connection with a SELECT-only user, a statement time
limit and a row cap. Today `settings.DATABASES` has only `default` (the owner role, full rights).

**Proposal:** a Postgres role `fieldpressure_ro` with `GRANT SELECT` on the `core_*` tables only
(no `assistant_*`, `auth_*`, `django_*`), `ALTER ROLE … SET statement_timeout = '3s'`, and
`DATABASES["readonly"]` pointing at it (credentials from `.env`).

**Until it exists:** the SQL tool (`run_readonly_sql`) is **disabled** — it requires both
`ASSISTANT_ENABLE_SQL=1` and a `readonly` database. The assistant's typed tools read through the
ORM helpers (`season_so_far()`, `coming_days()`, `observed()`, `current()`) on `default` and never write.
The SQL tool itself also validates queries (one SELECT, allowlisted `core_*` tables, no system
functions) and runs them in a read-only transaction with a 3 s timeout and a row cap.

## 3. Risk levels (cut-offs of `Risk.score`) — agreed

The engine writes `level` (low / medium / high) into every explanation; the assistant uses it, and
falls back to the same cut-offs as `engine/scoring.py` and the map (`frontend/src/risk.ts`):
`< 0.33` low, `< 0.66` medium, `≥ 0.66` high (`assistant/domain.py`).
**For Bartek:** `engine/README.md` still says "low < 0.3 ≤ medium < 0.6 ≤ high" — the code and
`docs/interfaces.md` say 0.33 / 0.66; please fix the README.

## 4. `Risk.explanation` format

The assistant reads the starting-point format from docs/database.md defensively:
`{"summary": "...", "factors": [{"variable", "value", "unit", "threshold"}], "source": "..."}`.
It shows `summary` as the engine's reasons and up to 4 `factors`; anything else is ignored.
Request (Bartek): keep `summary` a full Polish sentence (the model quotes it as "powody (silnik)"),
and `variable` = a WeatherDaily column name so the assistant can label it with a unit.

## 5. Citations

Agreed shape kept; additive keys only.

```json
{"type": "guide", "document": "metodyka_-_PSZENICA_-_www.pdf", "page": 79, "printed_page": 77,
 "section": "5. Ograniczanie sprawców chorób > 5.1. Najważniejsze choroby", "ref": 1}
{"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": "pszenica", "row": 19, "ref": 2}
{"type": "risk", "field_id": 3, "threat_code": "wheat.septoria_leaf_blotch", "date": "2024-05-15"}
```

- `page` = PDF page (1-based), so the UI can open `file.pdf#page=79`; `printed_page` = the number
  printed in the book (what a farmer would look up); `section` for the tooltip.
- `ref` = the number shown in the answer text (`[1]`, `[2]`); risk citations have no marker.
- The spreadsheet has no pages: `sheet` + `row` instead.

## 6. `Reply` extensions

`answer()` returns the agreed four fields plus three optional ones with defaults (old callers are
unaffected): `chart: dict | None` (Vega-Lite spec), `pending_action: dict | None`
(`{"type": "confirm_observation", "draft": {...}}`), `meta: dict` (route, LLM usage; stored in
`Message.meta`). **Proposal for the HTTP response:** add `chart` and `pending_action` to the
assistant message (`null` when absent), so the chat window can draw the chart and show
"Zapisz / Anuluj" buttons. **Until accepted:** the response keeps the agreed shape; the draft is
in the text ("Zapisać tę obserwację? (tak / nie)") and the chart only in `Message.meta`.

## 7. Chart format

No format in docs/interfaces.md ("charts: not in this version"). Proposal: **Vega-Lite v5 JSON**
(render with `vega-embed`), Polish titles/axes with units, a dashed "dziś" rule, solid line =
season so far, dashed = forecast. Every chart tool also returns a `summary` computed in code; the
model only comments on it.

## 8. Chat endpoint

`POST /api/chat/`, `GET /api/chat/conversations/`, `GET /api/chat/conversations/{id}/` are built in
`assistant/views.py` exactly to the agreed shapes (no auth, no CSRF, DRF error format), wired by one
line in `fieldpressure/urls.py`: `path("api/", include("assistant.urls"))`. If you prefer to own
the endpoint, move the view; it only calls `answer()` and saves `Message` rows. `ASSISTANT_LLM=fake`
in `.env` gives deterministic answers without API keys for frontend work.
