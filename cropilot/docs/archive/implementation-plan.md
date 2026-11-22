# Implementation plan: platform API, then frontend

> **Historical document (the plan of 21 Nov, morning).** Kept for the decisions and their reasons. Current behaviour: [interfaces.md](../interfaces.md) (the demo date moves only through `core.clock.set_today()`; chat messages carry `chart` and `pending_action`; engine texts are Polish) and [audit-2026-11-21.md](../audit-2026-11-21.md).

Field Under Pressure · owners: Jan + Szymek (map: Kuba) · draft of 21 Nov 2026, branch `feature-frontend`

How to build what [interfaces.md](../interfaces.md) agrees, starting from what exists
([frontend-status.md](frontend-status.md)). Part A is the platform API in `core`; Part B is the frontend, which
reads only through that API. [Decisions](#decisions) records what is settled and what is still open;
[Proposed chat contract](#proposed-chat-contract) was the text for interfaces.md; it is accepted and
now lives there. [Implementation status](#implementation-status-21-nov) lists where the build differs.

## Starting point

- **Exists:** models and query helpers (`core/models.py`, `core/clock.py`), `GET /api/health/`, the chat
  endpoints (`assistant/views.py`, Ola), `/api/schema/` and `/api/docs/` (drf-spectacular), the frontend skeleton.
- **Data to develop against:** `python manage.py assistant_dev_seed` (synthetic clock, 5 fields, threats, risks).
  The platform seed and the real import are a separate step; API tests create their own rows.
- **On `feat/decision-engine`, not merged yet**, and this plan builds on it:
  - `eb4c60e`: the risk **explanation, version 1** is the contract (database.md → Explanation, version 1;
    interfaces.md → Risks; map README → "why" panel); cut-offs 0.33 / 0.66; level names `low` / `medium` / `high`.
  - `cef7707`: `core.Observation` (farmer reports), soil `sand` / `silt` / `clay` as fractions and `band_*` as
    text, and the rule that the demo date changes only through `clock.save()` (the engine listens for it).
  - `predict()` itself, which writes the `Risk` rows the API reads; nothing in this plan waits for it.
- **On `feat/chat-assistant`, not merged yet:** Ola reads explanation v1 (`drivers`, `action`, `growth_stage`).
  Her cut-offs there are 0.3 / 0.6 (taken from an older engine README); they need to go back to 0.33 / 0.66.
- **Merge note:** `feat/decision-engine` still carries the rolled-back frontend and its docs (AGENTS.md, the
  README's Frontend section, the map README's "What is built"). When it is merged into this branch, keep this
  branch's rollback and take only its contract lines (explanation v1, cut-offs, "why" panel, Observation, clock).

## Part A: platform API (Jan + Szymek)

All in `core`. Every endpoint follows the shapes in interfaces.md exactly; if building one shows the contract
needs a change, change interfaces.md in the same commit.

### A0. Foundations

1. **No authentication, no CSRF** (interfaces.md → General rules). In `fieldpressure/settings.py`:
   `REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = []`. DRF already allows everyone by default. `/admin/` is
   Django's own and keeps its login. The chat views' own opt-out becomes redundant but stays (Ola's code).
2. **The forecast horizon in one place:** `core.clock.horizon()` = `today() + FORECAST_DAYS`.
3. **Date parameters** (new `core/api_dates.py`), used by every date endpoint:
   - `parse_date(value, name)`: `YYYY-MM-DD` or `400 {"detail": "<name> must be YYYY-MM-DD"}`;
   - `single_date(value)`: default today; after the horizon → `400 {"detail": "date is after today + 7"}`;
   - `date_range(from_, to, default_from)`: defaults applied, `to` cut at the horizon, `from > to` → `400`;
     returns the dates actually used so the response can report them.
4. **Missing clock row:** a DRF exception handler turns `ClockNotSetError` into
   `503 {"detail": "The demo date is not set: set it in /admin/ or run the seed."}` instead of a 500.
5. **Schema quality:** every view declares named serializers (`Clock`, `Threat`, `FieldFeatureCollection`,
   `FieldDetail`, `DayRisks`, `FieldRiskSeries`, `FieldDayRisks`), so `openapi-typescript` produces readable,
   exact types (B0).
6. **Schema file in git:** `frontend/openapi.yml` is generated with
   `python manage.py spectacular --file frontend/openapi.yml` and committed. A test in `core/test_api.py`
   generates the schema again and fails if it differs from the committed file, so a backend change without a
   regenerated schema is caught by `manage.py test`.
7. **Layout:** `core/serializers.py`, `core/views.py`, `core/urls.py`, tests in `core/test_api.py`.

### A1. Clock: `GET` / `PUT /api/clock/`

- `GET` → `{"today": "2024-05-15", "forecast_days": 7}`.
- `PUT {"today": "2024-06-01"}` → saves the single `Clock` row **with `clock.save()`** (create if missing; never
  `Clock.objects.update()`, which skips the engine's hook), returns the `GET` shape. Invalid date → `400`. Any
  valid date is accepted: a date without data shows empty results, which makes gaps in the data easy to spot.
- **Speed:** on `feat/decision-engine` the engine's hook on that save rewrites every risk row after today; the
  review measured 5.3 s for 3 fields (`docs/engine-predict-review.md`, section 4, on that branch). Until the
  engine changes that, the request can take seconds; the date control shows that it is busy (B2).
- Tests: get, put creates and updates, invalid body, `503` with no row, `PUT` without a CSRF token while
  logged in to `/admin/` (`Client(enforce_csrf_checks=True)`).

### A2. Threats: `GET /api/threats/`

- Every threat: `{code, name, crop: {code, name}, category}`, ordered by crop, then code.
- Tests: shape, order.

### A3. Fields: `GET /api/fields/`, `GET /api/fields/{id}/`

- **List:** a GeoJSON `FeatureCollection`. Per feature: `id`, `geometry` exactly as stored (already EPSG:4326,
  [lon, lat]), `properties: {id, name, crop: {code, name}, area_ha}`.
- **Detail:** `id, name, crop, area_ha, centroid: {lat, lon}, weather_grid_id`, plus:
  - `crop_history`: one entry per year, ascending; `classes` by share, descending: `{code, name, share}`;
  - `soil`: the average over `field.soil_cells()` of `ph, clay, sand, silt, om, cec, bulk_density` in source
    units (after `cef7707`, `clay` / `sand` / `silt` are fractions 0–1), a column that is null in every cell
    stays null; `soil_texture` = the most common class; `null` when the field has no soil cells.
- Unknown id → `404 {"detail": ...}`.
- Tests: GeoJSON shape, soil averaging with a null column, texture majority, crop history order, 404.

### A4. Risks

| Endpoint | Rules |
|----------|-------|
| `GET /api/risks/?date=` | `single_date` (default today). `{date, risks: [{field_id, threat_code, score, level}]}` for every field. `level` is copied from `explanation.level`, so the map colours by level as the explanation contract asks ([decision 10](#decisions)) |
| `GET /api/fields/{id}/risks/?from=&to=` | `date_range`: default `from` = 1 September of the year before the demo year, so winter wheat sown in autumn is covered; default and maximum `to` = today + 7. `{field_id, from, to, threats: [{threat_code, points: [{date, score}]}]}`, threats by code, points by date |
| `GET /api/fields/{id}/risks/{date}/` | `single_date`. `{field_id, date, risks: [{threat: {code, name, category}, score, explanation}]}`, highest score first. `explanation` (version 1) passed through unchanged |

- Unknown field → `404`. A day without rows → empty lists, not an error.
- Tests: shapes; **the cut-off**: a single date after today + 7 is `400`, a range's `to` is cut and reported,
  defaults never pass today + 7, moving the clock moves the limit.

### A5. Finish

- `python manage.py spectacular --validate --fail-on-warn > /dev/null` passes (it does today, for health and chat).
- `python manage.py test core` passes, including the schema-file test.
- interfaces.md: status rows for the API, the demo date control and "API without authentication" set to
  built; the chat rows corrected to "Built (Ola, `assistant/views.py`)"; the `503` for a missing clock under
  General rules; `level` in the `/api/risks/` example.

### Not in Part A

The weather endpoint (shape not defined), the read-only database user, endpoints for `core.Observation` (the
assistant writes it through its own tool), the platform seed/import, and the engine's extra functions proposed on
its branch (`field_day`, `farm_ranking`).

## Part B: frontend (Jan + Szymek; map: Kuba)

The agreed module layout: `main.ts`, `api/`, `events.ts`, `chat/`, `map/`. Plain TypeScript, esbuild, no
framework. UI text in Polish.

### B0. Tooling

- Dependencies: `leaflet` (map), `marked` + `dompurify` (chat), `vega-embed` (charts in the chat, if the proposed
  chat contract is accepted), `openapi-typescript` (dev).
- `npm run api:types`: `openapi-typescript openapi.yml -o src/api/schema.d.ts`. Both files are committed, so the
  frontend builds with Node alone. `npm run api:check` regenerates into a temporary file and fails if the
  committed `schema.d.ts` differs; `npm run build` runs it first. Together with the Python test in A0 this
  catches a stale schema on either side.
- esbuild also emits `dist/main.css` (Leaflet's stylesheet); the template links it. `vega-embed` is split into
  its own chunk and loaded only when a message has a chart (esbuild `--splitting`, ESM).

### B1. Shared pieces

- `events.ts`: `AppEvents` and `EventBus` exactly as in interfaces.md (the rolled-back `events.ts` on `main` has
  the same `AppEvents` and `EventBus`; reuse those and leave out its `ShellBus` and shell types).
- `api/client.ts`: one typed function per endpoint, using the generated types. A non-2xx response throws
  `ApiError(status, detail)`; a missing endpoint or a stopped server becomes a visible message, never an
  unhandled rejection. The chat's `citations` are untyped in the schema, so `api/` adds its own `Citation` type.
- `AppContext = { api, events, clock: { today, forecastDays } }` from interfaces.md, nothing more.
- `risk.ts`: the levels `low` / `medium` / `high`, their colours, and the cut-offs 0.33 / 0.66 for the one
  place that only has a score (the season chart's level lines).

### B2. Page and `main.ts`

- Template: header (title, platform status, demo date control) and a main area with the map and the chat panel
  side by side.
- `main.ts`: creates the `EventBus`, loads `GET /api/clock/` (if it fails: an error in the header and no
  date-dependent requests; never `new Date()`), builds the context, calls `initChat` and `initMap` once and
  awaits neither.
- **Demo date control:** a date input plus ±1 day buttons → `PUT /api/clock/` → on success `main.ts` updates
  `ctx.clock` **in place** (the same object the modules hold) and sends `date:changed`. While the request runs
  the control is disabled and shows that it is working (it can take seconds, A1). Shifting a `YYYY-MM-DD`
  string by a day is fine; reading the browser's date is not.

### B3. Chat (`chat/`)

Can start right away: the chat endpoints exist, and `ASSISTANT_LLM=fake` gives fixed answers without API keys.

- Conversation list (`GET /api/chat/conversations/`), open one (`/{id}/`), start a new one
  (`conversation_id: null`).
- Sending: the user's message appears at once, then "Myślę…", then the answer; send is disabled meanwhile; an
  error replaces the indicator and keeps the typed text.
- Answer text: `DOMPurify.sanitize(marked.parse(text))`; never raw HTML.
- Citations (Ola's proposal 5, accepted): the `[n]` markers in the text link to the citation with that `ref`;
  guide PDF → "{document}, s. {printed_page, else page}" with `section` as the tooltip; spreadsheet →
  "{document}, arkusz {sheet}, wiersz {row}"; `risk` → a link that sends `field:focus`. Unknown keys ignored.
- `focus_field_id` → `field:focus`; non-empty `updated_field_ids` → `risks:updated`.
- `field:selected` → "Pytasz o: {name}" (name from `GET /api/fields/{id}/`), and `field_id` goes with the next
  message; `null` clears it.
- If the proposed chat contract is accepted: the chart under the answer, and **Zapisz** / **Anuluj** under a
  pending observation draft ([rules](#proposed-chat-contract)).

### B4. Map (`map/`, Kuba)

Needs A3 and A4. Contract: `initMap(container, ctx): void`.

- Fields layer from `GET /api/fields/`; a click sends `field:selected`, a click on empty map sends `null`.
- Colouring from `GET /api/risks/?date={ctx.clock.today}`: each field takes its highest `level`; legend with the
  three levels.
- Field panel: details from `GET /api/fields/{id}/`; that day's threats from `GET /api/fields/{id}/risks/{date}/`;
  per threat the "why" from explanation v1, as the map README on `feat/decision-engine` lists it: `level`,
  `summary`, the `drivers` sorted by `effect` (their `label`), `action.text` and, for `treat`,
  `action.spray_window.date`, `growth_stage.name`, `confidence`; unknown keys ignored.
- Season chart from `GET /api/fields/{id}/risks/?to={today + 7}` (default `from`), solid up to today, dashed for
  the coming days, with the 0.33 / 0.66 lines.
- Events: handles `field:focus` (zoom, highlight, then send `field:selected`), `date:changed` (reload colours and
  the open panel, reading `ctx.clock.today`), `risks:updated` (reload those fields).
- Size: the map watches its own container with a `ResizeObserver` and calls Leaflet's `invalidateSize()`; nothing
  outside the map has to tell it.
- Reusable from the rolled-back map on `main`: Leaflet setup and base layers, the field card and its SVG chart
  (with `to` changed to today + 7 and colours by level).

### B5. Finish

- `npm run build` passes (including `api:check`).
- End-to-end on `assistant_dev_seed` + `ASSISTANT_LLM=fake`: select a field → ask → the answer names it →
  click a risk citation → the map focuses that field; change the date → the map recolours; a stopped server or a
  missing endpoint shows a message, not a blank page.
- interfaces.md status rows for the event bus, page and map set to built; the map README updated if Kuba's
  contract changed.

## Order and dependencies

| Step | Who | Needs | Done when |
|------|-----|-------|-----------|
| A0 Foundations | Jan + Szymek | — | helpers and schema test pass, auth off |
| A1 Clock | Jan + Szymek | A0 | tests pass |
| A2 Threats | Jan + Szymek | A0 | tests pass |
| A3 Fields | Jan + Szymek | A0 | tests pass |
| A4 Risks | Jan + Szymek | A0, decision 10 | tests pass, cut-off covered |
| A5 Finish | Jan + Szymek | A1–A4 | schema valid, interfaces.md updated |
| B0–B1 Tooling, shared pieces | Jan + Szymek | A0 | build passes |
| B2 Page, date control | Jan + Szymek | B1, A1 | date moves, `date:changed` sent |
| B3 Chat | Jan + Szymek | B1; charts and buttons: decision 9b | flow works on the fake LLM |
| B4 Map | Kuba | B1, A3, A4 | events and panels work |
| B5 Finish | all | B2–B4 | end-to-end check passes |

A1–A4 are independent of each other once A0 is in. B3 can run alongside Part A; B4 can start on A3 alone (fields
without colours) and add colouring when A4 lands.

## Decisions

### Decided (Szymek, 21 Nov)

- **1. Missing clock row:** `503` with a `detail` for every endpoint that needs today.
- **2. Default season range** for `/api/fields/{id}/risks/`: 1 September of the year before the demo year.
- **3. `PUT /api/clock/`:** any valid date; a date without data shows empty results, which helps catch data gaps.
- **4. Schema files committed** (`frontend/openapi.yml`, `frontend/src/api/schema.d.ts`), with a staleness test
  on each side.
- **5. Layout:** map and chat side by side.
- **6. `initMap` returns `void`**, as agreed: there is no hidden map view, menu or login, so events cover
  everything; the map watches its own size and `main.ts` updates `ctx.clock` in place.
- **7. `explanation` format:** version 1, Bartek's contract, documented on `feat/decision-engine` (`eb4c60e`).
  The assistant already reads it on `feat/chat-assistant`.
- **8. Cut-offs:** 0.33 / 0.66, level names `low` / `medium` / `high`, the same for the engine, the assistant
  and the map.
- **9a. Ola's proposal 5** (extra citation keys): accepted.
- **9b. Ola's proposals 6 and 7** (`pending_action` and `chart`): accepted as the interface (Szymek, 21 Nov).
  The contract is now in interfaces.md → Chat. The platform builds the chat window's side (Vega-Lite charts,
  Zapisz / Anuluj) and does not touch the assistant: Ola's `message_json` adds the two keys to conform.
- **10. `level` in `GET /api/risks/?date=`:** yes (Szymek, 21 Nov). Copied from `explanation.level`; rows
  without one (the assistant's dev seed) get it from the score with the cut-offs.

## Implementation status (21 Nov)

Parts A and B are built on `claude/frontend-backend-api-impl-241034`. Where the build differs from the text above:

- **Moving the date (A1):** `feat/decision-engine` is merged and its engine no longer has a signal on `Clock`.
  The platform calls `engine.clock_moved(old, new)` itself, through `core.clock.set_today()` (save and
  recompute in one transaction), from `PUT /api/clock/` and from the admin's clock page. About 1.5 s per day
  moved on the dev farm.
- **Type generation (B0):** `openapi-typescript` **6.7** (no TypeScript dependency). Version 7 needs
  TypeScript 5's compiler API, which the repo's TypeScript 7 no longer ships.
- **Map (B4):** the map is `feat/map`'s (Bartek, for Kuba), merged here and wired to the platform API through
  `map/contract.ts` (generated types, explanations read as version 1). It replaced a first version built on this
  branch. It adds a field list, level and category filters, a day strip (today + the coming days) and Esri base maps.
- **Still open:** `assistant/views.py` sends neither `chart` nor `pending_action` yet (Ola); the explanation
  texts are still English (Bartek); the end-to-end check on the real assistant needs
  `sentence-transformers` installed (the assistant's guide search imports it).

## Proposed chat contract

Ola's proposals 5–7 ([assistant/INTERFACE_PROPOSALS.md](INTERFACE_PROPOSALS.md)).

Text for interfaces.md → Chat once accepted. Only the chat response changes; the request and the endpoints stay
as they are.

### The assistant message

Two keys are added and always present: `chart` and `pending_action`, each `null` when unused. User messages
have both `null`. The conversation history (`GET /api/chat/conversations/{id}/`) returns them for every message
too (they are stored in `Message.meta`).

```json
{
  "id": 58,
  "role": "assistant",
  "text": "**Szkic obserwacji** (objawy na polu)\n- pole: Pole północne\n- …\n\nZapisać tę obserwację? (tak / nie)",
  "citations": [],
  "focus_field_id": 3,
  "updated_field_ids": [],
  "chart": null,
  "pending_action": {
    "type": "confirm_observation",
    "draft": {"draft_id": "a1b2c3d4e5f6", "field_id": 3, "field": "Pole północne", "date": "2024-05-15", "…": "…"}
  },
  "created_at": "2024-05-15T10:42:00Z"
}
```

### `pending_action`: confirming an observation

The assistant never saves a farmer's report straight away. It drafts it, asks, and saves only after a yes. The
draft lives on the server, in the conversation's state; the message only shows it.

1. The farmer describes what they see. The answer describes the draft in its text, ends with
   "Zapisać tę obserwację? (tak / nie)", and carries `pending_action: {"type": "confirm_observation", "draft": …}`.
2. The chat window shows **Zapisz** and **Anuluj** under that message.
3. A click sends an ordinary message, exactly as if the farmer had typed it:
   `POST /api/chat/ {"conversation_id": 12, "message": "Zapisz", "field_id": …}` (or `"Anuluj"`). No new endpoint
   and no new request field; typing "tak" / "nie" keeps working.
4. **Zapisz:** the server saves the pending draft as an observation, with an idempotency key made from the
   conversation and `draft_id`, so a second click or a repeated "tak" never saves it twice. Then it runs
   `predict()` for the field, and the reply lists the recomputed fields in `updated_field_ids` (→ `risks:updated`,
   the map recolours). **Anuluj:** the draft is dropped.
5. Any other message drops the pending draft; a new observation replaces it with a new draft.

**Rules for the chat window:**

- The buttons are active **only on the last message of the conversation**, and not while a request is running.
  Once a newer message exists, the server no longer holds that draft, so older buttons are shown disabled (also
  when the history is reloaded). This is what stops a click from confirming a different draft than the one on
  screen.
- From `draft` the window may use only `draft_id` and `field_id`; the other keys are for display and Ola may
  change them.
- An unknown `type` shows only the text.

### `chart`: charts in the chat

- A **Vega-Lite v5** spec (`"$schema": "https://vega.github.io/schema/vega-lite/v5.json"`), at most one per
  message, shown under the answer text. Built in code by the assistant's chart tools (risk over time, weather
  against risk, the farm on one day), never written by the model.
- Data is inline (`data.values`), never a URL; the chat window does not draw a spec with a data `url`.
- `"width": "container"`: the chart takes the message's width.
- Polish titles and axis labels with units; solid line = season so far, dashed = coming days, a dashed "dziś"
  line, level lines at 0.33 and 0.66. No data after today + 7 (the tools use the same cut-off as the API).
- The answer text stands on its own: it states the chart's key numbers (computed in code), so nothing is lost if
  the chart cannot be drawn.
- The browser draws it with `vega-embed`, loaded only when a message has a chart, with its actions menu off.

### Citations (proposal 5)

The agreed shape stays; these keys are added, and readers ignore keys they don't know:

- guide PDF: `page` (PDF page, 1-based, so `file.pdf#page=N` opens it), `printed_page` (the number printed in the
  book, may be `null`), `section` (the chapter path), `ref` (the number of the `[n]` marker in the text);
- spreadsheet: `{"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": "pszenica", "row": 19, "ref": 2}`,
  without `page`;
- `risk` citations have no `ref` and no marker in the text.

### What changes when it is accepted

- `assistant/views.py` (`message_json`): `chart` and `pending_action` from `Message.meta` (Ola).
- interfaces.md → Chat: the response example and the three sections above; "Not in this version: charts"
  removed.
- README.md: `vega-embed` as a frontend dependency; assistant/INTERFACE_PROPOSALS.md: proposals 5–7 marked
  accepted (Ola).
- The chat window: B3.
