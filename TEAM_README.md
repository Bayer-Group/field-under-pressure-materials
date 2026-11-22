# Team Szalet — Field Under Pressure

**Track:** Disease & pest
**Event:** [Field Under Pressure](https://geo-hackathon.g.location360.ag/) · 20–22 Nov 2026

## Team
| Name | Role | Contact |
|------|------|---------|
| Jan | Platform, frontend | — |
| Szymek | Platform, frontend | — |
| Kuba | Map | — |
| Bartek | Decision engine | — |
| Ola | AI assistant | — |

## One-liner
**Cropilot**: for each wheat and maize field, which disease or pest threatens it today and in the next 7 days, why,
and what to do now (inspect, treat, wait), plus a chat assistant grounded in the official IOR guides.

## Problem & scope
- Focus area: winter wheat and maize, Opolskie, season 2023/24 replayed day by day.
- In scope: risk per field × threat × day with explanations, farm map, 7-day outlook, assistant with citations and
  farmer reports that update the risks.
- Out of scope: product and dose advice, yield prediction, live weather, other crops in the assistant.

## Data we use
- [x] Weather (daily, hourly, IMERG rain)
- [x] Satellite (Sentinel-2 NDVI)
- [x] Soil (ISRIC)
- [x] Cropland (CLMS 2020–2024)
- Notes: data stays outside git, in `DATA_DIR` (set in `cropilot/.env`).

## How to run
```bash
cd cropilot
cp .env.example .env        # LLM keys for the chat; the map works without them
./start.sh
python manage.py runserver  # http://localhost:8000
```

## Demo notes (Sunday)
- What to show: the farm map on 27 May 2024, a field's "why" panel, then a farmer's report in the chat turning a
  field red on the map ([script](cropilot/docs/demo-script.md)).
- Key result: every risk is explained by weather, growth stage, field history or the farmer's own report.
- Known limits: rule-based scores, not validated against field outcomes; simulated forecast.

## Links
- Repo: [github.com/Skerov-tazak/teamSzaletGeoHackaton](https://github.com/Skerov-tazak/teamSzaletGeoHackaton)
