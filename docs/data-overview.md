# Data overview: what we have, what it is for, how to build on it

Short orientation for the team. Details per dataset (download, columns, pitfalls) are in [`AGENT.md`](../AGENT.md); column meanings in [`feature_contract.md`](feature_contract.md). State as of 21 Nov 2026, branch `feature/its-002-port`.

## 1. What is available

Two NEON farm sites: **STER** (North Sterling, CO, dryland) and **KONA** (Konza, KS).

### Built and on disk (`data/processed/`)

| Layer | Tables | Unit | Coverage |
|---|---|---|---|
| Soil bacteria and gene functions (NMDC) | `metagenomes`, `ko_panel`, `ko_counts_all`, `taxa_genus`, `plot_biology*` | metagenome (composite of up to 3 soil cores) | 59 metagenomes, 26 plots; STER 2013-2022, KONA 2017/2019. **Only 10 are deep enough for gene profiles** (8 of them STER 2022) |
| Soil fungi (NEON ITS) | `its_core_genus`, `its_genus`, `plot_its*` | core, plot-date | 506 cores, 149 plot-dates, 26 plots, 2016-2024; two NEON pipelines (.001 / .002) that are not directly comparable |
| Soil chemistry (NEON) | `neon_chem` | plot-date | 29 plots, 2013-2026: organic C, N, C:N, pH, moisture |
| Microbial abundance (NEON qPCR) | `neon_qpcr` | plot-date | 128 plot-dates, 2013-2017; copies per ng DNA, not per gram soil |
| **Joined biology** | `joined_metagenomes` (59 x 72), `joined_fungi_genus` | metagenome | bacteria + genes + chemistry + fungi from exactly the pooled cores; 32 metagenomes have fungi |

### Geo data, linked to each sampling event (built)

721 sampling events on 29 plots, 175 with biology. Each dataset below is attached to every event with an explicit time window and the date actually used (`event_features`, `event_table`; AGENT.md 3.9).

| Layer | Tables | Coverage of the 175 biology events |
|---|---|---|
| Soil map, terrain, climate normals | `plots`, `plot_terrain` | all |
| Weather before sampling (7, 30, 90 days) | `plot_weather_daily` | all |
| Satellite greenness (Sentinel-2, Landsat), 2013-2026 | `plot_vi_timeseries`, `plot_season` | 97% have a clear image within 6 days; season summaries for all |
| Aerial photos (NAIP; NEON airborne camera) | `plot_aerial`, chips in `data/raw/imagery/` | NAIP within 200 days: 44% (flights every 2 years) |
| Farm management and crop sown/harvested, 2013-2026 | `neon_management_events`, `neon_crop_reported` | 97% have a reported operation in the year before |
| Crop map 2008-2021 | `plot_crop_history` | sampling year: 66% (ends 2021) |
| Nitrate, ammonium, N turnover | `neon_inorganic_n` | 64% |
| Ground survey of plant cover | `neon_plant_cover` | 70% within 120 days |
| Soil pit (texture, CEC), once | `neon_soil_baseline` | 62% |

To look at all of it: `.venv/bin/python scripts/10_inspect_data.py`, then open `outputs/inspect/index.html`.

### Not built

| Layer | Script | Needs |
|---|---|---|
| Field polygons with crops 2018-2025 (CSB) + soil + weather for ~4,850 fields | `scripts/04_build_fields.py` | the 3.76 GB CSB zip in `data/raw/csb/` (manual download) |
| EU cross-check: LUCAS fungi vs land-cover history | `scripts/e1_match.py` | JRC LUCAS zip in `data/raw/lucas/` |

## 2. What the data is useful for

| Project goal | Signals we have | How far it carries |
|---|---|---|
| **Disease risk** | ITS shares of pathogen genera (Fusarium, Macrophomina, Rhizoctonia complex, Gaeumannomyces, Sclerotinia, Pythium); crop history (host continuity); weather (wet May, heat) | Genus level only (cannot split pathogenic from benign species), relative shares, oomycetes under-captured. Good for "elevated vs. typical for this site", not for absolute risk |
| **Fertilisation** | N-cycle gene potential (nitrification, denitrification, nosZ, urease), P mobilisation; NEON C, N, C:N, pH; SSURGO organic matter and water capacity | Gene potential is not activity, and only 10 metagenomes are deep enough. nifH is not detectable in any sample. Chemistry and soil map are the solid part |
| **Spraying / biocontrol** | Trichoderma, mycorrhizal genera (Glomus, Rhizophagus, Funneliformis); Pseudomonas, Bacillus, Streptomyces shares; acdS, chitinase, hcnA genes | Indicative only; phlD not detected |
| **Crop rotation** | Per-plot crop sequence (CDL 2008-2021, CSB 2018-2025) next to fungal shares over time | Lets you show e.g. take-all fungi under repeated wheat; few plots and years, so descriptive |
| **Context for any of the above** | Daymet climate indicators, SSURGO soil properties, also for every field (no biology at field level) | Solid, national coverage; code works for any US point |

**Honest bound:** 2 sites, 26 plots with biology. That supports an exploratory, explain-what-we-see app, not a trained predictive model. The LUCAS table (373 EU cropland points) is the only dataset large enough to fit a cross-site relationship (e.g. fungi vs. pH, C, crop history).

## 3. How to proceed with implementation

1. **Fix the app question and the unit.** Recommended unit: **plot x year** (biology, chemistry, crops and weather all exist per year). Fields are a second, biology-free layer for the map.
2. **Geo side: done for the plots** (see section 1). Add `04_build_fields.py` once the CSB zip is in place if the field map is wanted.
3. **Integration step: done at event level.** `event_table.parquet` has one row per sampling event with biology and every linked dataset, each with the date used and its distance in time. If the app wants plot x year instead, aggregate from `event_features`.
4. **Compute scores in the app layer, not in the processed tables.** Percentiles, risk flags and status labels belong next to the question they answer, each stating its reference group (site, year, pipeline). Treat the existing `bio_*_pct_*` columns as a starting point, not as comparable numbers (they use three different reference groups).
5. **App reads `unit_year` (+ `fields` for the map)** with pandas or DuckDB. Carry the caveats of AGENT.md section 5 into the UI: relative abundance only, "not detected" never "absent", "insufficient depth" shown as such.

**Suggested first version:** a plot page for STER and KONA with a timeline of crops, pathogen and beneficial fungal shares, N-cycle genes (where deep enough), chemistry and weather, each with a confidence label; then a field map coloured by soil, climate and rotation indicators.

**Known gaps to keep in mind:** "cropland" is selected by 2001 land-cover labels (plots that became cropland later are missing); NEON pulls use the current release, so rebuilds can drift; `metagenome_key` changes if NMDC reprocesses; the site list lives in four places (`neon.SITES`, `csb.SITES`, `config/regions.yaml`, the NMDC pull's `--sites`).
