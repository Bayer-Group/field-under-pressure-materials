# AGENT.md: data guide (download, process, use)

A practical guide for humans and coding agents working on any prototype in this repo. It covers the **data side only**: how to download each dataset, where it lands, which code processes it, what the processed tables contain, how datasets join, and what to watch out for. It deliberately says nothing about any particular app or scoring logic.

The code was written for a first prototype ("Crop Fit", branch `crop-fit`) around two NEON farm sites, **STER** (North Sterling, Colorado, dryland) and **KONA** (Konza, Kansas). Everything below is reusable for other sites or points, except where noted.

Figures marked "measured" were observed on 21 Nov 2026 on an 8-core, 16 GB laptop. Anything marked "not verified" was not re-checked.

Related: `docs/nmdc-data-guide.md` (how to interpret the NMDC files and how STER and KONA differ; written before the dedupe change, so its folder layout block is out of date, see the NMDC section below) and `docs/feature_contract.md` (column dictionary for the per-unit feature tables).

---

## 0. Setup

```bash
uv venv --python 3.12 .venv            # geo wheels are risky on newer system Pythons
uv pip install --python .venv/bin/python -e .
.venv/bin/python -m pytest -q          # 142 tests, no network, no data needed
```

The package is `cropfit` in `src/cropfit/` (the name is historical). Scripts add `src/` to `sys.path` themselves; run them from the repo root: `.venv/bin/python scripts/<name>.py`. `e1_match.py` and `pull_nmdc_cropland.py` use paths relative to the current directory, so run them from the repo root.

| Module | Purpose |
|---|---|
| `config.py` | Paths (`DATA`, `RAW`, `PROCESSED`, `CACHE`, `RULES`, `RESOURCES`), window bbox helpers from `config/regions.yaml`. Importing it creates `data/raw`, `data/processed`, `data/cache` and `outputs/figures`. |
| `http.py` | Shared `requests` session with a **User-Agent** (required by NMDC and NEON), retries with backoff on 429/5xx, and a JSON/text disk cache under `data/cache/<namespace>/`. |
| `nmdc.py` | Sample-name regex, `samples.csv` loader, KO / Kraken2 / GOTTCHA2 parsers, KO panel, depth gate. |
| `neon.py` | NEON portal pulls (neonutilities), ITS per-sample files, ITS / chemistry / qPCR processing. |
| `ssurgo.py` | Soil Data Access (SDA): point to mukey, mukey to properties, AWC. |
| `fields.py` | Window-level SSURGO polygons and field-by-polygon overlay. |
| `daymet.py` | Single-pixel Daymet fetch and derived agro-climate indicators. |
| `cdl.py` | CDL crop history per point from Planetary Computer. |
| `csb.py` | NASS Crop Sequence Boundaries clipped to a window. |
| `events.py` | Sampling-event registry (the anchor all geo data is linked to), plot footprints, core positions. |
| `stac.py` | Shared raster access: Planetary Computer catalogue, area-weighted footprint reads, chips, fetch manifests. |
| `satellite.py` | Sentinel-2 / Landsat observations per plot, vegetation indices, season metrics. |
| `aerial.py` | Aerial photo chips and in-plot statistics: NAIP and the NEON airborne camera. |
| `terrain.py` | Elevation, slope, aspect, relative position from the 3DEP 10 m elevation model. |
| `link.py` | Temporal operators that attach every dataset to the sampling events (see 3.9). |
| `assoc.py` | Association scan between microbiome and environmental columns (any shape, within site x year; see 3.10). |
| `e1.py` | Open-Meteo / NASA POWER climate for EU points, plus modelling helpers used by the LUCAS experiment (needs scikit-learn). |
| `kb.py` | FungalTraits and USDA Fungus-Host downloads, name normalisation, genus x crop host table (see 3.12). |
| `risk.py` | Crop risk index per plot-unit x crop (see 3.12). |
| `followup.py` | Follow-up test suggestions per plot-unit x crop from the risk result and `rules/followup_tests.csv` (see 3.13). |
| `api_risk.py` | GUI endpoints for the crop risk index (`/api/plots/{id}/crop-risk[/{unit}[/{crop}]]`), computed on demand from `risk.py` |
| `microbe_roles.py` | Microbe roles (3.14): ontology, genus role annotations and hover descriptions; per-sample roll-up into role classes. Used by the Soil microbes "Roles" view and the Soil functions tab. |

Lookup tables in `rules/` (generic, read by the code): `cdl_codes.csv` (all 132 CDL codes to a crop-group vocabulary), `ko_panel.csv` (KEGG KOs of interest with function group and caveat), `lucas_lc1_groups.csv` (LUCAS land-cover codes with `is_cereal`; documentation only, `e1_match.py` hard-codes its own cereal rule B11-B19), `genus_synonyms.csv` (alias -> canonical genus: Rhizoctonia/Thanatephorus/Ceratobasidium -> Rhizoctonia_complex, Gibberella -> Fusarium) and `crop_host_taxa.csv` (USDA host taxon -> crop_group). Microbe roles (3.14): `microbe_ontology.csv` (32 role terms in a tree under useful / harmful / context (nitrogen cyclers) / background / unknown, with `ko_group` linking to `ko_panel.csv` function groups), `microbe_annotations.csv` (genus -> role rows with confidence, evidence, source and species examples), `microbe_genera.csv` (a plain-language description of at most two sentences per genus, shown on hover) and `microbe_annotation_prompt.md` (instructions for the annotator agents). Small input tables in `resources/` are listed under each dataset.

### Where things land (all gitignored except `resources/`, `rules/`, `config/`)

```
data/nmdc/            samples.csv, data_objects.csv, objects/<data_object_id>/{ko.tsv,kraken2_report.tsv,...}
data/raw/neon/<DPID>/ NEON tables as parquet
data/raw/csb/         NationalCSB_2018-2025_rev23.zip (you place it here)
data/raw/lucas/       lucas_harmo_uf.zip and a slimmed CSV (you create it)
data/cache/<ns>/      http.cached() JSON/text: sda/, daymet/, openmeteo_e1/, power_e1/
data/raw/satellite/   one small parquet per satellite scene (resumable) + manifest
data/raw/imagery/     aerial chips (GeoTIFF) and previews (PNG) per source and plot + manifest
data/raw/kb/           fungaltraits/ and usda_fungus_host/, each with a manifest.json (see 3.12)
data/processed/       parquet outputs of scripts 01-09
```

Pipeline order (what produces what):

