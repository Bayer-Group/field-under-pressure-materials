# Frontend: agreed docs vs what is built

Field Under Pressure · owners: Jan + Szymek · state on 21 Nov 2026, branch `feature-frontend`

> **Superseded:** the pieces listed below as missing are now built; see [implementation-plan.md → Implementation status](implementation-plan.md#implementation-status-21-nov). Kept as the record of the starting point.

What the agreed documentation says the frontend must do, and how much of it exists. "Agreed" means the
documents as of 3e96862, before the unagreed frontend commits:

- [docs/interfaces.md](../interfaces.md): frontend modules, map–chat events, platform API, chat;
- [frontend/src/map/README.md](../../frontend/src/map/README.md): the map's contract (Kuba);
- [architecture_overview.md](../../architecture_overview.md) and [README.md](../../README.md): the product and the setup.

Two "built" columns:

- **Here**: this branch (frontend rolled back to 3e96862; the backend as on `main`).
- **Rolled back**: what the unagreed frontend on `main` (4cabf4b, 38767d7) did. It is not on this branch;
  it is listed so we know what can be reused and where it left the agreed contract.

## Summary

- **Frontend, here:** only the skeleton. `main.ts` calls `GET /api/health/` and writes the result into
  `#platform-status`. No context, event bus, API client, map or chat.
- **Backend, here:** of the endpoints the frontend needs, only `GET /api/health/` and the three chat endpoints
  exist. Clock, threats, fields and risks are not built, so a map has no data to show yet.
- **Data to develop against:** `python manage.py assistant_dev_seed` (Ola's, not the platform seed) fills a
  synthetic farm: the `Clock` row (default 2024-05-15), 5 fields, threats and toy risks with explanations.
- **Docs out of date:** the status table in interfaces.md still says the chat endpoints and `answer()` are
  "To build"; Ola built both in `assistant/`.

## The page and its modules

| Piece | Docs say | Here | Rolled back |
|-------|----------|------|-------------|
| Page | One Django template plus TypeScript bundled by esbuild into `static/frontend/dist/main.js`; hosts the map and the chat panel | Template with a title, `#platform-status` and a placeholder line | Header with navigation, layers sidebar, map, chat drawer, field card |
| `main.ts` | Creates the context, mounts chat + map, demo date control | Health check only | Creates the context, mounts everything; **no demo date control** |
| `AppContext` | `{ api, events, clock: { today, forecastDays } }` | None | Adds `shell`, `view`, `layers`; `clock.today` may be `null` |
| `api/` | Typed client; **types generated** by `openapi-typescript` from `/api/schema/` into `api/schema.d.ts` (one npm script) | None; no `openapi-typescript` in `package.json` | Client for every agreed GET endpoint and `POST /api/chat/`, but not `PUT /api/clock/`; types **written by hand** in `types.ts` |
| `events.ts` | Typed `EventBus` over a private `EventTarget` (code given in interfaces.md) | None | Same `EventBus`, plus a second `ShellBus` for UI events |
| `chat/` | Chat window | None | Chat drawer |
| `map/` | `initMap(container, ctx): void`, called once | None | `initMap(container, ctx): Promise<MapHandle>` (`reload`, `focusField`, `setClock`, `invalidate`) |
| Demo date control | In the header: `PUT /api/clock/`, then `main.ts` updates `ctx.clock` and sends `date:changed` | None | None: the date is only shown; nothing sends `PUT /api/clock/` or `date:changed` |
| Not in the agreed docs | — | — | *Moje uprawy* list, *Own data* upload (`localStorage`), local account dialog (`localStorage`), three base maps |

## Events between map and chat

| Event | Docs say | Here | Rolled back |
|-------|----------|------|-------------|
| `field:selected { fieldId \| null }` | Map sends it on a click (`null` for empty map); chat shows "Asking about: …" and sends `field_id` with the next message | None | Built both ways |
| `field:focus { fieldId }` | Chat sends it for `focus_field_id` or a clicked risk citation; map zooms, highlights, then sends `field:selected` | None | Built; *Moje uprawy* sends it too |
| `date:changed { today }` | `main.ts` sends it after the date control saved; map reloads | None | Map listens, but **nothing sends it** |
| `risks:updated { fieldIds }` | Chat sends it for `updated_field_ids`; map reloads those fields | None | Built; the map reloads every field's risks, not only the listed ones |

## Map (Kuba)

| Feature | Docs say | Here | Rolled back |
|---------|----------|------|-------------|
| Fields | `GET /api/fields/`, GeoJSON in EPSG:4326, coordinates **[lon, lat]** | None | Built (Leaflet) |
| Risk colouring | `GET /api/risks/?date=` for `ctx.clock.today` | None | Colour = highest score of the field; green < 0.33, amber < 0.66, red ≥ 0.66 (provisional) |
| Field details | `GET /api/fields/{id}/` | None | Field card: name, crop, area |
| Season chart | `GET /api/fields/{id}/risks/?from=&to=`; season so far (up to today) + coming days (today + 1 … today + 7) | None | Asks `to = today`, so the coming days never arrive although the chart draws them dashed |
| "Why" panel | `GET /api/fields/{id}/risks/{date}/` with `explanation` | None | That day's threats and scores; `explanation` not shown (format still open) |
| Legend | `GET /api/threats/`: names and categories | None | Fixed three-colour legend; `/api/threats/` never called |
| No own date checks | The API cuts everything at today + 7 | — | Relies on the API, as agreed |
| Never `new Date()` | The date is `ctx.clock.today` | — | Kept: without `/api/clock/` the date stays `null` and the map stays neutral |

## Chat in the browser

| Behaviour | Docs say | Here | Rolled back |
|-----------|----------|------|-------------|
| Sending | User's message appears at once, then a "thinking…" indicator, then the whole answer (no streaming) | None | Built ("Myślę…") |
| Markdown | Converted and sanitised with DOMPurify; never raw HTML | None | `DOMPurify.sanitize(marked.parse(...))` |
| `guide` citation | `document` + `page` | None | Shows "Źródło: {document}, s. {page}"; prints `s. undefined` for spreadsheet citations, which have no `page` |
| `risk` citation | Link; a click sends `field:focus` | None | Built |
| `focus_field_id`, `updated_field_ids` | → `field:focus`, → `risks:updated` | None | Built |
| Conversations | `GET /api/chat/conversations/` and `/{id}/` | None | Built (list and reopen) |
| Charts | Not in this version | — | — |

## Platform API the frontend uses

| Request | Docs say | Backend here |
|---------|----------|--------------|
| `GET /api/health/` | `{status, database}` | **Exists** (`core/views.py`); `503` when the database is down |
| `GET /api/clock/` | `{"today", "forecast_days": 7}` | Not built (the `Clock` model and `core.clock.today()` exist) |
| `PUT /api/clock/` | Body `{"today"}`, returns the GET shape | Not built |
| `GET /api/threats/` | Every threat with crop and category | Not built (`Threat` model exists) |
| `GET /api/fields/` | GeoJSON FeatureCollection | Not built (`Field` model exists) |
| `GET /api/fields/{id}/` | Details, crop history, soil | Not built |
| `GET /api/risks/?date=` | Every field's risks on one day | Not built (`Risk` model with `season_so_far()` / `coming_days()` exists; `predict()` doesn't, so the only rows are the dev seed's synthetic ones) |
| `GET /api/fields/{id}/risks/?from=&to=` | One field over time, `to` cut at today + 7 | Not built |
| `GET /api/fields/{id}/risks/{date}/` | One day with explanations; `400` after today + 7 | Not built |
| `POST /api/chat/` | Agreed request/response shape | **Exists** (`assistant/views.py`, Ola) |
| `GET /api/chat/conversations/`, `/{id}/` | `[{id, title, updated_at}]`, `{id, title, messages}` | **Exist** (`assistant/views.py`) |
| `GET /api/schema/`, `/api/docs/` | Schema for `openapi-typescript`, live docs | **Exist** (drf-spectacular) |

## General rules

| Rule | Docs say | State |
|------|----------|-------|
| No logins, no CSRF | The API is open | **Not done globally**: `REST_FRAMEWORK` keeps DRF's default authentication, so `PUT`/`POST` on new views needs a CSRF token in a browser that is logged in to `/admin/`. The chat views opt out on their own (`authentication_classes = []`) |
| Cut-off at today + 7 | Every date endpoint enforces it | Not built (none of the date endpoints exist) |
| Generated TypeScript types | From `/api/schema/` | Schema exists; generation not set up |
| Errors | `{"detail": "..."}` with 4xx | Chat follows it: `400` for an unknown `field_id`, `404` for an unknown `conversation_id` |

## What the chat sends beyond the agreed contract

Ola's [assistant/INTERFACE_PROPOSALS.md](INTERFACE_PROPOSALS.md) lists these as proposals; the
endpoint already behaves this way, so the chat window has to cope:

- **Guide citations carry extra keys:** `printed_page`, `section`, `ref` (the `[n]` marker in the text).
  Spreadsheet citations have `sheet` + `row` and **no `page`** (proposal 5).
- **`chart` and `pending_action`** (Vega-Lite chart, "save this observation?") are not in the HTTP response;
  they are stored in `Message.meta` only. The confirmation question is in the answer text (proposals 6, 7).
- **Observations** go into an interim `assistant.Observation` table. Without `predict()` the reassessment is
  reported as unavailable, so `updated_field_ids` stays empty (proposal 1).
- `ASSISTANT_LLM=fake` in `.env` gives deterministic answers without API keys, for frontend work.

## Still open

- Risk colour cut-offs: provisional 0.33 / 0.66, used by the assistant in `assistant/domain.py` (Bartek, Kuba).
- `Risk.explanation` format for the "why" panel (Bartek, Kuba, Ola).
- Whether Ola's proposals 5–7 (citation keys, `chart`, `pending_action`) enter the chat contract.
- Whether anything from the rolled-back frontend (sections, `ShellBus`, `MapHandle`, local account) is agreed
  and added to the docs.
