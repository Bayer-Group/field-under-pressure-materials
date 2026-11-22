# TITLE

> [!IMPORTANT]
> ## ▶ Try the app: [`static_version/index.html`](static_version/index.html)
> **Judges, start here.** Clone or download this repo, then double-click **[`static_version/index.html`](static_version/index.html)**. It opens in any browser (Chrome, Firefox or Safari) with nothing to install: no Python, no npm, no data downloads, no API keys. If it won't work just double click `index.html` in file explorer (Finder on Mac) and it should open a browser. 

Hackathon project combining **bioinformatic** and **geoinformatic** data to support smarter, earlier decisions in agriculture.

## Quick start (judges)

1. `git clone` this repo (or *Code → Download ZIP* on GitHub and unzip it).
2. Open **[`static_version/index.html`](static_version/index.html)** in a browser.

If your browser refuses to open the local file, serve the folder instead:

```bash
python3 -m http.server -d static_version
```

Then open http://127.0.0.1:8000.

The static demo is a read-only snapshot of 5 plots (North Sterling, Colorado). All tabs work: greenness over time, soil microbes, soil characteristics, crop disease risk and the treatment plan. The data is built in; only the map background needs internet. For the full live app and the data pipeline, see [GUI](#gui) below.

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

## Running the pipeline yourself

You don't need this to try the app: the static demo has its data built in. If you do want to download and rebuild the data, read the two notes below first.

> [!IMPORTANT]
> **You need a NEON API token.** The NEON downloads (`scripts/02_fetch_neon.py`, and the NEON aerial photos in `scripts/09_fetch_aerial.py aop`) will not work without one. It is free: sign in at [data.neonscience.org](https://data.neonscience.org), then open *My Account* and choose *API token*. Copy `.env.example` to `.env` and paste the token after `NEON_API_TOKEN=`. `.env` is gitignored: never commit it or paste it anywhere. Every other source (NMDC, USDA soil, Daymet, satellite imagery, the knowledge bases) needs no key.

> [!NOTE]
> **Light mode is on by default**, so you don't start an hours-long full download by accident. A fresh clone downloads and builds only the 5 STER plots that are in the static demo (STER_006, 010, 011, 012, 016). To get every plot at both sites (STER and KONA), run `scripts/00_light_mode.py off` **before** downloading. That takes a long time and several GB.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
cp .env.example .env                                # then paste your NEON API token into it
.venv/bin/python scripts/00_light_mode.py           # check: "light mode is ON ... 5 plots"
```

What light mode changes:

- Only the light-mode plots are downloaded and processed. KONA is skipped entirely. The NMDC download drops from 729 MB to 239 MB (measured with `--dry-run`).
- NEON serves whole sites, so `02_fetch_neon.py` still asks for all of STER but keeps only the light-mode plots' rows. The soil polygons (`04_build_fields.py`) cover the whole STER window, and that step still needs the 3.76 GB NASS crop boundary zip that you download by hand (see [`AGENT.md`](AGENT.md), 3.6).
- `scripts/00_light_mode.py off` switches to all plots; `scripts/00_light_mode.py on [PLOT ...]` switches back (to the default plots, or your own list). The setting lives in `data/light_mode.txt`; deleting that file also goes back to the defaults. Switching never deletes data; re-run the steps to rebuild.

The order of the pipeline steps and what each one downloads are in [`AGENT.md`](AGENT.md) (section 0). A full end-to-end run in light mode has not been timed.

## GUI

A small local web app for looking at the data: a map of the plots, and for each plot one timeline with its greenness over time, its sampling visits and its aerial photos. The timeline chooses what is laid over the map: an aerial photo, or the satellite greenness map (1 km around the plot) of any day. A second tab, *Soil microbes*, shows what lives in the plot's soil for a chosen year and sampling day: bacteria and archaea (NMDC metagenomes) or fungi (NEON ITS), grouped by phylum, class or genus. It needs the tables from `scripts/02b_build_neon_features.py` and `scripts/05_build_biology.py`. It runs on your machine only.

The *Crop disease risk* tab shows, for each plot and year, each crop's rank among the site's other plots (same year and ITS method), split into the part from genera found in the plot and the part from genera not found (counted at their mid-rank). It also lists the genera behind each crop's score, the genera that could not be scored, and the caveats. It needs the knowledge base (`scripts/14_build_kb.py`, downloads about 1 MB + 179 MB once) and `its_core_genus.parquet` (`scripts/02b_build_neon_features.py`). The first view of a site-year takes about 2.5 s (computed on demand, then cached). The score is a relative index, not a probability of disease.

The *Soil microbes* tab has a Roles | Taxonomy switch and opens on Roles. Roles shows the sample's reads by role (useful, potentially harmful, nitrogen cyclers and so on), and genus names show a short description on hover. The *Soil functions* tab shows which named genera may carry each gene-backed function. The roles are AI-annotated at genus level; see [`AGENT.md`](AGENT.md) (sections 3.14 and 5) for the caveats.

The *Treatment plan* tab lists, for a plot, year and crop, the product types worth considering before planting and during growth (seed treatments, foliar fungicides, biologicals, fertilisers, nitrogen stabilisers, inoculants, lime), each with the soil finding behind it and the test that would confirm it. It draws on the crop disease risk, the soil measurements and bacterial genes of the same year, the crop history and the site. The product list (`rules/products.csv`) is not verified: it names product classes, not brands or rates.

```bash
cd web && npm install && npm run build      # once, and after changing anything in web/
.venv/bin/python scripts/13_fetch_ndvi_maps.py   # once: greenness maps (network, about 300 MB); optional
.venv/bin/python scripts/12_gui.py          # then open http://127.0.0.1:8000
```

`bash scripts/bake_static.sh` regenerates `static_version/` after data or frontend changes.

- `src/cropfit/api.py`: the local JSON API over `data/processed/` (new backend results get a route here); `api_microbiome.py` holds the soil microbes routes (plot → samples, sample → composition by phylum, class or genus).
- `web/src/api.ts`: the typed client; `web/src/features/<name>/`: one folder per part of the screen.
- `src/cropfit/api_risk.py`: the crop risk routes (plot → units, unit → crop ranks, crop → genera behind the score); `web/src/features/risk/`: the *Crop disease risk* tab.
- `src/cropfit/products.py` and `rules/products.csv`: the product rules; `web/src/features/plan/`: the *Treatment plan* tab.
- Frontend development: run `scripts/12_gui.py` and, in `web/`, `npm run dev` (it forwards `/api` to port 8000).

## Status

Open for exploration – approach, tools and models are intentionally undecided.
