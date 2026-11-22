# Interfaces

Field Under Pressure · owners: Jan + Szymek · last updated 21 Nov 2026

How the components talk to each other: the frontend modules, the events between map and chat, the platform API, the chat, the assistant's data access and the decision engine. The tables behind all of this are in [database.md](database.md).

## Status

| Piece | Status | Built by |
|-------|--------|----------|
| [Event bus](#events-between-map-and-chat) (`frontend/src/events.ts`) | Built | Jan + Szymek |
| [Page and app context](#frontend-modules) (`main.ts`, `api/`) | Built | Jan + Szymek |
| [Map module](#the-map-module) (`initMap`) | Built (`feat/map`, merged and wired to the platform API) | Kuba (built by Bartek) |
| [Platform API](#platform-api) | Built, except the weather endpoint (shape not defined) | Jan + Szymek |
| [Demo date control](#clock) (`PUT /api/clock/` + header control) | Built | Jan + Szymek |
| [Chat tables](#chat-tables) (`Conversation`, `Message`) | Exists | Jan + Szymek (first version), then Ola |
| [Chat endpoints](#chat) | Built (Ola, `assistant/views.py`), including the `chart` and `pending_action` keys | Ola |
| [Chat window](#chat) (`frontend/src/chat/`) | Built, including charts and the observation buttons | Jan + Szymek |
| [`answer()`](#the-answer-function), MCP tools, RAG | Built | Ola |
| [Read-only database user](#free-form-lookups-read-only-sql) | To build | Jan + Szymek |
| [Observation table](#writing-observations) (`core.Observation`) | Exists; the assistant writes it (its migration 0003 moved the interim rows) | Jan + Szymek (schema), Ola (writes), Bartek (reads) |
| [`as_of` on the query helpers](#as_of-on-the-helpers) | Exists | Jan + Szymek |
| [`predict()`](#decision-engine), `clock_moved()` | Built | Bartek |
| [API without authentication](#general-rules) | Built (`REST_FRAMEWORK` settings) | Jan + Szymek |
| [API cut-off at today + 7](#no-data-after-the-forecast) | Built (`core/api_dates.py`, every date-based endpoint) | Jan + Szymek |

## General rules

- **No logins, no tokens.** The API is open; it's a single-farm demo. Nothing needs a CSRF token.
- **JSON** with snake_case keys; dates as `YYYY-MM-DD` (only that form: ISO weeks like `2024-W22-1` or `20240601` are a 400); timestamps in ISO 8601, UTC. Request bodies are JSON only (`Content-Type: application/json`; a form-encoded body is a 415), so a form on another site can't post to the API.
- **Units** are the database's (source units), under the database column names. See [database.md](database.md#unit-traps).
- **GeoJSON** coordinates are **[lon, lat]**, EPSG:4326.
- **Nothing after the forecast.** The API never returns data dated after today + 7; see [below](#no-data-after-the-forecast).
- **Errors** use Django REST Framework's format: `{"detail": "..."}` with a 4xx status, also for any `/api/` path no endpoint matches (404 `{"detail": "Not found."}`, never Django's HTML page). The `detail` texts are English; the page shows them in Polish (`frontend/src/api/client.ts`).
- **No demo date:** while the `Clock` row is missing, every endpoint that needs today answers `503 {"detail": "The demo date is not set: set it in /admin/ or run the seed."}`.
- **TypeScript types are generated, not written.** Both files are committed: `frontend/openapi.yml` (`python manage.py spectacular --file frontend/openapi.yml`) and `frontend/src/api/schema.d.ts` (`cd frontend && npm run api:types`). If the backend changes, regenerate both; the type checker shows what broke. `python manage.py test core` fails if `openapi.yml` is stale, and `npm run build` fails if `schema.d.ts` is.

### No data after the forecast

**How the demo is filled.** The demo replays a past season, so the database holds the whole season from the start (details in [database.md](database.md#how-the-demo-is-filled)):

- observed weather for every day of the season;
- a 7-day forecast for every day of the season, copied from the observed weather;
- risks for every day of the season, precomputed once by `predict()`;
- the `Clock` row, set to the day the demo starts.

So rows dated after the demo's today (say June, when today is 15 May) are already in the database, although a farmer on 15 May could only know the weather and risks up to 15 May plus the forecast for 16–22 May.

**Who keeps them hidden.**

- **Python code** (engine, assistant) reads through the query helpers (`.observed()`, `.current()`, `season_so_far()`, `coming_days()`), which never return anything later.
- **The frontend** reads only through the API, and the helpers don't protect it. So **the API must enforce the same limit on every endpoint that takes a date**:
  - a single `date` after today + 7 is an error: `400 {"detail": "date is after today + 7"}`;
  - a range's `to` is cut off at today + 7, and the response's `to` says where it stopped;
  - with no dates given, the defaults never go past today + 7.

The frontend can rely on this and doesn't need its own checks: a chart or date slider simply can't receive data past the forecast. The legitimate way to see later days is to **move the demo date** ([`PUT /api/clock/`](#clock)); then the limit moves with it.

## Frontend modules

```text
frontend/src/
  main.ts      starts the page: creates the context, mounts chat + map, demo date control
  api/         typed API client + generated types
  events.ts    typed event bus
  chat/        chat window
  map/         map (Kuba)
```

Every module gets the same context and talks to the rest of the page only through it:

```ts
interface AppContext {
  api: Api;                                         // typed calls to the platform API
  events: EventBus;                                 // see below
  clock: { today: string; forecastDays: number };   // updated by main.ts on "date:changed"
}
```

### The map module

The map module exports one function. `main.ts` calls it once with the map's container:

```ts
// frontend/src/map/index.ts
export function initMap(container: HTMLElement, ctx: AppContext): void;
```

The map draws itself inside `container`, loads its data through `ctx.api`, and sends and receives events through `ctx.events`. It never reads the date from `new Date()`: the demo's date is `ctx.clock.today`.

## Events between map and chat

The modules never call each other. They send custom events through one shared, private `EventTarget` (created in `main.ts`, passed in the context; not `document`, so nothing can clash with browser or library events). A typed wrapper makes a wrong event name or payload a type error:

```ts
// frontend/src/events.ts
export interface AppEvents {
  "field:selected": { fieldId: number | null };   // null = no field selected
  "field:focus": { fieldId: number };
  "date:changed": { today: string };
  "risks:updated": { fieldIds: number[] };
}

export class EventBus {
  private target = new EventTarget();

  emit<K extends keyof AppEvents>(type: K, detail: AppEvents[K]): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof AppEvents>(type: K, handler: (detail: AppEvents[K]) => void): () => void {
    const listener = (event: Event) => handler((event as CustomEvent<AppEvents[K]>).detail);
    this.target.addEventListener(type, listener);
    return () => this.target.removeEventListener(type, listener); // call to stop listening
  }
}
```

| Event | Payload | Sent by | Handled by |
|-------|---------|---------|------------|
| `field:selected` | `{ fieldId: number \| null }` | map: the user clicks a field (or empty map: `null`) | chat: shows "Asking about: …" and sends `field_id` with the next message |
| `field:focus` | `{ fieldId: number }` | chat: an answer has `focus_field_id`, or the user clicks a risk citation | map: zooms to and highlights the field, then sends `field:selected` itself |
| `date:changed` | `{ today: "YYYY-MM-DD" }` | `main.ts`, after the demo date control saved the new date | map: reloads; `main.ts` updates `ctx.clock` first |
| `risks:updated` | `{ fieldIds: number[] }` | chat: an answer has `updated_field_ids` (an observation was recorded) | map: reloads those fields |

Events are handled synchronously, in the order they are sent. Selecting a field is always optional: with no field selected, the chat still works.

## Platform API

Built by Jan + Szymek with Django REST Framework. Once an endpoint exists, its exact schema is at <http://localhost:8000/api/docs/>. The examples below are the agreed shapes.

| Request | Returns | Used by |
|---------|---------|---------|
| `GET /api/health/` | `{status, database, clock, assistant: {available, llm, rag, reason} \| null}` | the page's status line; the chat greys itself out when `assistant.available` is false |
| `GET /api/clock/` | the demo's date | everyone |
| `PUT /api/clock/` | sets the demo's date | demo date control |
| `GET /api/threats/` | every threat | legend, filters |
| `GET /api/fields/` | every field as GeoJSON | map |
| `GET /api/fields/{id}/` | one field's details | field panel |
| `GET /api/risks/?date=` | every field's risks on one day | colouring the map |
| `GET /api/fields/{id}/risks/?from=&to=` | one field's risks over time | season chart |
| `GET /api/fields/{id}/risks/{date}/` | one field's risks on one day, with explanations | "why" panel |
| `GET /api/fields/{id}/weather/?from=&to=` | observed + forecast weather | later, shape not defined yet |

### Clock

```json
// GET /api/clock/
{"today": "2024-05-15", "forecast_days": 7, "min_date": "2022-09-01", "max_date": "2024-12-31"}

// PUT /api/clock/   body: {"today": "2024-06-01"}   → returns the same shape as GET
```

The demo date control in the page header sends the `PUT`; on success `main.ts` updates `ctx.clock` in place and sends `date:changed`. `min_date` / `max_date` are the dates `PUT` accepts: the days a forecast was issued on (the scenario's window, previous season included), else the days with observed weather; both `null` when there is no weather at all (then any date is accepted). A date outside them is `400 {"detail": "today must be between 2022-09-01 and 2024-12-31 (the days with weather)"}`; an invalid one is `400 {"detail": "today must be YYYY-MM-DD"}`. The date control sets them as the picker's limits.

Moving the date recomputes the days whose inputs change: `engine.clock_moved(old, new)` rewrites the risks of (min(old, new), max(old, new) + 7] ([archive/engine-predict-review.md](archive/engine-predict-review.md#4-moving-the-demo-date-rewrites-the-rest-of-the-season)). The engine has no signal, so every date change goes through **`core.clock.set_today(new)`**, which saves the row and calls `clock_moved` in one transaction (if the engine fails, the date stays): `PUT /api/clock/` and the admin's clock page use it; from the terminal, `python manage.py engine_set_date D`. Never change the date with `Clock.objects.update(...)` or a bare `clock.save()`. With the date cache filled (`engine_precompute_dates`, demo date − 7 … + 30) a move copies precomputed rows and takes about 0.3 s; a field changed by a farmer's report since then, or a date outside the cache, is computed (2–5 s); a move into another season recomputes both seasons (about 10 s). The date control shows that it is busy, and asks before a jump of more than a month.

### Threats

```json
// GET /api/threats/
[
  {"code": "wheat.septoria_leaf_blotch", "name": "septorioza paskowana liści pszenicy",
   "crop": {"code": 1110, "name": "Wheat"}, "category": "fungal"}
]
```

### Fields

```json
// GET /api/fields/
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 3,
      "geometry": {"type": "Polygon", "coordinates": [[[19.95, 50.03], [19.96, 50.03], [19.96, 50.04], [19.95, 50.03]]]},
      "properties": {"id": 3, "name": "North field", "crop": {"code": 1110, "name": "Wheat"}, "area_ha": 20.4}
    }
  ]
}
```

```json
// GET /api/fields/3/
{
  "id": 3,
  "name": "North field",
  "crop": {"code": 1110, "name": "Wheat"},
  "area_ha": 20.4,
  "centroid": {"lat": 50.035, "lon": 19.955},
  "weather_grid_id": "…",
  "crop_history": [
    {"year": 2023, "classes": [{"code": 1130, "name": "Maize", "share": 0.92}, {"code": 0, "name": "No cropland", "share": 0.08}]}
  ],
  "soil": {"ph": 6.4, "soil_texture": "silt loam", "clay": 0.182, "sand": 0.21, "silt": 0.608, "om": 24.1, "cec": 14.3, "bulk_density": 1.32}
}
```

`soil` holds the root-zone columns of [SoilCell](database.md#soilcell), averaged over the field's cells, in the same units (`clay`, `sand`, `silt` are fractions 0–1). A column that is empty in every cell stays `null`; `soil_texture` is the most common class (ties: alphabetical). `soil` is `null` when the field has no soil cells. `crop_history` has one entry per year, oldest first, its `classes` by share, largest first. An unknown id is `404`.

### Risks

```json
// GET /api/risks/?date=2024-05-15        (date defaults to today; at most today + 7)
{"date": "2024-05-15", "risks": [{"field_id": 3, "threat_code": "wheat.septoria_leaf_blotch", "score": 0.72, "level": "high"}]}
```

`level` is copied from the row's `explanation.level`, so the map colours by level without the explanations. For rows whose explanation has no level (the assistant's dev seed), it comes from the score with the cut-offs below.

```json
// GET /api/fields/3/risks/?from=2024-04-01&to=2024-05-22     (to is cut off at today + 7)
// defaults: from = 1 September of the year before the demo's year (covers winter wheat), to = today + 7
{
  "field_id": 3, "from": "2024-04-01", "to": "2024-05-22",
  "threats": [{"threat_code": "wheat.septoria_leaf_blotch", "points": [{"date": "2024-04-01", "score": 0.1}]}]
}
```

```json
// GET /api/fields/3/risks/2024-05-15/
{
  "field_id": 3, "date": "2024-05-15",
  "risks": [
    {"threat": {"code": "wheat.septoria_leaf_blotch", "name": "septorioza paskowana liści pszenicy", "category": "fungal"},
     "score": 0.72,
     "explanation": {
       "version": 1,
       "summary": "Wysokie ryzyko septoriozy paskowanej liści: 14 godzin z mokrymi liśćmi przy 10–20 °C w ostatnich 7 dniach; pszenica w fazie strzelania w źdźbło (BBCH 32).",
       "level": "high", "score": 0.72,
       "threat": {"code": "wheat.septoria_leaf_blotch", "name_pl": "septorioza paskowana liści", "name_en": "Septoria leaf blotch", "category": "fungal"},
       "as_of": "2024-05-15",
       "growth_stage": {"bbch": 32, "name": "strzelanie w źdźbło", "method": "degree days", "sowing_assumed": "2023-10-01", "confidence": 0.6},
       "drivers": [
         {"factor": "condition_hours", "label": "Godziny z mokrymi liśćmi przy 10–20 °C (7 dni)", "value": 14, "unit": "h",
          "threshold": "od 5 h ryzyko rośnie, 20 h = pełne", "effect": 0.72},
         {"factor": "rain_days", "label": "Dni z opadem ≥ 1 mm", "value": 3, "unit": "dni", "effect": null}
       ],
       "action": {"type": "treat", "text": "Wysokie ryzyko: obejrzyj pole teraz; po przekroczeniu progu zabieg jest uzasadniony.",
                  "threshold": "…", "spray_window": {"date": "2024-05-17", "quality": "acceptable"}},
       "confidence": 0.6
     }}
  ]
}
```

Scores are 0–1 (an index, not a probability). Days up to today are the season so far; today + 1 … today + 7 are the coming days.

**`explanation` is version 1**, written by the engine and passed through by the API unchanged. The full key list, who reads what and the open points are in [database.md → Explanation, version 1](database.md#explanation-version-1). The example above is trimmed (no `crop`, `severity`, `expected_loss`, `notes`, `assumptions`, `model`). In short:

- **Colour** from `level`: `low` / `medium` / `high` (cut-offs 0.33 and 0.66). Show it; don't recompute it from the score.
- **Why** from `summary` and `drivers`: each driver has a `label` and an `effect` (how much the score would drop without it; `null` = context only). Sort by `effect`.
- **What to do** from `action`: `type` (`wait` / `monitor` / `treat`), `text`, and for `treat` a `spray_window` from the forecast.
- **How sure** from `confidence` (0–1; lower for coming days).
- Texts are shown to the farmer as they are, so they are Polish (the engine writes Polish since v0.11). Ignore keys you don't know.

## Chat

Chats are stored like in any chat app. The endpoints and [`answer()`](#the-answer-function) are built by Ola in `assistant/`; the chat window (`frontend/src/chat/`) by Jan + Szymek.

### Endpoints

```json
// POST /api/chat/
{"conversation_id": 12, "message": "Why is the north field at risk?", "field_id": 3}
// conversation_id: null starts a new conversation
// field_id: null when no field is selected
```

```json
// response
{
  "conversation_id": 12,
  "message": {
    "id": 57,
    "role": "assistant",
    "text": "Markdown answer… [1]",
    "citations": [
      {"type": "guide", "document": "metodyka_-_PSZENICA_-_www.pdf", "page": 34, "printed_page": 32, "section": "5.2 Choroby", "ref": 1},
      {"type": "risk", "field_id": 3, "threat_code": "wheat.septoria_leaf_blotch", "date": "2024-05-15"}
    ],
    "focus_field_id": null,
    "updated_field_ids": [],
    "chart": null,
    "pending_action": null,
    "created_at": "2024-05-15T10:42:00Z"
  }
}
```

| Request | Returns |
|---------|---------|
| `POST /api/chat/` | sends a message, returns the assistant's answer (above) |
| `GET /api/chat/conversations/` | `[{id, title, updated_at}]`, newest first. The title is the start of the first message |
| `GET /api/chat/conversations/{id}/` | `{id, title, messages: [...]}`, each message in the shape above (user messages have empty `citations` and `null` `chart` / `pending_action`) |

`chart` and `pending_action` (Ola's proposals 6 and 7, accepted on 21 Nov) are always present, each `null` when unused, also in the conversation history (they are stored in `Message.meta`). Without an LLM configured, `POST /api/chat/` answers `503 {"detail": "Asystent jest wyłączony: …"}` and stores nothing.

**Not in this version:** streaming. The answer appears all at once after a "thinking…" indicator.

**In the browser:** the user's message appears immediately, then "Myślę…", then the answer; sending is disabled meanwhile, and an error replaces the indicator and keeps the typed text. The markdown is turned into HTML and sanitised (DOMPurify) before it goes into the page; the model's output is never inserted as raw HTML. `focus_field_id` → `field:focus`; non-empty `updated_field_ids` → `risks:updated`. Readers ignore keys they don't know.

#### Citations

- `guide`, a PDF passage: `document` (the file name in `field-under-pressure-materials/metodyki/`), `page` (PDF page, 1-based, so `file.pdf#page=N` opens it), `printed_page` (the number printed in the book, may be `null`), `section` (the chapter path), `ref` (the number of the `[n]` marker in the text). Shown as "{document}, s. {printed_page, else page}", with `section` as the tooltip.
- `guide`, a spreadsheet row: `{"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": "pszenica", "row": 19, "ref": 2}`, without `page`. Shown as "{document}, arkusz {sheet}, wiersz {row}".
- `risk`: a risk row the answer relies on (`field_id`, `threat_code`, `date`); no `ref` and no marker in the text. The chat shows it as a link; clicking it sends `field:focus`.

The `[n]` markers in the text link to the citation with that `ref`.

#### `pending_action`: confirming an observation

The assistant never saves a farmer's report straight away. It drafts it, asks, and saves only after a yes. The draft lives on the server, in the conversation's state; the message only shows it.

```json
"pending_action": {
  "type": "confirm_observation",
  "draft": {"draft_id": "a1b2c3d4e5f6", "field_id": 3, "field": "Pole północne", "date": "2024-05-15", "…": "…"}
}
```

1. The farmer describes what they see. The answer describes the draft in its text, ends with "Zapisać tę obserwację? (tak / nie)", and carries `pending_action` as above.
2. The chat window shows **Zapisz** and **Anuluj** under that message.
3. A click sends an ordinary message, exactly as if the farmer had typed it: `POST /api/chat/ {"conversation_id": 12, "message": "Zapisz", "field_id": <draft.field_id>}` (or `"Anuluj"`). No new endpoint and no new request field; typing "tak" / "nie" keeps working.
4. **Zapisz:** the server saves the pending draft as an observation, with an idempotency key made from the conversation and `draft_id`, so a second click or a repeated "tak" never saves it twice. Then it runs `predict()` for the field, and the reply lists the recomputed fields in `updated_field_ids` (→ `risks:updated`, the map recolours). **Anuluj:** the draft is dropped.
5. Any other message drops the pending draft; a new observation replaces it with a new draft.

Rules for the chat window: the buttons are active **only on the last message of the conversation**, and not while a request is running (once a newer message exists, the server no longer holds that draft, so older buttons are disabled, also in a reloaded history). From `draft` the window uses only `draft_id` and `field_id`; the other keys are for display and may change. An unknown `type` shows only the text.

#### `chart`: charts in the chat

- A **Vega-Lite v5** spec (`"$schema": "https://vega.github.io/schema/vega-lite/v5.json"`), at most one per message, shown under the answer text. Built in code by the assistant's chart tools (risk over time, weather against risk, the farm on one day), never written by the model.
- Data is inline (`data.values`), never a URL; the chat window does not draw a spec with a data `url` anywhere.
- `"width": "container"`: the chart takes the message's width (the window sets it).
- Polish titles and axis labels with units; solid line = season so far, dashed = coming days, a dashed "dziś" line, level lines at 0.33 and 0.66. No data after today + 7 (the tools use the same cut-off as the API).
- The answer text stands on its own: it states the chart's key numbers (computed in code), so nothing is lost if the chart cannot be drawn.
- The browser draws it with `vega-embed` (Polish date and number formats), loaded only when a message has a chart, with its actions menu off.

### Chat tables

They live in [`assistant/models.py`](../assistant/models.py), not `core`: they are specific to the assistant, so Ola owns them. Jan + Szymek created the first version; from now on only Ola changes them (and creates their migrations).

| Table | Columns |
|-------|---------|
| `Conversation` | `title`, `created_at`, `updated_at` |
| `Message` | `conversation`, `role` (`user` / `assistant`), `text`, `citations` (JSON, empty list by default), `field` (the field selected when sent, nullable), `focus_field` (nullable), `created_at` |

- `conversation.messages` lists a conversation's messages, oldest first; `Conversation.objects` lists conversations newest first.
- Saving a message moves its conversation's `updated_at` forward, so the conversation list stays in order.
- `Conversation.title_from(text)` makes a title from the first message (its first line, at most 80 characters).
- If a field is deleted, messages keep their text and the field columns become empty.

### The `answer()` function

Everything the assistant does (prompts, RAG, MCP tools) sits behind one function that Ola implements. The platform calls it from `POST /api/chat/`:

```python
# assistant/answer.py (Ola)
from dataclasses import dataclass, field as dataclass_field

from assistant.models import Conversation
from core.models import Field


@dataclass
class Reply:
    text: str                                                    # markdown
    citations: list[dict] = dataclass_field(default_factory=list)
    focus_field_id: int | None = None
    updated_field_ids: list[int] = dataclass_field(default_factory=list)
    chart: dict | None = None             # Vega-Lite v5 spec (sent as "chart")
    pending_action: dict | None = None    # {"type": "confirm_observation", "draft": {...}} (sent as "pending_action")
    meta: dict = dataclass_field(default_factory=dict)  # route, LLM usage, errors (stored in Message.meta, not sent)


def answer(conversation: Conversation, message: str, selected_field: Field | None) -> Reply:
    ...
```

The platform saves the user's message before calling `answer()` (it is the last message in `conversation`) and saves the reply afterwards.

## The assistant's data access

Ola owns everything MCP: which tools exist, what they allow and what they refuse. The platform provides two pieces of infrastructure for it.

### Free-form lookups: read-only SQL

For questions no specific tool covers, the assistant can run **SQL**, never ORM code. ORM queries are Python, and running model-written Python is running arbitrary code. SQL through a read-only database user is safe because Postgres enforces it:

- a separate database user that can only `SELECT` from the platform tables;
- every query stopped after a time limit (e.g. 2 s);
- results capped (e.g. 500 rows).

The platform adds the user and a second database connection, `readonly`, in the settings. The MCP tool runs queries only through `django.db.connections["readonly"]`.

### Writing observations

The assistant changes data only through narrow tools, for example "record an observation". Reports go into `core.Observation`: farm data that the engine reads. Columns, the six `kind` values and examples are in [database.md → Observation](database.md#observation). In short:

- `kind` says what the report is (`symptoms`, `absence`, `neighbour`, `treatment`, `field_fact`, `event`); the engine skips a row without a known kind.
- `threat` if the farmer named one; otherwise `category` (`disease` / `pest`) so the engine knows which threats to raise.
- `severity` is a number 0–1, `distance_m` is for neighbour reports, facts and event types go in `details`.
- `field` empty = the whole farm.

After recording one, the tool calls `engine.predict(field_ids=[field.id], start=observation_date)` and the answer returns that field in `updated_field_ids`, so the map reloads it.

**Moving from the interim table:** the engine reads both `core.Observation` and the assistant's interim `assistant.Observation`. If rows exist in both, every report counts twice. So the assistant switches its tool to `core.Observation` and moves (copies, then deletes) its interim rows in the same change.

Both gaps found in [archive/engine-predict-review.md](archive/engine-predict-review.md) are fixed: the default `end` is the later of today + 7 and the last day already stored for these fields, so precomputed days get the report's effect too; and `predict()` returns a `PredictResult` (an int plus `.field_ids`) that lists the nearby fields a symptoms report spread to, which the assistant sends in `updated_field_ids`.

## Decision engine

The engine exposes one function. It computes risks and writes them all at once, overwriting earlier ones:

```python
# engine (Bartek)
def predict(field_ids: list[int] | None = None, start: date | None = None, end: date | None = None) -> int:
    """
    Compute risks for the given fields (default: all) from start to end (default: the whole
    season up to today + 7), and overwrite them in the Risk table in one bulk write.
    Returns the number of rows written.
    """
```

It works through the days in order, each one **as of that day**: only the weather observed up to that day, plus the forecast issued that day. The current implementation differs in several places, and some of this wording needs tightening: see [archive/engine-predict-review.md](archive/engine-predict-review.md). It can be called from anywhere:

| When | Call |
|------|------|
| After the seed / import | `predict()` over the whole season, so moving the demo date is instant |
| After an observation is recorded | `predict(field_ids=[field.id], start=observation_date)` |
| By hand | a management command, e.g. `python manage.py engine_predict` |

### `as_of` on the helpers

`.observed()` and `.current()` cut at the clock's today, which would stop `predict()` from working through a whole season. So they take an optional `as_of` date that defaults to `clock.today()`:

```python
WeatherDaily.objects.observed(as_of=day)          # weather up to that day
WeatherForecastDaily.objects.current(as_of=day)   # the forecast issued that day
```

Only the engine passes `as_of`; everyone else calls the helpers without it.
