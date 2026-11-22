# Map

**Owner:** Kuba

The interactive map of the farm: fields, their crops, their risk per threat, how that risk changes over the season, and the details of a selected field.

## What the rest of the page expects

**One function, `initMap()`,** exported from `frontend/src/map/index.ts`. `main.ts` calls it once. Details: [docs/interfaces.md → Frontend modules](../../../docs/interfaces.md#frontend-modules).

```ts
export function initMap(container: HTMLElement, ctx: AppContext): void;
// ctx.api     typed calls to the platform API
// ctx.events  the event bus shared with the chat
// ctx.clock   { today, forecastDays }: the demo's date, never new Date()
```

The map draws itself inside `container` and talks to the rest of the page only through `ctx`.

**Events** ([docs/interfaces.md → Events](../../../docs/interfaces.md#events-between-map-and-chat)):

| You send | When |
|----------|------|
| `field:selected` `{ fieldId }` | the user clicks a field; `{ fieldId: null }` when they click empty map |

| You handle | What to do |
|------------|------------|
| `field:focus` `{ fieldId }` | zoom to and highlight the field, then send `field:selected` for it |
| `date:changed` `{ today }` | reload the risks for the new date (`ctx.clock` is already updated) |
| `risks:updated` `{ fieldIds }` | reload those fields' risks |

**Data** ([docs/interfaces.md → Platform API](../../../docs/interfaces.md#platform-api), example responses included):

- `GET /api/fields/`: every field as GeoJSON (EPSG:4326, coordinates **[lon, lat]**), with name, crop and area;
- `GET /api/risks/?date=`: every field's risk per threat on one day, for colouring;
- `GET /api/fields/{id}/`, `/risks/?from=&to=`, `/risks/{date}/`: details, the season chart and the "why" panel;
- `GET /api/threats/`: names and categories for the legend.

Risk scores are 0–1. "Season so far" is up to today; "coming days" are today + 1 … today + 7. The API never returns anything later ([why and how](../../../docs/interfaces.md#no-data-after-the-forecast)), so you don't need your own checks; to see later days, the demo date has to move.

## Building

- **Plain TypeScript, no framework.** Map libraries (Leaflet, MapLibre, …) are fine: install them with `npm install` in [`frontend/`](../../), and esbuild bundles them into `static/frontend/dist/main.js`.
- **API types are generated** from the backend's schema, so they always match it; don't write them by hand.
- **Colours and the "why" panel** come from `explanation` version 1 ([database.md → Explanation, version 1](../../../docs/database.md#explanation-version-1)): `level` for the colour (`low` / `medium` / `high`, cut-offs 0.33 / 0.66, agreed), `summary`, the `drivers` sorted by `effect` (their `label`), `action.text` and, for `treat`, `action.spray_window.date`, `growth_stage.name` and `confidence`. Ignore keys you don't know.
- The explanation texts are Polish (engine v0.11), shown as they are.

## Development

Team notes (what is built, how to run it, what each of us still has to do): [docs/archive/map-and-engine-notes.md](../../../docs/archive/map-and-engine-notes.md).

The module above is built: [`index.ts`](index.ts) (`initMap`), [`panel.ts`](panel.ts) (field panel and "why"),
[`chart.ts`](chart.ts) (season chart), [`map.css`](map.css). It follows this README and interfaces.md exactly;
outside `map/` it uses [`../events.ts`](../events.ts) (the `EventBus` of interfaces.md) and the generated API
types through [`contract.ts`](contract.ts).

**In the page:** `cd frontend && npm run build`, then `python manage.py runserver`: `main.ts` mounts the map next to
the chat with the real platform API (`core/views.py`), on the demo scenario (`python manage.py scenario switch
demo_2024`) or, without the datasets, on the assistant's synthetic farm (`python manage.py assistant_dev_seed`).
(The stand-in page and mock API used before the platform API existed were removed on 22 Nov.)

**Contract details the module keeps:**

- From `explanation` it reads exactly the map's keys (database.md → "Who reads what"): `level`, `summary`,
  `drivers` (`label`, `effect`; sorted by `effect`, `null` = context), `action` (`type`, `text`,
  `spray_window.date`), `growth_stage.name`, `confidence`. Threat names come from the API's `threat.name`.
- Every rule of `map.css` is scoped under `.fup-map`; the layout uses container queries (the map's own width).
- Responses that arrive after the day or the demo date changed are dropped; a season series is cached per today.
- `ctx.clock` is read at each use; a `field:focus` that arrives before the fields are drawn is applied after.
- Closing the field panel also sends `field:selected { fieldId: null }` (no field selected any more).

**Wired to the platform (21 Nov, merge of `feat/map`):**

- **Types:** [`contract.ts`](contract.ts) re-exports the generated API types (`api/types.ts`, from `api/schema.d.ts`).
  Only the explanation is typed there, since the schema passes it through untyped; `readExplanations()` reads each
  one as version 1 and, for rows that lack a key (the assistant's dev seed has no `level`), takes the level from the
  score with the agreed cut-offs, as the API does.
- **`ctx.api`:** `api/client.ts` has the six calls of `MapApi` under the same names; `main.ts` passes its full
  `AppContext`, of which `contract.ts`'s `AppContext` is the part the map uses.
- **`level` in `/api/risks/?date=`** (decision 10) is always sent; the map uses it.