| Step | Command | Output |
|---|---|---|
| Light mode (**on by default**; `off` for all plots) | `scripts/00_light_mode.py [on\|off]` | `data/light_mode.txt` (see below) |
| NMDC download | `scripts/pull_nmdc_cropland.py` | `data/nmdc/` |
| NEON download | `scripts/02_fetch_neon.py` (needs token) | `data/raw/neon/` |
| NEON tables | `scripts/02b_build_neon_features.py` (offline) | `its_core_genus`, `its_genus`, `its_genus_lineage`, `plot_its*`, `neon_metagenome_pooling`, `neon_chem`, `neon_qpcr` |
| Event registry | `scripts/01_build_events.py` (offline, after 02b and 05) | `events`, `plot_geometry`, `event_cores` (see 3.9) |
| Plot tables | `scripts/03_build_plots.py` (after 01) | `plots`, `plot_crop_history`, `plot_climate_yearly`, `plot_weather_daily` |
| Field tables | `scripts/04_build_fields.py` (needs CSB zip) | `fields`, `plot_csb`, `csb_raw_<site>` |
| NMDC tables | `scripts/05_build_biology.py` (offline) | `metagenomes`, `ko_*`, `taxa_genus`, `taxa_lineage`, `plot_biology*` |
| Satellite | `scripts/08_fetch_satellite.py` (after 01) | `plot_vi_timeseries`, `plot_season` |
| Aerial photos | `scripts/09_fetch_aerial.py [naip] [aop]` (after 01; `aop` needs token) | `plot_aerial`, chips under `data/raw/imagery/` |
| Greenness maps (for the GUI) | `scripts/13_fetch_ndvi_maps.py` (after 08; network, resumable) | `plot_ndvi_maps`, Sentinel-2 NDVI chips (10 m, 1 km around each plot, one per clear date) under `data/raw/imagery/s2_ndvi/` |
| Event features | `scripts/07_build_event_features.py` (offline, last) | `event_features`, `event_table` (see 3.9) |
| Association scan | `scripts/11_association_scan.py` (offline, after 07, under a minute) | `association_scan` (see 3.10) |
| Knowledge base | `scripts/14_build_kb.py [--refresh]` (downloads ~1 MB + ~179 MB once) | `kb_fungaltraits_genus`, `kb_genus_crop_host`, `kb_usda_species_crop`, `kb_meta.json` |
| Crop risk | `scripts/15_crop_risk.py --site STER --year 2022` (offline, after 02b and 14) | `crop_risk_<SITE>_<YEAR>_{summary,contributions,skipped}.parquet` + `.json` |
| Inspector | `scripts/10_inspect_data.py [--standalone]` (offline) | `outputs/inspect/index.html`, a developer page to look at all of the above |
| Joined table | `scripts/06_build_joined.py` (offline, after 02b and 05) | `joined_metagenomes`, `joined_fungi_genus` (see 3.8) |
| Fungal guilds (for the GUI's soil characteristics tab) | `scripts/16_fetch_funguild.py` (network once, ~7.5 MB, keyless; cached under `data/raw/kb/funguild/`) | `fungal_guilds` (FUNGuild role per fungal genus: primary guild, category, can be plant pathogen, can parasitise fungi, confidence) |
| Microbe roles: export | `scripts/17_export_microbe_taxa.py` (offline, after 02b and 05) | `data/processed/microbe_taxa.csv` (2,358 genera: 1,095 bacteria, 96 archaea, 1,167 fungi) |
| Microbe roles: annotation | Manual step: LLM agents write the chunks by hand, following `rules/microbe_annotation_prompt.md` (no script) | `data/annotation_chunks/` (gitignored) |
| Microbe roles: merge | `scripts/18_merge_microbe_annotations.py` (offline, after the chunks exist) | Validates the chunks and `review_*` overrides, merges them into `rules/microbe_annotations.csv` and `rules/microbe_genera.csv`, prints coverage and the blind agreement with FUNGuild (saved to `data/processed/microbe_roles_agreement_blind.csv`) |
| KEGG modules | `scripts/19_build_kegg_modules.py` (network once for KEGG REST, cached; then offline, after 05) | `kegg_modules`, `kegg_module_completeness` (see 3.16) |
| Who carries which function | `scripts/20_build_gene_taxa.py` (offline; needs the NMDC gene phylogeny files, see 3.16) | `ko_taxa` (see 3.16) |

Note: `03_build_plots.py` takes its plots from the event registry (the 29 plots that were actually sampled). `04_build_fields.py` still carries the two windows of `config/regions.yaml`. The site list is defined once, as the keys of `windows` in `config/regions.yaml` (`config.sites()`); only the standalone NMDC pull script has its own `--sites` default.

### Light mode: download only a few plots

Light mode is **on by default**: a fresh clone (no `data/light_mode.txt`) downloads and builds only the default plots, so nobody starts an hours-long full download by accident. To get every plot, switch it off **before** downloading, then run the pipeline as usual:

```bash
.venv/bin/python scripts/00_light_mode.py on        # default plots: STER_006, STER_010, STER_011, STER_012, STER_016
.venv/bin/python scripts/00_light_mode.py on STER_006 "STER 010"   # or your own list
.venv/bin/python scripts/00_light_mode.py           # status
.venv/bin/python scripts/00_light_mode.py off
```

- State is in `data/light_mode.txt` (editable by hand): **missing** means on with the default list (`light_plots` in `config/regions.yaml`); a line **`off`** means off (all plots); otherwise it lists the plots, one per line (`STER_006` or `STER 006`). A file with neither falls back to the default list. `config.light_plots()` reads it (via `config.read_light_file()`; `api_risk.py` and the standalone `pull_nmdc_cropland.py` follow the same rules), `config.light_filter(df)` drops the rows of other plots (rows that name no plot, such as site-level lab rows, are kept), and `config.sites()` returns only the sites of those plots (STER for the default list), so KONA is not fetched at all.
- Where it applies: `pull_nmdc_cropland.py` pulls only those plots' biosamples (measured with `--dry-run`: 39 biosamples, 60 files, 239 MB, against 295 files and 729 MB for the full pull; `--plots` overrides the list, `--all-plots` ignores light mode); `02_fetch_neon.py` still downloads whole sites (NEON serves sites, not plots) but saves only those plots' rows, so the ITS per-sample files are fetched for them only; `nmdc.load_samples()`, the event registry (`01_build_events.py`) and `satellite.load_observations()` keep only those plots. Every geo step (03, 08, 09, 13) reads `plot_geometry`, so it follows. `04_build_fields.py` builds the STER window only; the window itself (SSURGO polygons, CSB) is not reduced to the plots.
- Switching does not delete anything: processed tables are replaced when their step is re-run, and cached satellite scenes of other plots stay on disk but are ignored. Switch it off (`00_light_mode.py off`) and re-run the steps to get all plots back. Not verified: a full pipeline run end to end in light mode (the filters were checked on the existing raw NEON, NMDC and satellite data on 21 Nov 2026).

---

## 1. Keys, secrets and what never goes into git

- **Only one key is needed: the NEON API token.** Put it in a gitignored `.env` as `NEON_API_TOKEN=...` (template: `.env.example`; `NEON_TOKEN` is accepted as a fallback name). Since June 2026 the NEON portal calls in this repo need it. Never paste it in chat, logs or commits. `neon.get_token()` loads it via python-dotenv.
- **Everything else is keyless:** NMDC, SSURGO/SDA, Daymet, Planetary Computer CDL (anonymous signed URLs via the `planetary-computer` package), CSB and CDL downloads from USDA, NASS, JRC LUCAS, GlobalFungi table, Open-Meteo, NASA POWER.
- **Knowledge bases (3.11):** FungalTraits and USDA Fungus-Host (3.12) are keyless. The EPPO API needs a free token, and an NCBI API key is optional (higher rate limit). If you add them, use the same gitignored `.env` (for example `EPPO_API_TOKEN`, `NCBI_API_KEY`).
- **Never commit** `.env`, anything under `data/`, or `data/links.txt`. The latter (if you have it from the hackathon organisers) holds pre-signed S3 URLs with session tokens. `.gitignore` covers `data/`, `.env`, `*.zip`, `.venv/`, `outputs/`, `*.part`.
- **User-Agent:** NMDC rejects some default client user agents and NEON asks for one. `http.py` sets one for all calls; `pull_nmdc_cropland.py` sets its own. If you write new code, set a UA.

## 2. Disk and compute

- A laptop is enough. No server needed for anything here.
- Disk, measured: NMDC objects 729 MB (default types), CSB zip 3.76 GB, LUCAS harmonised zip 128 MB (plus a 128 MB slim CSV if you create it), `data/cache` about 110 MB, NEON raw parquet 1.5 MB, processed parquet 8.5 MB.
- **Peak is about 12 GB if you unzip CSB** (5.7 GB unzipped plus the 3.76 GB zip). You do not need to unzip: `csb.py` reads straight from the zip via `/vsizip/`. Delete the zip after clipping if disk is tight (the clipped parquet files are about 3 MB).
- Compute: all processing steps run in seconds to minutes. The slow parts are network: SDA window queries (about 4 minutes each when cold), CDL windowed reads (about 14 s per point for 14 years, measured), CSB bbox read from the zip (about 17 s for a 3 km box, measured).

---

## 3. Datasets

### 3.1 NMDC: NEON soil metagenomes

- **What:** National Microbiome Data Collaborative processing of NEON soil metagenomes (study `nmdc:sty-11-34xj1150`, NEON product DP1.10107.001). Per metagenome: Kraken2 and GOTTCHA2 read-based taxonomy (Centrifuge optional), assembled-gene annotation (KEGG Orthology `ko.tsv`, EC), QC and annotation statistics. Per biosample: pH, temperature, moisture, organic C, N, C:N, ammonium, depth, coordinates.
- **Coverage:** STER 2013, 2014, 2016, 2017, 2022; KONA 2017, 2019. 183 cropland biosamples (STER 132, KONA 51); 170 of them have processed outputs, 13 STER ones have metadata only. Other NEON sites exist in NMDC; `resources/nmdc_neon_soil_ag_sites_processed.csv` (482 rows, 6 sites: STER, JERC, LAJA, BLAN, SERC, KONA, with direct file URLs and NLCD class) lists them. Running the pull script for sites other than STER and KONA (`--sites JERC`) is expected to work but was not verified.
- **Access:** `https://api.microbiomedata.org` (REST), keyless. Needs a User-Agent. Files come from `data.microbiomedata.org` URLs found in the API.
- **Download:** `.venv/bin/python scripts/pull_nmdc_cropland.py` (options `--sites`, `--out`, `--dry-run`, `--types`, `--workers`). Default types: kraken2, gottcha2, ko, annotation_stats, qc. `ec` and `centrifuge` are off by default (they add about 0.5 GB). Re-running is safe: existing files with the right size are skipped; md5 is checked.
- **Size and time:** default pull 729 MB for 295 unique files, about 5 minutes (README estimate; KO files alone, 668 MB for 68 metagenomes, took 77 s measured).
- **Changes in this version of the script (vs. the earlier one on main):** downloads are deduplicated by data-object id, because up to 3 biosamples share one metagenome and the old script fetched identical files up to 3 times; files are stored by object id; `--types` added; `samples.csv` gets a `metagenome_key` column.
- **Layout on disk (current script):**
  ```
  data/nmdc/samples.csv         183 rows; one per biosample; has metagenome_key = KO data-object id (or Kraken2 id if no KO)
  data/nmdc/data_objects.csv    10,756 rows: every NMDC file linked to each biosample, url, selected, local_path
  data/nmdc/objects/<nmdc_dobj-...>/ko.tsv | kraken2_report.tsv | gottcha2_report_full.tsv | qc_filterStats.txt | annotation_stats.tsv
  ```
  The folder layout `files/<SITE>/<sample name>/` shown in `docs/nmdc-data-guide.md` is the older one. Use `nmdc.object_paths()` to resolve `metagenome_key` to local files.
- **Processing:** `scripts/05_build_biology.py` (offline).
- **Processed outputs** (`data/processed/`):
  - `metagenomes.parquet`, 59 rows, one per composite metagenome: `metagenome_key, site, plotID, date, year, n_biosamples, biosample_names, ph_mean, temp_c, water_content_g_per_g, org_carb_pct, nitro_pct, carb_nitro_ratio, ammonium_nitrogen, n_ko_genes, marker_mean, ko_depth_ok, kraken_total_reads, kraken_bacteria_reads, kraken_unclassified_pct, has_kraken`.
  - `ko_counts_all.parquet`, 131,076 rows, long: `metagenome_key, ko, count` (58 metagenomes, 8,458 distinct KOs).
  - `ko_panel.parquet`, 1,914 rows: panel KOs only, with `gene, function_group, count, per_genome_eq` (count divided by the mean of 5 single-copy marker KOs: K03043, K03553, K02950, K02967, K02982) and `per_million`.
  - `taxa_genus.parquet`, 67,237 rows: `metagenome_key, source (kraken2|gottcha2), genus, reads, pct_of_bacteria, filtered` (59 Kraken2 metagenomes, 46 GOTTCHA2). Caution: `pct_of_bacteria` divides by Bacteria reads only, but the genus rows also include archaea, viruses and animals, so a sample can sum past 100% (one KONA 2017 metagenome with 113 bacterial reads reaches 170%).
  - `taxa_lineage.parquet`, 100,975 rows: `metagenome_key, rank (domain|phylum|class|order|family|genus), name, domain, phylum, reads` (Kraken2 clade reads, Bacteria and Archaea only, each taxon with its phylum; `nmdc.kraken_lineage()`). Use it for shares: divide by the summed `domain` rows of the metagenome. Measured: named phyla cover 95-98% of those reads, classes 87-94%, genera 74-82%. Used by the GUI's soil microbes view.
  - `plot_biology_timeseries.parquet` (59 rows) and `plot_biology.parquet` (latest per plot, 26 rows): percentile and status columns per KO function group and per genus; see `docs/feature_contract.md` (Biology).
- **Join keys:** `plotID` + date to NEON portal products (chemistry, qPCR, ITS); `plotID` to plot coordinates (`resources/neon_soil_plots_landcover.csv`, strip `.basePlot.bgc`); `metagenome_key` between all NMDC tables.
- **Sample-name regex** (`nmdc.NAME_RE`): `SITE_NNN-H-X[-Y]-YYYYMMDD`, for example `KONA_001-M-16-31.5-20190619`. **2022 names have a single depth field** (`STER_006-M-21-20220607`), so the second depth group is optional. `plotID = SITE_NNN`, `H` is the horizon (M mineral, O organic; all cropland samples here are M).
- **Pitfalls:**
  - **The unit of analysis is the metagenome, not the biosample.** 170 processed biosamples map to 59 metagenomes: up to 3 cores are pooled into one composite (55 metagenomes have 3 biosamples). Average the core-level chemistry over the members; do not count them as independent samples.
  - **Depth varies by orders of magnitude.** KO-annotated genes per metagenome (median, measured): STER 2022 about 764,000 (8 of 9 pass the depth gate of at least 50k genes and marker mean of at least 20), STER 2017 about 17,600 (2 of 9 pass), STER 2013, 2014, 2016 about 2k-8k, KONA 2017 about 1,900 (max 26k), KONA 2019 about 450. Function profiles are comparable only within well-sequenced batches. Normalise by marker genes or total genes, carry depth and batch (site x year) as covariates, and subsample before comparing richness.
  - **Kraken2's database has no fungi** (only bacteria, archaea, viruses, and Metazoa among eukaryotes), and about 90% of reads are unclassified. Fungal signals must come from NEON ITS (3.2). GOTTCHA2 does list some fungal genera (for example Fusarium in 5 of the 46 GOTTCHA2 metagenomes: 4 STER 2022, 1 KONA 2017), but that is thin evidence.
  - **nifH (K02588) is not detected in any KO table**, including the 1.2M-gene ones. Treat it as "not detectable", never as "absent". Also: K10944 is labelled pmoA-amoA in KEGG (methane and ammonia monooxygenase cannot be separated); K00370/K00371 combine narG/nxrA and narH/nxrB. See the `caveat` column in `rules/ko_panel.csv`.
  - 1 of the 59 metagenomes has no KO table (Kraken2 only).
  - STER 2013 and 2014 include December and March samples; for cross-year comparisons use summer samples.

### 3.2 NEON data portal: DP1.10081 (ITS), DP1.10109 (qPCR), DP1.10086 (soil chemistry)

- **What:**
  - **DP1.10081.002** (current pipeline) and **DP1.10081.001** (old pipeline): soil microbe community taxonomy / composition. ITS (fungi) taxon tables come **as per-sample CSV files** linked from a sample-metadata table: `mct_soilSampleMetadata_ITS` (.002) and `mcc_soilSeqVariantMetadata_ITS` (.001). Note the different product code: an earlier version of this guide only knew .001 and missed every year after 2017. The two pipelines are **not directly comparable** (different bioinformatics and reference data); the processed tables carry `product`, keep it as a covariate or compare within one pipeline.
  - DP1.10109.001: soil microbe group abundances (qPCR of fungi, bacteria, archaea).
  - DP1.10086.001: soil physical and chemical properties (periodic): chemistry (`sls_soilChemistry`), pH (`sls_soilpH`), moisture (`sls_soilMoisture`), core collection, **metagenome pooling** (`sls_metagenomicsPooling`: which cores make up each metagenome composite), plus `ntr_*` lab tables.
- **Coverage:** STER and KONA in the default scripts (set `neon.SITES` for others).
  - ITS per-sample taxonomy (measured, 506 cores after picking one run per DNA sample; cores passing NEON's read check in brackets):

    | Site | Year | Product | Cores (OK) |
    |---|---|---|---|
    | KONA | 2017 | .001 | 58 (28) |
    | KONA | 2019 | .002 | 83 (66) |
    | KONA | 2024 | .002 | 90 (89) |
    | STER | 2016 | .001 / .002 | 88 (30) / 14 (10) |
    | STER | 2017 | .001 | 87 (47) |
    | STER | 2022 | .002 | 86 (86) |

    149 plot-dates on 26 plots. STER 2013-2014 have ITS only as raw reads (DP1.10108.001), not processed here.
  - qPCR: STER 2013, 2014, 2016, 2017 and KONA 2017 (844 raw rows).
  - Chemistry and pH: 2013 to 2026 (the newest releases may be provisional; the pull uses `include_provisional=True`).
  - Pooling: 76 composites, 228 cores.
- **Access:** NEON data portal API through the `neonutilities` package; **token required** (`NEON_API_TOKEN` in `.env`, sent as `X-API-Token`). `include_provisional=True`, release "current". The per-sample ITS CSVs are public storage URLs; the code fetches them with `http.get` (UA set).
- **Download:** `.venv/bin/python scripts/02_fetch_neon.py [--allow-partial] [DPID ...]` (default: DP1.10081.002, DP1.10081.001, DP1.10109.001, DP1.10086.001). Raw tables land as parquet under `data/raw/neon/<DPID>/<table>.parquet`; for each ITS product the script then downloads **every** per-sample ITS CSV (all runs of re-sequenced samples, 8 threads; 275/275 for .002 and 321/321 for .001, measured), keeps taxonomy and counts only, and writes `mct_soilPerSampleTaxonomy_ITS.parquet` / `mcc_soilPerSampleTaxonomy_ITS.parquet`. Failed downloads are listed by file name. **An incomplete pull writes nothing:** if any site of a product, or any ITS file, fails, the existing raw parquet is left as it was and the script reports `IncompleteFetch` (a table file holds all sites, so writing only the sites that succeeded would silently drop the others). Re-run, or pass `--allow-partial` to keep what succeeded.
- **Size and time:** raw parquet is small (a few MB). The full pull took a few minutes on 21 Nov 2026 (not timed precisely).
- **Processing:** `scripts/02b_build_neon_features.py` (offline).
  - `neon.load_its_raw()` combines both ITS products and keeps **one run per DNA sample**: the deepest run within a product (NEON re-sequenced some samples), then .002 over .001 when a sample is in both (14 cores in STER 2016).
  - `neon.parse_sample_id` accepts IDs with one or two depth fields (from 2022 on NEON IDs have one, e.g. `KONA_001-M-21-20240409-GEN-DNA1`; the earlier regex silently dropped all 2022 and 2024 samples).
- **Processed outputs:**
  - `its_core_genus.parquet` (long, one row per core and genus): `site, plotID, horizon, collectDate, soilSampleID` (core, equals the NMDC biosample name)`, dnaSampleID, product, sequenceCountQF, genus, reads, total_reads` (fungal reads of the core)`, share_pct`. All cores, QC flag kept. Fungal reads without a genus are kept as `unclassified_Fungi`.
  - `its_genus.parquet` (long): `site, plotID, collectDate, year, dnaSampleID (semicolon-joined cores), n_cores, product, genus, reads, total_reads, rel_abund_pct, its_below_threshold_share`. **Only cores passing NEON's read check** (`sequenceCountQF != "Below threshold"`; `neon.build_its_genus(..., qc_ok_only=False)` keeps all). `rel_abund_pct` is the **mean of per-core shares** (each core weighs equally, like the equal-mass cores in a composite), not pooled reads, so one deep core cannot dominate. `reads` and `total_reads` are sums over the included cores (fungal reads only). Zero rows are added for the 18 genera in `neon.GENERA` so detection frequency is defined.
  - `plot_its_timeseries.parquet` (149 rows) and `plot_its.parquet` (latest per plot, 26 rows), wide: `bio_its_share_<Genus>`, `bio_its_detected_<Genus>`, `bio_its_pct_<Genus>` (percentile within site), plus a `Rhizoctonia_complex` (Rhizoctonia + Thanatephorus + Ceratobasidium). Percentiles now span both pipelines: compare with care.
  - `its_genus_lineage.parquet` (1,359 genera): `genus, phylum, class` from the per-sample ITS taxonomy of both pipelines (`neon.its_genus_lineage()`; a genus with several lineages gets the one with most reads). Placeholder names such as `Hypocreales_gen_Incertae_sedis` are kept; the GUI counts them as "no name at this rank". `unclassified_Fungi` (about 23% of fungal reads on average) has no row.
  - `neon_metagenome_pooling.parquet` (228 rows): `soilSampleID, genomicsSampleID, plotID, collectDate`, one row per core pooled into a metagenome composite.
  - `neon_chem.parquet` (715 rows): per `plotID, collectDate` means of `organic_c_pct, total_n_pct, cn_ratio, ph_water, ph_cacl2, soil_moisture`, plus `n_cores`, `site`.
  - `neon_qpcr.parquet` (128 plot-dates): `fungal_copies, bacterial_copies, archaeal_copies, n_cores, n_cores_fungal, unit`.
- **Join keys:** to NMDC metagenomes, **exactly through the cores**: NMDC `biosample_names` and `its_core_genus.soilSampleID` are the same core IDs, and `neon_metagenome_pooling` gives NEON's own core list per composite (`scripts/06_build_joined.py` does this, see 3.8). `plotID` + `collectDate` (a few days of tolerance) works for plot-date tables such as `neon_chem`. NEON `dnaSampleID` embeds the core ID, for example `STER_026-M-8-11.5-20130716-GEN-DNA1`; `neon.parse_sample_id` extracts site, plotID, horizon and date.
- **Pitfalls:**
  - **ITS flags:** `sequenceCountQF` is "Below threshold" for 150 of 506 cores, mostly in the old pipeline (.001: 128 of 233). Those cores are excluded from `its_genus` and the joined table; `its_below_threshold_share` reports the share per plot-date. Plot-date fungal reads (passing cores) range from 576 to about 790,000, median about 33,000; always show `total_reads`.
  - **Two pipelines.** KONA 2017 and STER 2016-2017 (mostly .001) are not directly comparable with KONA 2019/2024 and STER 2022 (.002). Year-to-year changes across that boundary may be method, not biology.
  - **qPCR units are copies per ng of extracted DNA** (`meanCopyNumber`), not per gram of soil. Values range from 0 to about 188,000 (median about 59). Not an absolute abundance; multiplying a relative ITS share by it gives only an approximation (see `scripts/e3_qpcr_scale.py`).
  - ITS genus assignments cannot separate species (Fusarium covers pathogens and non-pathogens). ITS fungal primers under-capture Glomeromycota and miss oomycetes.

### 3.3 SSURGO: soil properties (USDA Soil Data Access)

- **What:** US soil map units and properties. Used here: dominant major component per map unit, surface horizon pH (`ph1to1h2o_r`), clay, organic matter, CaCO3, EC, drainage class, and available water capacity to 100 cm.
- **Coverage:** contiguous US (SSURGO-mapped areas).
- **Access:** `POST https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest` with `{"query": "<SQL>", "format": "JSON+COLUMNNAME"}`. Keyless. Wrapped in `ssurgo.sda_query(sql)` (disk-cached, returns a DataFrame; the first row of the response is the column names).
- **Example SQL:**
  ```sql
  -- point -> mukey
  SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('POINT(-103.0321 40.4652)')
  -- horizons of a component
  SELECT cokey, hzdept_r, hzdepb_r, awc_r, ph1to1h2o_r, claytotal_r, om_r, caco3_r, ec_r
  FROM chorizon WHERE cokey IN ('...') ORDER BY cokey, hzdept_r
  -- map-unit polygons intersecting a window (slow)
  SELECT mukey, mupolygongeo.STAsText() AS wkt FROM mupolygon
  WHERE mupolygongeo.STIntersects(geometry::STGeomFromText('POLYGON((x0 y0, x1 y0, x1 y1, x0 y1, x0 y0))', 4326)) = 1
  ```
- **Functions:** `ssurgo.point_mukey(lat, lon)`, `ssurgo.mukey_properties([mukeys])` (one row per mukey: `ph_surface, clay_pct, om_pct, caco3_pct, ec_dsm, awc100_mm, drainage_class`), `ssurgo.plot_soil(lat, lon)` (modal mukey over the centroid and 4 points at +/-15 m, `mukey_share` = count/5). For polygons: `fields.window_mupolygons(site)` then `fields.dominant_mukey(fields, mupolys)` (largest overlap area per field) and `fields.add_soil(fields, site)`.
- **AWC:** `ssurgo.compute_awc100`: sum over horizons with `hzdept_r < 100` of `awc_r` (cm/cm) x (min(`hzdepb_r`, 100) - `hzdept_r`) x 10, giving mm. NaN if no horizon has `awc_r`.
- **Size and time:** a point lookup is about 3 s cold (measured), cached afterwards (`data/cache/sda/`, 30 MB for the whole prototype). **A window polygon query takes about 4 minutes cold.** If it times out, tile the window into 4 parts.
- **Outputs:** soil columns of `plots.parquet` (44 plots) and `fields.parquet` (4,854 fields); column meanings in `docs/feature_contract.md` (Soil).
- **Pitfalls:** `caco3_r` is often not reported (NaN; do not silently treat as 0). Map units can be complexes; `mukey_share` tells you how pure the dominant unit is. SDA reports "typical" component values, not point measurements, so compare with NEON chemistry (3.2) when it matters.

### 3.4 Daymet: daily weather

- **What:** 1 km daily surface weather (ORNL). Used: `tmax, tmin, prcp`.
- **Coverage:** North America, 1980 to the last published year. Used here: 2008-2025 (years not yet published are absent from the response).
- **Access:** `https://daymet.ornl.gov/single-pixel/api/data?lat=..&lon=..&vars=tmax,tmin,prcp&years=2008,2009,...` returning CSV text with a metadata header. Keyless. `daymet.fetch_daymet(lat, lon, y0, y1)` parses it into `date, year, yday, tmax, tmin, prcp` (disk-cached in `data/cache/daymet/`, 67 MB for about 400 points).
- **Derived features:** `daymet.yearly_climate(df)` per year; `daymet.summarise_yearly` medians and probabilities; `daymet.climate_features(lat, lon, 2008, 2025)` returns the contract columns (GDD10 May-Sep, frost-free days, Apr-Sep and Oct-Jun precipitation, hot days, `p_wet_may`, `p_hot_dry_jul_aug`, `p_june_heat`, `climate_years_used`). Definitions in `docs/feature_contract.md`.
- **Time:** about 3 s per point for 18 years (measured, cold). Fields use a 2 km snapped grid (`daymet.snap_to_grid`) to dedupe: 346 grid points for 4,854 fields.
- **Pitfall:** **Daymet uses a 365-day calendar**: in leap years Dec 31 is dropped (so `yday` 1..365 maps to Jan 1 + `yday-1` days in every year; that is what the code does). Only years with `yday` up to 365 are treated as complete.

### 3.5 CDL: Cropland Data Layer (crop per pixel and year)

- **What:** USDA NASS 30 m crop classification, one raster per year.
- **Coverage here:** 2008-2021 via Planetary Computer.
- **Access:** Microsoft Planetary Computer STAC `https://planetarycomputer.microsoft.com/api/stac/v1`, collection `usda-cdl`. Filter items with the property **`usda_cdl:type == "cropland"`** (the collection also has other layer types); asset key `cropland`; CRS `EPSG:5070` (`proj:code`); sign asset URLs with `planetary_computer.sign`. Keyless. **Read windows, not whole rasters** (cloud-optimised GeoTIFF).
- **Functions:** `cdl.cdl_history(lat, lon, years)` returns, per year, the majority class in a 40 x 40 m window: `year, cdl_code, crop_group, share, edge (share < 0.6), source`. `cdl.cdl_history_many({id: (lat, lon)})` runs it threaded. `cdl.crop_group(code)` maps a CDL code to the group vocabulary using `rules/cdl_codes.csv`.
- **Time and size:** about 14 s per point for 14 years (measured); the whole 44-plot history is under 100 MB transferred and `plot_crop_history.parquet` is 6 KB (616 rows).
- **Fallbacks:** the CropScape API was returning HTTP 503 on 21 Nov, so do not depend on it. The national CDL zips from NASS (about 1.8 GB per year) are the offline fallback (not implemented here).
- **Pitfalls:** CDL has no data beyond 2021 on Planetary Computer (use CSB, 3.6, for 2018-2025). The rules table maps some codes coarsely (for example 205 triticale falls in `barley_oats`, 28 and 21 in `barley_oats`, double crops in `double_wheat_soy`). Small or narrow parcels give mixed pixels: check `share` and `edge`.

### 3.6 NASS Crop Sequence Boundaries (CSB)

- **What:** field-like polygons with the CDL crop code for each year, derived from CDL (so no irrigation flag, no field-level truth).
- **Coverage:** national, 2018-2025, revision 23. 15,973,095 features.
- **File:** `NationalCSB_2018-2025_rev23.zip`, **3.76 GB** zip (5.7 GB unzipped), a FileGDB `CSB1825.gdb` with a single layer **`national1825`** in a USA Albers CRS (about EPSG:5070). Obtain it from the USDA NASS CSB download page (national FileGDB) and place it at `data/raw/csb/NationalCSB_2018-2025_rev23.zip`. Keyless. Older vintages back to 2009-2016 exist (not used here). Download time: 10-30 min (estimate, not re-measured).
- **Columns:** `CSBID, CSBYEARS, CSBACRES, CDL2018 ... CDL2025, STATEFIPS, STATEASD, ASD, CNTY, CNTYFIPS, INSIDE_X, INSIDE_Y, ORIG_FID, Shape_Length, Shape_Area, geometry`.
- **Reading:** straight from the zip with a bounding box, no unzip: `pyogrio.read_dataframe("/vsizip/<zip>/CSB1825.gdb", layer="national1825", bbox=(minx, miny, maxx, maxy))`, with the bbox transformed to the layer CRS. About 17 s for a 3 km box (measured). `csb.clip_csb_to_windows()` does this for the windows in `config/regions.yaml` and writes `data/processed/csb_raw_<site>.parquet` (STER 4,871 fields, KONA 1,998). `csb.load_window_fields(site)` then clips to the window, adds `unit_id = CSB_<CSBID>`, `area_ha`, `crop_<year>` groups, `crop_t1..t5` and lat/lon.
- **Outputs:** `fields.parquet` (4,854 fields of at least 2 ha: STER 3,507, KONA 1,347; geometry simplified to 10 m, EPSG:4326), `plot_csb.parquet` (29 plots, point-in-polygon match: `csb.plot_to_csb`).
- **Pitfalls:** CSB drops small fields and non-crop land, so a plot can fall outside every polygon (all 29 STER and KONA plots matched). For 2018-2021 you can compare with CDL history.

### 3.7 LUCAS (EU): soil fungi (GlobalFungi ITS) and land-cover history

- **What:** two pieces. (a) **GlobalFungi ITS genus table** for LUCAS 2018 topsoil (Labouyrie et al. 2023) and a few other studies: `resources/lucas_fungi_genus.csv` (1,074 rows, 43 columns: `sample_ID, paper_ID, country, latitude, longitude, environment_type, pH, organic_C_content, total_N_content, ITS_total, fungal_reads`, then genus columns as percentages). 374 rows are `paper_ID == "Labouyrie_2023_BBS"` and `environment_type == "cropland"`; the other 151 cropland rows come from non-LUCAS studies and are excluded in `e1_match.py`. (b) **JRC harmonised LUCAS table** `lucas_harmo_uf.zip` (128 MB zip, 1.6 GB CSV, 1.35M rows: 2006, 2009, 2012, 2015, 2018), with land cover `lc1` per point and survey year.
- **Access:** keyless. The JRC harmonised table is distributed by the EU Joint Research Centre (LUCAS harmonised microdata); save it as `data/raw/lucas/lucas_harmo_uf.zip`. The GlobalFungi table is already in `resources/`. A second small table `resources/lucas_PL_dna_points_crop_history_2009_2022.csv` (31 Polish points with `POINT_ID` and `LC1_2009 ... LC1_2022`) has a crop history by point id.
- **Slim file used by `e1_match.py`** (not created by any script; make it yourself, 5 s measured):
  ```python
  import pandas as pd
  cols = ["point_id","year","nuts0","th_lat","th_long","gps_lat","gps_ew","gps_long","lc1","lc1_label"]
  h = pd.read_csv("data/raw/lucas/lucas_harmo_uf.zip", usecols=cols, dtype={"lc1": str})
  h.to_csv("data/raw/lucas/lucas_harmo_slim.csv", index=False)
  ```
- **Matching ITS rows to LUCAS points:** the genus table has **no POINT_ID**, so `scripts/e1_match.py` matches by nearest point (haversine BallTree). **The ITS points sit on the LUCAS theoretical coordinates (`th_lat`, `th_long`)**: all 374 matched within 0.66 m (median 0.36 m). The harmonised **GPS coordinates are poor for this**: 206k of the 1.35M rows carry sentinel values (`gps_lat` = 88.88889), and only 39 of 374 ITS rows match a GPS point best. Use the theoretical coordinates. 373 points remain after dropping one duplicated point id. The script also builds crop-history labels from `lc1` across 2009-2018 (maize is `B16`, cereals B11-B19).
- **Output:** `outputs/e1/e1_matched.csv` and `match_stats.json` (gitignored). `scripts/e1_match.py` also relies on `scikit-learn`.
- **Climate for EU points:** `cropfit.e1.climate(df)` uses Open-Meteo archive (mean annual T and precipitation 2010-2018), `cropfit.e1.climate_power(df)` NASA POWER climatology. **Open-Meteo rate-limits** (HTTP 429, with minute and hourly caps); the code backs off a full minute and caches responses; POWER is the fallback.
- **Pitfalls:** genus values are relative abundance (% of fungal reads), genus level only; `ITS_total` and `fungal_reads` tell you the depth. Barcoding regions differ across studies (`barcoding_region`). Country is a strong confounder in any cross-site model (group your cross-validation by country).

---

### 3.8 Joined table: bacteria + fungi + soil per metagenome

- **What:** one row per NMDC metagenome (composite of up to 3 cores) with NMDC soil and depth columns, Kraken2 bacterial genus shares, KO panel function groups, NEON chemistry, and NEON ITS fungal shares from **exactly the cores pooled into that metagenome**.
- **Build:** `.venv/bin/python scripts/06_build_joined.py` (offline; after 02b and 05).
- **Outputs** (`data/processed/`):
  - `joined_metagenomes.parquet` (59 rows, 72 columns): all `metagenomes.parquet` columns, plus
    - `genomicsSampleID, pooling_check`: NMDC's core list compared with NEON's pooling table (`match` for 55; `mismatch` for 4 STER 2013 metagenomes, where NMDC holds separate metagenomes for subsets of one NEON composite);
    - `neon_*`: `neon_chem` for the plot-date (+-3 days);
    - `ko_<function_group>`: summed `per_genome_eq` of the KO panel (meaningful only where `ko_depth_ok`);
    - `bac_share_<genus>` for `nmdc.BIO_GENERA` (% of bacterial reads);
    - `n_fungal_cores_any, n_fungal_cores_ok, fungal_reads, fungal_products`;
    - `fun_share_<genus>` for `neon.GENERA` + `Rhizoctonia_complex`: mean per-core share (% of fungal reads) over the metagenome's QC-passing cores; NA when it has none.
  - `joined_fungi_genus.parquet` (long): `metagenome_key, genus, rel_abund_pct` for all genera (32 metagenomes, 738 genera).
- **Coverage (measured):**

  | Site | Year | Metagenomes | With fungi | Depth OK | Depth OK and fungi |
  |---|---|---|---|---|---|
  | KONA | 2017 | 10 | 7 | 0 | 0 |
  | KONA | 2019 | 7 | 7 | 0 | 0 |
  | STER | 2013 | 7 | 0 | 0 | 0 |
  | STER | 2014 | 8 | 0 | 0 | 0 |
  | STER | 2016 | 9 | 2 | 0 | 0 |
  | STER | 2017 | 9 | 7 | 2 | 2 |
  | STER | 2022 | 9 | 9 | 8 | 8 |

  Only 10 metagenomes have both usable gene profiles and fungal data, 8 of them STER 2022. Without DP1.10081.002 it would be 2.
- **Pitfalls:** `fungal_products` mixes the two ITS pipelines; 32 rows and hundreds of genera is a p >> n setting, so use a small set of chosen features.

### 3.9 Geo data linked to the sampling events

- **Idea:** the anchor is a **sampling event** = one visit to a plot (`plotID`, date; visits at most 3 days apart are one event). Every other dataset is reduced to the plot footprint when it is fetched, then attached to each event through a time window. `config/modalities.yaml` is the registry (role, spatial and temporal support, table, operator); `cropfit/link.py` holds the operators; `scripts/07_build_event_features.py` applies them.
- **Events (measured):** 721 events on 29 plots, 175 with biology (metagenome or ITS) on 28 plots. `event_cores` gives each soil core its position inside the plot (NEON reports the plot centre as lat/lon for every core; the offset is `coreCoordinateX/Y` in metres from the south-west corner).
- **Footprint:** the 40 x 40 m plot square. Raster values are area-weighted (`stac.footprint_window`): a 30 m pixel half outside the plot counts half.
- **Time windows:** `static`; `antecedent_7d/30d/90d` and `year_to_date` (weather before sampling); `at_sample` (nearest observation within a tolerance, lag recorded); `last_before`; `nearest_flight`, `nearest_survey`; `season` (year of the event), `prior_t-k` (k years before), `anomaly` (event year minus the plot's mean of other years). A feature that cannot be computed is absent, never 0.
- **Outputs:**
  - `event_features.parquet` (long): `event_id, modality, role, variable, window, value | value_text, obs_date, lag_days, n_obs, source`. `lag_days` = observation date minus sampling date (negative = before).
  - `event_table.parquet` (wide, the 175 events with biology): event columns, biology (`joined_metagenomes` columns, `its_share_<Genus>`), and every feature as `<modality>__<variable>__<window>` plus `<modality>__lag_days__<window>`.
- **Datasets added for this** (all per plot):

  | Table | Source | Content | Notes |
  |---|---|---|---|
  | `plot_vi_timeseries`, `plot_season` | Sentinel-2 L2A (2015+) and Landsat 8/9 C2 L2 (2013+), Planetary Computer, keyless | per scene: band reflectances, `ndvi, evi, ndmi, ndre` (S2 only), `bare_soil_index`, `clear_frac`, `clear`; per year: peak, peak day, season integral, green-up, senescence | 2,686 scenes, 17,019 clear plot-observations; use only `clear`. Sentinel-2 NDVI is on average 0.05 below Landsat on the same days (r = 0.98): keep `sensor`. 3 Landsat scenes could not be read (listed with `read = False` in the manifest) |
  | `plot_aerial` + chips | NAIP (0.3-1 m, R G B NIR; 2011-2023, every 2 years) and NEON airborne camera `DP3.30010.001` (10 cm R G B) | in-plot greenness (`ndvi_*` NAIP only, `exg_*`, `green_frac`), spread = patchiness, chip and preview paths | camera digital numbers, not reflectance: compare within one flight. NEON gives the campaign month, not the day (`date_precision`). NEON tiles are read remotely row by row (a tile is ~300 MB, no overviews); slow, about 1.5 chips per minute, so NEON chips cover only 120 m around the plot while NAIP chips cover 1 km (`fetch_naip` `context_m=500`) |
  | `plot_terrain` | USGS 3DEP 10 m | elevation, slope, aspect, `tpi_150m` (plot minus its 150 m surroundings), relief | static |
  | `plot_weather_daily` | Daymet | daily tmax, tmin, prcp 2007-2025 | 2026 not published yet: 2026 events have no weather windows |
  | `neon_inorganic_n` | NEON `DP1.10086.001` `ntr_*` tables (already in the chemistry pull) | ammonium and nitrate (mg N/kg dry soil), net N mineralisation and nitrification per day | 117 plot-dates, 20 plots, 2017/2019/2022/2024 |
  | `neon_management_events`, `neon_crop_reported` | NEON `DP1.10111.001` | dated seeding, harvest, tillage, herbicide, fertiliser per plot, with product or species; harvested species per plot and year | 1,134 plot-events 2013-2026. **Fills the crop gap after 2021** (CDL ends 2021, CSB zip not present). Some dates are estimates (`date_quality`) |
  | `neon_soil_baseline` | NEON `DP1.10047.001` | one soil pit per plot, top horizon: pH, C, N, CEC, texture, bulk density | 18 of the 29 plots; measured once (STER 2015, KONA 2018) |
  | `neon_plant_cover` | NEON `DP1.10058.001` | per ground survey: plant cover, bare soil, litter (%), species count, dominant species | 214 surveys on 20 plots |

- **Fetch the three extra NEON products:** `.venv/bin/python scripts/02_fetch_neon.py DP1.10111.001 DP1.10047.001 DP1.10058.001`, then `02b_build_neon_features.py`.
- **Checks done (measured):** season peak by CDL crop of the same plot-year: winter wheat day 124, barley/oats 144, millet 214, corn and soybean 226; fallow peaks at NDVI 0.30 against 0.67-0.81 for corn and soybean. 97% of biology events have a clear satellite observation within 6 days.
- **Pitfalls:**
  - Weather is 1 km: plots of one site share a few cells, so it separates sampling dates, not plots.
  - `season` uses the calendar year; autumn growth of winter wheat belongs to the year before.
  - Imagery before the sampling date is plant input to the soil community; imagery after it is an outcome. `lag_days` tells which.
  - Not done: NEON hyperspectral indices and canopy height (the lidar height model is set to 0 below 2 m, useless for crops), CSB field polygons (zip absent), Sentinel-1 radar.

### 3.10 Association scan (microbiome against environment)

- **What:** `scripts/11_association_scan.py` tests every microbiome column of `event_table` (`its_share_*`, `bac_share_*`, `ko_*` where depth is sufficient, qPCR fungal and bacterial copies) against every numeric environmental column, per site and for both sites together. Output `association_scan.parquet`, one row per pair and scope; browse it in the inspector (tabs Associations and Compare).
- **Why not a plain correlation:** a response can have an optimum (bell shape, e.g. along pH) that leaves the correlation near zero, and two sites or years that differ in both variables can fake one. The scan therefore reports:
  - `dcor_adj`, `p`, `q`: distance correlation (any shape) on values centred within site x year, permutation test shuffling only inside a site-year, Benjamini-Hochberg q per scope;
  - `rho`, `rho_adj`: rank correlation raw and within site-year;
  - `shape`, `turning_point`, `p_curve`, `r2_line`, `r2_curve`: quadratic fit on sqrt(value) with site-year intercepts; `hump` = significant concave curve with its maximum inside the central 80% of the predictor;
  - `rho_within_plot`: rank correlation on values centred per plot (constant plot differences removed; empty for static predictors);
  - `timing`: `before` / `at sampling` / `around (may be after)` / `constant`, from the time window.
- **Result (measured, 3,532 pairs):** STER 73 pairs with q < 0.1 (38 with q < 0.05), both sites together 38, KONA none. Of the pairs with q < 0.1 that can be checked within plots, half keep their direction there. Soil pH shows no association that survives correction in either site (the pH range inside a site is narrow: KONA about 5.2-6.6, STER 6.2-8.5).
- **Limits:** observational, 28 plots, two sites: the scan finds candidates, it does not show cause. Events of one plot are not independent, so p-values are optimistic. Fungal shares are relative: one genus rising pushes others down. Several strong STER pairs involve the NEON airborne photo, which has 38 events from two campaigns.

### 3.11 Knowledge bases: what a microbe does to a plant, and when (only FungalTraits and USDA Fungus-Host downloaded, see 3.12)

- **Status:** FungalTraits and USDA Fungus-Host are now downloaded and used by code (see 3.12). Apart from the organisers' risk workbook (inspected on 21 Nov 2026, see below), none of these sources is downloaded or read by code in this repo. The rest of this section was compiled from prior knowledge on 21 Nov 2026 and is **not verified** (URLs, file formats, sizes, licences, rate limits). Check each source before relying on it, and replace this note with measured facts once something is pulled.
- **Why:** the measured tables only say *which* genera are present and in what share. Turning that into crop advice needs two kinds of knowledge:
  1. **What the microbe does:** lifestyle (plant pathogen, mutualist, saprotroph, growth promoter), which crops it affects, which disease it causes. Example: Macrophomina causes charcoal rot on sorghum, soybean, sunflower and corn.
  2. **When it matters:** the conditions under which the effect actually happens (soil or air temperature, moisture, crop stage, previous crop, pH, nitrogen). Example: charcoal rot is favoured by hot soil and drought stress around flowering.
- **The curated databases below fill the first kind reasonably well. The second kind has to be built by hand or mined from papers.** That is where an LLM extracting from papers helps most, because this knowledge exists mainly as sentences in papers and extension guides, not as database fields. The databases record lifestyle and host lists; they do not model an organism's environmental needs.
- **Kind 1 comes at two levels of detail, and only one says which crop is affected:**
  - **Genus labels** (FungalTraits, FUNGuild): "Fusarium: plant pathogen". Good as a **filter** (is this genus worth looking at?), but they say nothing about which crops.
  - **Species × host records** (USDA Fungus-Host, APS, EPPO, CABI; PHI-base for lab-studied pathogens): "*F. graminearum* recorded on *Triticum aestivum*". Only these let you say which share of a genus's documented species are recorded on a given crop.
- **What no database gives:** whether the evidence for an effect comes from the field, a greenhouse or a lab, i.e. the evidence type. USDA records each cite a reference, so their count is a rough proxy for the number of studies; the evidence type has to come from papers or extension guides. Bacteria are covered only by PLaBAse, and only for beneficial traits.
- **First to pull (planned, access not verified yet):** FungalTraits as the genus filter and USDA Fungus-Host for species × crop host records.

**Kind 1, what the microbe does: curated databases (start here, before mining literature):**

| Source | What it gives | Resolution | Access (not verified) | Environmental needs? |
|---|---|---|---|---|
| **FungalTraits** (Põlme et al. 2020, *Fungal Diversity*, doi:10.1007/s13225-020-00466-2) | Primary and secondary lifestyle for about 10k fungal genera (e.g. plant pathogen, root endophyte, arbuscular mycorrhizal, saprotroph), plant-pathogenic capacity | Genus (plus a species-hypothesis table) | Supplementary table of the paper; keyless | No. Same resolution as NEON ITS: the best first match for the ITS genus columns |
| **FUNGuild** (Nguyen et al. 2016, *Fungal Ecology*, doi:10.1016/j.funeco.2015.06.006) | Trophic mode, guild, confidence ranking (Possible / Probable / Highly Probable) | Genus, some species | Online database (JSON) and the FUNGuild script on GitHub; keyless | No. Many genera get several guilds; keep the confidence ranking |
| **USDA ARS Fungal Databases**, Fungus-Host Distributions (Farr & Rossman) | Recorded fungus-host plant pairs with literature references | Species × host plant | Web query at `fungi.ars.usda.gov`; keyless; bulk export unclear | No. Where it was found, not under what conditions; a record is one observation, not a measure of disease importance |
| **APS Common Names of Plant Diseases** (American Phytopathological Society) | Disease name → causal organism, per crop | Species × crop | Free web pages; scraping terms not checked | No. Good for listing the known pathogens of the crops in `rules/cdl_codes.csv` |
| **PHI-base** (Urban et al., *Nucleic Acids Research*) | Pathogen-host interactions: pathogen species, host, gene, mutant phenotype, PubMed ID | Species and gene | Downloads (CSV) at `phi-base.org`; keyless; CC BY 4.0 | No. Lab conditions only; useful for linking genes later, not for field risk |
| **EPPO Global Database** | Host plants, distribution and regulatory status of pests and pathogens | Species | `gd.eppo.int`; the REST API needs a free token from a registered account | Distribution only. Focused on regulated and quarantine organisms, not common soil fungi |
| **CABI Compendium** (Crop Protection) | Host ranges, impact, management; datasheets have a free-text climate / environment section | Species | Subscription, partly open | Partly, as free text (e.g. "favoured by high temperatures and drought stress"). Do not bulk-scrape; use for manual checks |
| **PLaBAse / PGPT ontology** (Patz et al.) | Plant-growth-promoting traits of bacteria, gene-based annotation of plant-associated bacteria | Bacterial genes and genomes | Web tool at the University of Tübingen; keyless | No. The bacterial side: Kraken2 genera and the KO table |

**Kind 2, when it matters: sources of environmental conditions:**

| Source | What it gives | Limits |
|---|---|---|
| **Organisers' risk workbook** `metodyki/ryzyka_zebrane.xlsx` in the organisers' hackathon repo (their docs call it `zboza_ryzyka.xlsx`; inspected 21 Nov 2026) | Condensed extract of the official Polish integrated crop protection guides (*metodyki integrowanej ochrony*). 5 sheets: sugar beet, corn, wheat, sunflower, potato. Per disease or pest: temperature, moisture, other risk factors (previous crop, monoculture, pH, excess N, heavy soil). 4 embedded images: corn water needs by stage, winter-wheat stage durations by sowing date, wheat pest and sunflower disease timing by BBCH stage. Example row: *Macrophomina phaseolina* (charcoal rot of sunflower), about 30 °C, low humidity | Diseases named in Polish, Latin names only for sunflower and some potato rows, so a disease → pathogen → genus mapping is needed. Mixed formats (`15-25`, "warm summers", "not stated"), air vs soil temperature often unclear. Most rows are leaf diseases and insects that a soil sample cannot see. No soybean or sorghum; barley, oat, rye, triticale only in the PDFs. Polish context: pathogen temperature ranges transfer, sowing dates do not |
| **The metodyki PDFs** (same folder, 14 files: wheat, triticale, rye, barley, oat, corn, sugar beet, potato, sunflower, GIORiN cereals guide) | The authoritative text behind the workbook | Polish; already curated, so a much better corpus for LLM extraction than random papers; cite the guide by title |
| **Disease forecasting models** | Weather-driven risk for single diseases; the best-known US example is the Fusarium head blight risk tool for wheat (temperature and humidity around flowering) | Exist for a few diseases only; charcoal rot has thresholds in the literature but no widely used operational model |
| **GlobalFungi** (occurrence records with climate, pH and land use per sample; the LUCAS table in `resources/` is of this kind) | Empirical niche: where a genus's share tends to be high (warmer, drier, given pH) | Correlation, not proof; mixed studies and barcoding regions |
| **BacDive** (bacteria), culture studies (fungi) | Lab growth temperature and pH ranges and optima | Lab, not field soil: use as plausibility limits, not as risk predictions |
| **CLIMEX-type and crop-disease models** | Mechanistic response to temperature and moisture | Only for well-studied pests; mostly commercial or research-grade |
| **Papers via LLM extraction** | Crop- and context-specific conditions that no database holds | See the extraction rules in the pitfalls below |

**Literature search, name normalisation and gene annotation:**

| Source | Use | Access (not verified) |
|---|---|---|
| Europe PMC REST (`https://www.ebi.ac.uk/europepmc/webservices/rest/search`) | Search, abstracts, full-text XML for open-access papers | Keyless |
| NCBI E-utilities (PubMed) | Search and abstracts | Keyless up to about 3 requests/s; an optional NCBI API key raises the limit. Set the `tool` parameter; do not put a personal email in requests |
| OpenAlex (`https://api.openalex.org`) | Paper metadata, citation counts, open-access links | Check the current access terms |
| GBIF species match (`https://api.gbif.org/v1/species/match?name=Fusarium`), NCBI Taxonomy | Map genus names and synonyms to stable IDs | Keyless |
| KEGG REST (`https://rest.kegg.jp`) | KO definitions and pathways behind `rules/ko_panel.csv` | Keyless for academic use; not for commercial redistribution |

- **Soil-borne rows of the workbook that match ITS genera** (pathogen names added from general knowledge, not from the workbook, except where it gives them):

  | Crop | Disease (workbook name) | Pathogen → ITS genus | Conditions in the workbook |
  |---|---|---|---|
  | Sunflower | Czarny uwiąd (charcoal rot) | *Macrophomina phaseolina* → Macrophomina | about 30 °C, low humidity |
  | Sunflower | Zgnilizna twardzikowa (white mould) | *Sclerotinia sclerotiorum* → Sclerotinia | 15-25 °C (optimum 19-20), high; risk after rapeseed |
  | Sunflower | Zgorzel siewek (damping-off) | Fusarium, Alternaria (Pythium too, not in ITS) | 8-18 °C, high; sowing into cold soil |
  | Wheat | Fuzaryjna zgorzel podstawy (Fusarium foot rot) | Fusarium | 5-25 °C, wet or overly dry soil |
  | Wheat | Fuzarioza kłosów (head blight) | Fusarium | 15-25 °C, humid; corn residue |
  | Wheat | Zgorzel podstawy źdźbła (take-all) | Gaeumannomyces | 12-20 °C, wet air and soil |
  | Wheat | Ostra plamistość oczkowa (sharp eyespot) | *Rhizoctonia cerealis* → Ceratobasidium (`Rhizoctonia_complex`) | 15-25 °C, warm, dry soil |
  | Wheat | Łamliwość źdźbła (eyespot) | Oculimacula | 5-15 °C, wet |
  | Sugar beet | Zgnilizna brunatna korzenia (root rot) | *Rhizoctonia solani* → `Rhizoctonia_complex` | 25-30 °C, wet; risk rises after corn |
  | Corn | Zgorzel siewek, fuzariozy łodyg i kolb (damping-off, stalk and ear rot) | Fusarium | cold and wet at emergence; drought stress for stalk rot |
  | Potato | Rizoktonioza (black scurf) | *Rhizoctonia solani* → `Rhizoctonia_complex` | wet periods, heavy soils, early planting |

- **Join keys to the repo data:** the genus name: `its_genus.genus`, `its_core_genus.genus`, `joined_fungi_genus.genus`, `taxa_genus.genus`, the `fun_share_<Genus>` / `bac_share_<Genus>` columns of `joined_metagenomes` and `its_share_<Genus>` of `event_table`. Normalise both sides (case, whitespace, suffixes such as `_sp`; drop `unclassified_Fungi`), ideally to a GBIF or NCBI taxon ID. Map crop names to the crop-group vocabulary of `rules/cdl_codes.csv` (and the species in `neon_crop_reported`) so effects can be matched to crop history. Host databases name plants in Latin, so a host-taxon → `crop_group` mapping is needed: *Zea mays* → corn, *Triticum aestivum* → winter/spring wheat, *Glycine max* → soybean, *Sorghum bicolor* → sorghum, *Helianthus annuus* → sunflower, *Panicum miliaceum* → millet, *Phaseolus vulgaris* → dry_bean, *Medicago sativa* → alfalfa, *Hordeum vulgare* and *Avena sativa* → barley_oats. Records given only to host genus (e.g. "*Triticum* sp.") need an explicit rule. Kind-2 conditions map to weather features: `daymet.climate_features` (e.g. `p_hot_dry_jul_aug`: share of years with at least 15 Jul-Aug days at tmax ≥ 35 °C and Jul-Aug rain below the pixel's 25th percentile, see `docs/feature_contract.md`) or the event windows of 3.9. Note these are air temperature and rain; most conditions in the sources refer to soil temperature and soil moisture.
- **Cross-check:** the association scan (3.10) can show whether a genus's share moves with the conditions a source claims (e.g. Macrophomina against hot, dry weather). With 28 plots that is a sanity check, not a validation.
- **Suggested layout:** raw downloads under `data/raw/kb/<source>/` (gitignored like the rest of `data/`). Small curated outputs (a genus → guild table, a genus × crop effect table, a disease-conditions table from the workbook) belong in `resources/` or `rules/`, with `source`, `source_version` and, for conditions, `temp_type` (air or soil) columns.
- **Pitfalls:**
  - **Resolution mismatch.** Effects are reported for species, strains or *formae speciales*; the data here is genus level. For each genus × crop, store which share of the documented species are pathogens or mutualists, and label the genus "mixed" when it is (Fusarium, Rhizoctonia, Pseudomonas, Bacillus). Macrophomina is an exception: it is practically one species, *M. phaseolina*, with a broad host range.
  - **Synonyms and dual names.** The ITS reference (UNITE) and older papers can use different names for the same fungus: Thanatephorus is the sexual stage of *Rhizoctonia solani* (the repo already merges a `Rhizoctonia_complex`), Gibberella of several Fusarium species, Cochliobolus of Bipolaris. Normalise names to IDs before joining.
  - **A record is not a risk.** A fungus-host record or a lab inoculation does not mean disease in the field; disease needs a susceptible host, the pathogen and the right environment together. Keep the evidence type (field, greenhouse, in vitro) and the number of independent studies. Inoculum thresholds in papers are per gram of soil (CFU, microsclerotia), so they cannot be compared with relative ITS shares.
  - **Publication bias.** Pathogens are studied far more than neutral or beneficial organisms. A genus with no records is "unknown", not "harmless".
  - **The knowledge bases cover more than the data can see.** Oomycetes (Pythium, Phytophthora, Aphanomyces) and nematodes are absent from the ITS fungal data and from Kraken2, so entries about them cannot be matched to any sample here.
  - **LLM extraction from papers and guides.** Use a strict schema (taxon as written, normalised taxon and rank, crop, effect, conditions, threshold, evidence type, quoted sentence, DOI or guide title and page, model and version). Check automatically that the quoted sentence appears in the source text and drop the claim if it does not. Use abstracts, open-access full text and the metodyki PDFs only, and do not redistribute full texts.

### 3.12 Crop risk index (FungalTraits + USDA Fungus-Host + NEON ITS)

- **What:** for a site and year, risk(p, c) = Σ_g A(p, g) · H(g, c), summed over genera that pass the FungalTraits filter. p is a plot-unit (plotID, year, ITS product) and c is a crop. Nothing else enters the score: no weather, soil, crop history or evidence weights. It is a relative index, not a probability of disease.
- **A (abundance rank):** mid-rank percentile (`neon.percentile_rank` / 100) of the unit's genus share among reference units. The share is the mean of per-core shares over the QC-passing horizon-M cores of the plot in that year and product. The reference is the same site, same ITS product, all years, depth-OK for the genus, and includes the unit itself. A reference below 10 units is flagged `small_reference`; below 5, A is not computed (`reference_too_small`).
- **Depth:** a unit needs 2000 fungal reads, otherwise `status = insufficient_depth`. A genus with 0 reads is skipped as `insufficient_depth` when total_reads × s_typ < 3 (s_typ = the genus's median non-zero share at that site and product). That misses a typical genus about 5% of the time. Otherwise a zero is `not_detected` and gets its mid-rank percentile. Genera never detected in the reference (for example Macrophomina at STER) are `not_detected_in_reference` and are not summed.
- **Filter:** FungalTraits primary or secondary lifestyle == `plant_pathogen`. `Plant_pathogenic_capacity_template` is reported but does not admit a genus: it would admit 77 more genera, for example Trichoderma. Non-fungal phyla (Oomycota and 4 other protist phyla) and the oomycete genera Pythium, Phytophthora, Aphanomyces, Globisporangium and Phytopythium are excluded, because ITS fungal primers miss them.
- **H (host share):** species of the genus with at least one USDA record on a host taxon of the crop ÷ species of the genus with any USDA record (all countries). var., f. sp. and subsp. collapse to the species. Fungus records given only to genus are not counted (reported as `n_genus_only_records_on_crop`). Host records given only to genus count only for Zea, Glycine, Triticum, Hordeum and Avena (`rules/crop_host_taxa.csv`). Bread-wheat taxa map to both winter_wheat and spring_wheat; durum (*Triticum durum*, *T. turgidum*) maps to spring_wheat only, so the two wheat scores differ slightly (up to 0.03, measured). Infraspecific forms match their species, so a few wild forms count too (teosinte subspecies of *Zea mays*, *Andropogon sorghum* var. *halepensis* = Johnson grass); measured impact: one fungus species. `metadata.same_host_taxa_as` lists crops whose host evidence is identical (none with the current table).
- **Crops scored:** corn, soybean, winter_wheat, spring_wheat, sorghum, sunflower, alfalfa, millet, dry_bean, barley_oats. `double_wheat_soy` is a rotation and the other groups are not single crops, so they are not scored. A crop with no host record among the scored genera gets `status = no_knowledge` (NaN, never 0).
- **Sources (measured):**
  - FungalTraits = Põlme et al. 2020 Table S1, official Springer ESM xlsx (990,658 bytes), 10,771 rows → 10,765 genera, 1,758 pass the filter. The article licence is not verified, so the raw file stays local.
  - USDA Fungus-Host = Ag Data Commons snapshot `Fungus-Host-Data_20211105.csv`, DOI 10.15482/USDA.ADC/1524414, U.S. Public Domain, 187,658,073 bytes, 827,645 rows, 0 bad lines, data current to 5 Nov 2021. The live fungi.ars.usda.gov API needs a site-internal key and is not used.
  - Each raw folder has a `manifest.json` (url, retrieved_utc, bytes, sha256, source_version). `kb_meta.json` copies them and is included in every result's `metadata.kb`. Refresh: `scripts/14_build_kb.py --refresh`.
- **Built KB (measured):** `kb_genus_crop_host` has 74,240 rows (7,424 genera × 10 crops) and documents 90,873 species. Examples: Fusarium has 443 species (Gibberella merged), H = 0.19 for winter wheat, 0.17 for corn, 0.13 for soybean. Macrophomina has 8 species, H = 0.25 on corn, soybean, sorghum and sunflower.
- **Output:** `compute_crop_risk(site, year, ...)` returns a `CropRiskResult` with `summary`, `contributions` and `skipped` DataFrames, plus `metadata`. `to_dict()` gives JSON with `schema_version` "crop_risk/1" and a `columns` block with the fixed column orders. The exact column lists are in `src/cropfit/risk.py` (`SUMMARY_COLUMNS`, `CONTRIBUTION_COLUMNS`, `SKIPPED_COLUMNS`):
  - summary: one row per unit × crop, with status `ok`, `no_knowledge`, `insufficient_depth` or `no_scored_genera`. `risk_from_detected` + `risk_from_not_detected` = `risk_index`.
  - contributions: one row per unit × crop × scored genus, with A, H and their inputs.
  - skipped: one row per unit × genus that could not be scored, with `reason`.
- A site-year without ITS data returns an empty result with `metadata.reason` (no exception).
- **Measured results (21 Nov 2026, default parameters):**

  | Site-year | Units | Product | Scored genera (max) | Units below floor | Smallest reference | Share of total from not-detected genera |
  |---|---|---|---|---|---|---|
  | KONA 2017 | 9 | .001 | 34 | 0 | 6 (all flagged small) | 31% |
  | KONA 2019 | 10 | .002 | 131 | 0 | 11 | 30% |
  | KONA 2024 | 10 | .002 | 165 | 0 | 10 | 17% |
  | STER 2016 | 22 (both products) | .001 + .002 | 89 | 3 | 11 | 39% |
  | STER 2017 | 10 | .001 | 28 | 0 | 13 | 29% |
  | STER 2022 | 10 | .002 | 136 | 0 | 9 (most flagged small) | 27% |

- **QC-passing cores after the .002 download and the 02b re-run (21 Nov 2026):** KONA 2017 28, KONA 2019 66, KONA 2024 89, STER 2016 27 (.001) / 10 (.002), STER 2017 42, STER 2022 86. These are slightly below the 3.2 table for STER 2016 and 2017; not investigated.
- **Pitfalls:**
  - Not-detected genera contribute their mid-rank percentile. With many genera tied at zero this is about 0.4 to 0.5 each, so a genus detected in one plot can still be a top contributor in the others. Example: Chalastospora at STER 2022 is detected in 1 of 10 units, with H = 2/3 from only 3 documented species. Read `risk_from_not_detected` next to `risk_from_detected`.
  - H from genera with few documented species is coarse (1/3, 2/3).
  - Totals are comparable only within one site and ITS product, because the set of scored genera differs.
  - No species synonymy. Fusarium's denominator includes old names (moniliforme, nivale), and dual names (Gibberella zeae = F. graminearum) count as two species.
  - JSON output is large (3.5 to 19 MB per site-year, mostly contributions, including H = 0 rows and `excluded_by_filter` rows). Use the parquet tables when you can.
  - The caveats in section 5 apply: relative abundance, genus level, and a host record means the fungus can infect the crop, not that it does in this field. Fungi only, no bacteria.
- **GUI:** the "Crop disease risk" tab shows these results per plot. The unit key is `YYYY-00N` (e.g. `2016-002`, one per ITS product). A plot is ranked only against plots of the same site, year and product. Comparing crops with each other mostly reflects how well each crop's diseases are documented, not soil risk.

### 3.13 Follow-up test suggestions (prototype)

- **What:** `followup.suggest(contributions, summary, unit_id, crop, context=...)` lists measurements that would close a gap in one crop's risk assessment, most useful first. API: `GET /api/plots/{plot}/crop-risk/{unit}/{crop}/tests`. GUI: the "What to test next" block under the breakdown in the "Crop disease risk" tab.
- **Triggers** (constants at the top of `src/cropfit/followup.py`):
  - `resolve_species`: a catalogued genus is detected, not weak, and A ≥ 0.75. ITS cannot tell its species apart.
  - `confirm_detection`: a catalogued genus is detected with ≤ 10 reads, or in one core when the unit has two or more.
  - `blind_spot`: oomycetes and nematodes, which no dataset here measures. Always listed for the crop; ranked higher when the row is `favoured_by` wet and the plot has `p_wet_may` ≥ 0.5 or a poorly drained map unit (from `plots.parquet`, optional).
  - `sampling`: the unit has one core (listed first), or is below the read floor (then it is the only suggestion).
- **Catalogue:** `rules/followup_tests.csv`, one row per test (`kind`, `genus`, `target`, `crops`, `disease`, `inoculum` soil or residue, `favoured_by`, `method`, `sample`, `tells_you`, `source`, `verified`). The 19 pathogen rows were written from general knowledge on 21 Nov 2026 and are **not verified** (`verified` = no; a unit test keeps that flag honest). Replace `source` with a citation and set `verified` = yes only after checking a row.
- **Priority** (0-1) only orders the list: A × (0.5 + 0.5 × log host records on the crop, scaled to the crop's maximum), × 0.8 for residue-borne diseases; half of that scale for weak detections; 0.35 for blind spots, + 0.25 on wet sites. The weights are not tuned.
- **Measured (21 Nov 2026, KONA 2017, KONA 2024, STER 2016, STER 2022):** 3.4 suggestions per unit × crop on average (1 to 8); soybean has the most (5.2), millet the fewest (2.2).
- **Limits:** no result thresholds; a suggestion means "this is unknown", not "disease is expected". Only genera in the catalogue can trigger a pathogen test. The triggers inherit the weaknesses of the risk score (3.12).

### 3.14 Microbe roles (LLM-annotated, POC)

- **What:** a GO-like role ontology for genera. It has 32 terms in a tree under five roots: useful, harmful, context (nitrogen cyclers), background and unknown. Each genus has zero or more role annotations (genus -> term, with confidence, evidence, source and named species examples), and one plain-language description for hover text. Files: `rules/microbe_ontology.csv`, `rules/microbe_annotations.csv`, `rules/microbe_genera.csv`. Code: `src/cropfit/microbe_roles.py` (contract: `docs/microbe_roles.md`).
- **Rank:** genus is the finest rank. The data has no species abundances, so species appear only as named examples (e.g. *Pseudomonas syringae*). One genus can have several roles.
- **How it was made:**
  - `scripts/17_export_microbe_taxa.py` (offline) writes `data/processed/microbe_taxa.csv`: 2,358 genera (1,095 bacteria, 96 archaea, 1,167 fungi).
  - Sonnet annotated all 2,358 genera blind, in 10 chunks, with `rules/microbe_annotation_prompt.md`. The chunks are in `data/annotation_chunks/` (gitignored). This is a manual step, not a script.
  - Opus reviewed 346 genera: every harmful genus and the 100 most abundant genera per group. Reviewed rows have `+reviewed` in `source`: 516 of 2,585 rows.
  - `scripts/18_merge_microbe_annotations.py` validates the chunks and the `review_*` overrides, merges them into the rules files, and prints coverage and the blind agreement with FUNGuild.
- **Fungi:** for the terms they cover, FUNGuild and FungalTraits override the LLM rows. The rules are in `docs/microbe_roles.md`, section 4. The curated rows are not written to `microbe_annotations.csv`; `microbe_roles.py` computes them on load.
- **Counted rows:** only `medium` and `high` confidence rows count. Low rows stay in the files for review and are ignored by every share, class and list.
- **Summary class:** each genus gets one class, with this precedence: mixed (useful and harmful terms) > harmful > useful > context > background > unknown. The six classes of a sample add up to 100% minus the reads without a genus name.
- **Quality, measured 21 Nov 2026, BLIND (before review):** LLM vs FUNGuild on 1,084 shared fungal genera.

  | Axis | Agreement | Cohen's kappa | Notes |
  |---|---|---|---|
  | Plant pathogen | 81.5% (read-weighted 74.6%) | 0.36 (read-weighted 0.51) | FUNGuild flags 274 genera, LLM 77. FUNGuild's "can be a plant pathogen" is much broader (e.g. Trichoderma, Cladosporium) |
  | Arbuscular mycorrhizal | 100% | 1.0 | |
  | Saprotroph / decomposer | 51.9% | 0.17 | The LLM used `decomposer` far less often |

  The blind comparison is saved to `data/processed/microbe_roles_agreement_blind.csv`.
- **Coverage after review** (share of reads, LLM rows only):
  - Bacteria and archaea: useful 15.6%, mixed 16.2%, potentially harmful 6.8%, nitrogen cyclers 1.9%, background 40.9%, role unknown 18.6%. Of the role unknown share, 4.5% of reads (587 genera) are probably misnamed reads: Kraken2 hits on marine, thermophile, gut or insect-symbiont genera.
  - Fungi: useful 8.0%, mixed 6.8%, potentially harmful 27.6%, background 51.0%, role unknown 6.6%.
- **Endpoints:**
  - `GET /api/microbiome/{sample_id}/roles`: the Roles view (`RoleComposition`).
  - `Taxon.description`: hover text at genus rank in the composition.
  - `/api/functions/{id}`: gains `carriers` ("who may carry it by name", per gene-backed role, with an agreement status) and a `bacteria_pathogens` card.

### 3.15 Product recommendations (prototype)

- **What:** `products.recommend(contributions, summary, unit_id, crop, signals=..., context=...)` lists product types worth considering for one crop on one unit, each with a timing (`before_planting` or `during_growth`), a reason, what it rests on and the follow-up tests that would confirm it. `products.unanswered(crop, signals, context)` lists the soil rules that could not be evaluated. API: `GET /api/plots/{plot}/crop-risk/{unit}/{crop}/products`. GUI: the "Treatment plan" tab (`web/src/features/plan/`), linked from the crop disease risk tab.
- **Triggers** (constants at the top of `src/cropfit/products.py`; the genus thresholds are those of 3.13):
  - `pathogen_high`: a catalogued genus is detected, not weak, and A ≥ 0.75. The item names the follow-up tests for that genus and crop.
  - `confirm_first`: the genus is detected weakly (≤ 10 reads, or one core of several). The item says to test before buying.
  - `site_favoured`: oomycete seed treatments, only when the row is `favoured_by` wet and the site is wet (as in 3.13). Nothing is recommended for an unmeasured organism otherwise. Nematodes have no product rows.
  - `soil_signal`: one of the rules in `SIGNAL_RULES`, on the `signals` dict: nitrate below 25 or 10 mg/kg (corn), C:N above 20, pH below 5.5, pH 5.5 to 6.0 (legumes), pH of 7.5 or more, organic carbon below 1%, urease genes found, the N2O flag of the soil functions view or nitrification genes on a wet site, a legume not in the crop history, copper resistance genes found, phlD found.
- **Signals** come from `api_functions.soil_signals(plot, year, dates)` and `api_risk._history_signals`: NEON soil measurements within 7 days of the fungal sample (else of the metagenome), the gene groups of the plot's metagenome of that year, `plot_crop_history` before that year and the Bradyrhizobium percentile of `plot_biology_timeseries`. A missing value gives no item; the rule is listed as not checked. Metagenomes exist for few years (3.1), and most are too shallow to read gene groups.
- **Catalogue:** `rules/products.csv`, one row per rule (`kind` pathogen, blind_spot or soil; `category`; `product_class`; `timing`; `stage`; `crops`; `genus`; `tests`; `signal`; `favoured_by`; `works_because`; `caution`; `source`; `verified`). Rows name active-ingredient groups with FRAC codes, never brands or rates. Category `no_product` says that no product works and what to do instead. All 29 rows were written from general knowledge on 21 Nov 2026 and are **not verified** (a unit test keeps the flag honest). Replace `source` with a citation and set `verified` = yes only after checking a row.
- **Priority** (0-1) only orders the list: for genera as in 3.13 without the residue factor (0.4 scale for weak detections, + 0.1 when the site favours the disease); 0.5 for `site_favoured`; a fixed strength per soil rule. The weights are not tuned.
- **Limits:** product groups follow US practice and registration was not checked for any country. The soil thresholds are copied from `api_functions.py` (a test keeps them equal). The nitrate rule uses whatever NEON measurement is nearest the fungal sample, which is often not the late-spring sample the 25 mg/kg level is calibrated for. Urease and copper genes are weak signals. Everything in 3.12 and 3.13 about genus-level detection applies.

### 3.16 KEGG modules and who carries which function (all KEGG genes, not only the panel)

- **Why:** `ko_panel` keeps 41 hand-picked KOs; a deep metagenome has about 6,000 distinct KOs (STER 2022: median 6,174 per metagenome, 8,205 over the site-year). These two tables use all of them.
- **KEGG modules** (`src/cropfit/kegg.py`, `scripts/19_build_kegg_modules.py`): 583 module definitions and the BRITE hierarchy `br:ko00002` from KEGG REST (free for academic use; cached in `data/cache/kegg/`). Each DEFINITION is parsed (space = step, `,` = alternative, `+` = complex member, `-` = optional member, `--` = step without a KO, `Mxxxxx` = another module) and scored per metagenome: completeness = steps with at least one KO copy / steps.
  - `kegg_modules.parquet`: `module, name, class_a, class_b, class_c, definition, n_steps`.
  - `kegg_module_completeness.parquet` (33,814 rows, 58 metagenomes): `metagenome_key, module, steps_found, n_steps, completeness, missing_steps, via_alias`.
  - Measured: deep STER 2022 metagenomes have a median of 197 complete modules; shallow ones 5-85, mostly a depth effect (check `metagenomes.ko_depth_ok`).
  - **KEGG renumbering:** NMDC annotated with the old K10944 "pmoA-amoA"; current KEGG uses K10944 for methane monooxygenase and K28504 for ammonia monooxygenase (`M00528`, `M00804`). `kegg.KO_ALIASES` lets K10944 satisfy K28504 and `via_alias` flags it; use `ko_taxa` to tell the two apart.
- **Gene phylogeny** (NMDC "Gene Phylogeny tsv", one per annotation run, same gene IDs as `ko.tsv`): closest reference genome, its lineage and % protein identity for every annotated gene. 58 files, 2.6 GB (deep 2022 files up to ~0.5 GB each). Download with `scripts/pull_nmdc_cropland.py --types kraken2 gottcha2 ko annotation_stats qc gene_phylogeny` (**keep the default types in the list**: `nmdc.object_paths()` only sees the types selected in the last pull).
  - `ko_taxa.parquet` (`src/cropfit/gene_taxa.py`, `scripts/20_build_gene_taxa.py`; 2.3 M rows, 58 metagenomes, ~1.5 min): `metagenome_key, ko, domain, phylum, class, order, family, genus, n_genes, identity_median`.
  - **Read the lineage as the closest known relative**, not the organism: median identity is ~70 %, so phylum or class is reliable and genus is a hint unless identity is high (e.g. nosZ matched to *Bradyrhizobium* at 97 %).
  - Example (STER_006, 2022): about 75 % of K10944 copies match ammonia-oxidising archaea (*Nitrososphaerota*, ~97 % identity) or *Nitrosomonadaceae*; the rest are actinobacterial monooxygenases (~72 %): mostly true nitrifiers.

### 3.17 Soil characteristics cards: reference colours and computed confidence

- **Reference:** gene cards compare the sample with the *other* well-sequenced metagenomes (`ko_depth_ok`; now 9, all STER). Per-genome values = KO copies / `marker_mean`.
- **Colour (gene cards):** only when the sample is above or below *every* reference soil (`_ref_colour` in `api_functions.py`): more N2O removers per N2O maker, P-freeing genes, stress-relief genes, breakdown routes -> green "More than usual" (yellow when below, except breakdown); copper-resistance genes above all -> yellow. Inside the range: no colour. The rule is listed in the card's "Numbers and rules".
- **Confidence** (`src/cropfit/confidence.py`): each card lists factors, each high/medium/low by fixed cut-offs, and takes the **weakest**. Cut-offs (high, medium) chosen from the data ranges:

  | Factor | Cards | High / medium | Data range seen |
  |---|---|---|---|
  | Gene copies in the weakest step of the pathways the headline names (KEGG modules, alternatives summed, K10944 counted for K28504) | gene cards | >=100 / >=20 | 1-511 |
  | Sequencing depth = `marker_mean` (genome equivalents) | gene cards | >=300 / >=100 | 55-843 in deep samples |
  | Median % identity behind "Who does it" | gene cards with who | >=75 / >=60 | 59-91 |
  | Reference size (one site caps at medium) | cards using the reference | >=20 / >=8 | 9 |
  | Days between NEON measurement and DNA sample | measured | <=2 / <=7 | 0-7 |
  | Cores / incubation pairs | measured | >=3 / >=2 | 1-3 |
  | Distance from the threshold (nitrate relative, pH units, organic carbon relative) | measured | 0.3 / 0.1; 0.5 / 0.2; 0.3 / 0.1 | |
  | Same cores; ITS reads; % reads named to a genus | fungi | same; >=20k / >=5k; >=70 / >=40 | 576-790k reads |
  | Bacterial reads; % reads classified by Kraken2 | bacteria names | >=5M / >=1M; >=50 / >=25 | 7-13 % classified |

  Method limits that do not change between samples (genes show capacity, not activity; guilds per genus) are stated in the card text, not counted as factors. The "unusual" headline names a pathway only if its weakest step has >= `MIN_COUNT` (5) copies.

## 4. Quick recipes

All snippets assume the repo root as the working directory and the venv. Prepend `import sys; sys.path.insert(0, "src")` if you have not installed the package.

**Soil for a lat/lon (SSURGO, about 3 s):**
```python
from cropfit import ssurgo
s = ssurgo.plot_soil(40.4652, -103.0321)   # modal mukey over 5 points
print(s["muname"], s["ph_surface"], s["clay_pct"], s["om_pct"], s["awc100_mm"], s["drainage_class"], s["mukey_share"])
```

**Daymet features for a point (about 3 s):**
```python
from cropfit import daymet
raw = daymet.fetch_daymet(40.4652, -103.0321, 2008, 2025)      # date, year, yday, tmax, tmin, prcp
yearly = daymet.yearly_climate(raw)                              # one row per year
feats = daymet.climate_features(40.4652, -103.0321, 2008, 2025)  # medians and probabilities
```

**CDL history for a point (2008-2021, about 14 s):**
```python
from cropfit import cdl
h = cdl.cdl_history(40.4652, -103.0321, range(2008, 2022))   # year, cdl_code, crop_group, share, edge
```

**CSB fields for a bbox (reads from the zip, no unzip):**
```python
import pyogrio
from pyproj import Transformer
from cropfit import cdl
src = "/vsizip/data/raw/csb/NationalCSB_2018-2025_rev23.zip/CSB1825.gdb"
crs = pyogrio.read_info(src, layer="national1825")["crs"]
lon0, lat0, lon1, lat1 = -103.05, 40.45, -103.00, 40.48
t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
xs, ys = zip(*[t.transform(x, y) for x, y in [(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)]])
g = pyogrio.read_dataframe(src, layer="national1825", bbox=(min(xs), min(ys), max(xs), max(ys)))
g["crop_2025"] = [cdl.crop_group(int(c)) for c in g["CDL2025"]]
```
For the two configured windows use `csb.load_window_fields("STER")` (first call clips and caches; needs the zip).

**KO counts per metagenome (processed tables, after `05_build_biology.py`):**
```python
import pandas as pd
from cropfit.config import PROCESSED
mg = pd.read_parquet(PROCESSED / "metagenomes.parquet")
ko = pd.read_parquet(PROCESSED / "ko_counts_all.parquet")           # long: metagenome_key, ko, count
wide = ko.pivot_table(index="metagenome_key", columns="ko", values="count", fill_value=0)
deep = mg.loc[mg.ko_depth_ok, "metagenome_key"]                      # passes the depth gate
wide_deep = wide.loc[wide.index.intersection(deep)]
```
From raw files instead: `from cropfit import nmdc as N; p = N.object_paths()[key]["Annotation KEGG Orthology"]; N.parse_ko_counts(p)`.

**ITS genus table per plot-date:**
```python
import pandas as pd
from cropfit.config import PROCESSED
its = pd.read_parquet(PROCESSED / "its_genus.parquet")
tab = its.pivot_table(index=["site", "plotID", "collectDate"], columns="genus",
                      values="rel_abund_pct", fill_value=0)          # % of fungal reads
tab.loc[:, ["Fusarium", "Macrophomina"]].head()
```

**Join NMDC metagenomes to NEON chemistry/qPCR by plot and date:**
```python
chem = pd.read_parquet(PROCESSED / "neon_chem.parquet")
mg["date"] = pd.to_datetime(mg["date"]).astype("datetime64[ns]")      # same dtype on both sides
chem["collectDate"] = pd.to_datetime(chem["collectDate"]).astype("datetime64[ns]")
j = pd.merge_asof(mg.sort_values("date"), chem.sort_values("collectDate"),
                  left_on="date", right_on="collectDate", by="plotID",
                  tolerance=pd.Timedelta("3D"), direction="nearest")
```

**Parse a sample name:** `from cropfit import nmdc as N; N.parse_sample_name("STER_006-M-21-20220607")`.

## 5. Honesty and caveats (please carry these into any prototype)

- **Relative abundance only.** Read shares and ITS shares are proportions of what was classified; they are not counts of organisms. The one scaled number (qPCR copies per ng DNA times ITS share) is approximate and labelled so.
- **Not detected does not mean absent.** Shallow sequencing, assembly misses and database gaps all produce zeros (nifH is the standing example). Show "not detected" or "insufficient depth", never "absent" or a zero percentile.
- **Genus level for fungi at best.** ITS genus assignments cannot separate pathogenic and benign species; the Kraken2 database has no fungi.
- **Pooled cores.** One metagenome represents up to three cores of one plot-date.
- **Percentiles need a reference set.** Within one site and year there may be only 8 deep metagenomes (STER 2022). All NMDC cropland samples at these sites are crop plots, so there is no non-crop reference.
- **NLCD 2001 plot labels are outdated** (`nlcd` in `resources/neon_soil_plots_landcover.csv`). Use crop maps (CDL, CSB) for what was actually grown.
- **Two NEON farm sites are not a generalisation** of US (or EU) agriculture. The LUCAS table is the only cross-site check here and it is EU, genus-level and relative.
- CSB and CDL carry no irrigation information; SSURGO is map-unit typical, not measured.
- **Microbe roles are per genus.** A role describes the typical genus, not the strains in the sample. A genus "with plant pathogens" (e.g. *Streptomyces* via *S. scabies*, *Pseudomonas* via *P. syringae*) mostly holds harmless or useful species. That is why the "Mixed" class exists.
- **LLM annotation can be wrong.** Only harmful and abundant genera had a second check, by an AI reviewer. No human expert has reviewed any of the roles.
- **Kraken2 genus calls on short reads can misplace reads**, especially into well-known pathogen genera. Small shares are noise.
- **Named carriers are capacity hints, not activity.** A genus listed as a possible carrier does not show that the function is active in this soil.
- When in doubt, look at the raw table, and say what you could not verify.
