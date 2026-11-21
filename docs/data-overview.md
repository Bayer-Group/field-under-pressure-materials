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

### Code ready, not yet run on this checkout

| Layer | Script | Needs | Output |
|---|---|---|---|
| Soil map (SSURGO), weather (Daymet), crop history 2008-2021 (CDL) for the 44 plots | `scripts/03_build_plots.py` | network only, keyless, minutes | `plots`, `plot_crop_history`, `plot_climate_yearly` |
| Field polygons with crops 2018-2025 (CSB) + soil + weather for ~4,850 fields | `scripts/04_build_fields.py` | the 3.76 GB CSB zip in `data/raw/csb/` (manual download) | `fields`, `plot_csb` |
| EU cross-check: LUCAS fungi vs land-cover history | `scripts/e1_match.py` | JRC LUCAS zip in `data/raw/lucas/` | `outputs/e1/` |

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
2. **Run the geo side:** `.venv/bin/python scripts/03_build_plots.py`; add `04_build_fields.py` once the CSB zip is in place.
3. **Write one integration step** (e.g. `scripts/07_build_unit_year.py` -> `unit_year.parquet`), the missing piece today. One row per plot and year, every source joined there and nowhere else:
   - an explicit date and source column per layer (`its_date`, `metagenome_date`, `chem_date`, `crop_source`), so a 2024 fungal sample is never shown as if it belonged to a 2017 metagenome (today the "latest per plot" tables differ by 5-7 years on 11 of 28 plots);
   - crop history merged from CDL and CSB;
   - depth, QC and pipeline flags carried along (`ko_depth_ok`, `n_fungal_cores_ok`, ITS `product`).
4. **Compute scores in the app layer, not in the processed tables.** Percentiles, risk flags and status labels belong next to the question they answer, each stating its reference group (site, year, pipeline). Treat the existing `bio_*_pct_*` columns as a starting point, not as comparable numbers (they use three different reference groups).
5. **App reads `unit_year` (+ `fields` for the map)** with pandas or DuckDB. Carry the caveats of AGENT.md section 5 into the UI: relative abundance only, "not detected" never "absent", "insufficient depth" shown as such.

**Suggested first version:** a plot page for STER and KONA with a timeline of crops, pathogen and beneficial fungal shares, N-cycle genes (where deep enough), chemistry and weather, each with a confidence label; then a field map coloured by soil, climate and rotation indicators.

**Known gaps to keep in mind:** "cropland" is selected by 2001 land-cover labels (plots that became cropland later are missing); NEON pulls use the current release, so rebuilds can drift; `metagenome_key` changes if NMDC reprocesses; the site list lives in four places (`neon.SITES`, `csb.SITES`, `config/regions.yaml`, the NMDC pull's `--sites`).
