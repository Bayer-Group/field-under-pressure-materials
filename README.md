# TITLE

Hackathon project combining **bioinformatic** and **geoinformatic** data to support smarter, earlier decisions in agriculture.

## Goal

Understand how the living soil and its environment relate, and use that to predict risks and guide action in the field.

## Data

- **Bioinformatic** – metagenomic sequencing of soil: which microbial populations are present at a site, and how they change over time (year after year).
- **Geoinformatic** – environmental variables: soil pH, humidity, weather, etc.

## Idea

Combine the two data sources to:

- predict potential plant/soil diseases
- adjust fertilization
- inform spraying and other treatments
- advising in crop rotations
- (and anything else the data supports)


## Data guide

What data is available, what it is for and how to build on it: [`docs/data-overview.md`](docs/data-overview.md). How to download, process and use each dataset (NMDC, NEON, SSURGO, Daymet, CDL, CSB, LUCAS): see [`AGENT.md`](AGENT.md).

## GUI

A small local web app for looking at the data: a map of the plots, and for each plot one timeline with its greenness over time, its sampling visits and its aerial photos. The timeline chooses what is laid over the map: an aerial photo, or the satellite greenness map (1 km around the plot) of any day. It runs on your machine only.

```bash
cd web && npm install && npm run build      # once, and after changing anything in web/
.venv/bin/python scripts/13_fetch_ndvi_maps.py   # once: greenness maps (network, about 300 MB); optional
.venv/bin/python scripts/12_gui.py          # then open http://127.0.0.1:8000
```

- `src/cropfit/api.py`: the local JSON API over `data/processed/` (new backend results get a route here).
- `web/src/api.ts`: the typed client; `web/src/features/<name>/`: one folder per part of the screen.
- Frontend development: run `scripts/12_gui.py` and, in `web/`, `npm run dev` (it forwards `/api` to port 8000).

## Status

Open for exploration – approach, tools and models are intentionally undecided.
