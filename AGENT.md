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
.venv/bin/python -m pytest -q          # 14 tests, no network, no data needed
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
| `e1.py` | Open-Meteo / NASA POWER climate for EU points, plus modelling helpers used by the LUCAS experiment (needs scikit-learn). |

Lookup tables in `rules/` (generic, read by the code): `cdl_codes.csv` (all 132 CDL codes to a crop-group vocabulary), `ko_panel.csv` (KEGG KOs of interest with function group and caveat), `lucas_lc1_groups.csv` (LUCAS land-cover codes with `is_cereal`; documentation only, `e1_match.py` hard-codes its own cereal rule B11-B19). Small input tables in `resources/` are listed under each dataset.

### Where things land (all gitignored except `resources/`, `rules/`, `config/`)

```
data/nmdc/            samples.csv, data_objects.csv, objects/<data_object_id>/{ko.tsv,kraken2_report.tsv,...}
data/raw/neon/<DPID>/ NEON tables as parquet
data/raw/csb/         NationalCSB_2018-2025_rev23.zip (you place it here)
data/raw/lucas/       lucas_harmo_uf.zip and a slimmed CSV (you create it)
data/cache/<ns>/      http.cached() JSON/text: sda/, daymet/, openmeteo_e1/, power_e1/
data/processed/       parquet outputs of scripts 02b-05
```

Pipeline order (what produces what):

| Step | Command | Output |
|---|---|---|
| NMDC download | `scripts/pull_nmdc_cropland.py` | `data/nmdc/` |
| NEON download | `scripts/02_fetch_neon.py` (needs token) | `data/raw/neon/` |
| NEON tables | `scripts/02b_build_neon_features.py` (offline) | `its_core_genus`, `its_genus`, `plot_its*`, `neon_metagenome_pooling`, `neon_chem`, `neon_qpcr` |
| Plot tables | `scripts/03_build_plots.py` | `plots`, `plot_crop_history`, `plot_climate_yearly` |
| Field tables | `scripts/04_build_fields.py` (needs CSB zip) | `fields`, `plot_csb`, `csb_raw_<site>` |
| NMDC tables | `scripts/05_build_biology.py` (offline) | `metagenomes`, `ko_*`, `taxa_genus`, `plot_biology*` |
| Joined table | `scripts/06_build_joined.py` (offline, after 02b and 05) | `joined_metagenomes`, `joined_fungi_genus` (see 3.8) |

Note: `03_build_plots.py` and `04_build_fields.py` carry the `window`/`plot` selection logic of the original prototype (the 44 NEON "cultivatedCrops" plots; the two windows in `config/regions.yaml`). To reuse them elsewhere, edit `config/regions.yaml` and the plot filter in `03_build_plots.py`.

---

## 1. Keys, secrets and what never goes into git

- **Only one key is needed: the NEON API token.** Put it in a gitignored `.env` as `NEON_API_TOKEN=...` (template: `.env.example`; `NEON_TOKEN` is accepted as a fallback name). Since June 2026 the NEON portal calls in this repo need it. Never paste it in chat, logs or commits. `neon.get_token()` loads it via python-dotenv.
- **Everything else is keyless:** NMDC, SSURGO/SDA, Daymet, Planetary Computer CDL (anonymous signed URLs via the `planetary-computer` package), CSB and CDL downloads from USDA, NASS, JRC LUCAS, GlobalFungi table, Open-Meteo, NASA POWER.
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
  - `taxa_genus.parquet`, 67,237 rows: `metagenome_key, source (kraken2|gottcha2), genus, reads, pct_of_bacteria, filtered` (59 Kraken2 metagenomes, 46 GOTTCHA2).
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
- **Download:** `.venv/bin/python scripts/02_fetch_neon.py [DPID ...]` (default: DP1.10081.002, DP1.10081.001, DP1.10109.001, DP1.10086.001). Raw tables land as parquet under `data/raw/neon/<DPID>/<table>.parquet`; for each ITS product the script then downloads **every** per-sample ITS CSV (all runs of re-sequenced samples, 8 threads; 275/275 for .002 and 321/321 for .001, measured), keeps taxonomy and counts only, and writes `mct_soilPerSampleTaxonomy_ITS.parquet` / `mcc_soilPerSampleTaxonomy_ITS.parquet`. Failed downloads are listed by file name.
- **Size and time:** raw parquet is small (a few MB). The full pull took a few minutes on 21 Nov 2026 (not timed precisely).
- **Processing:** `scripts/02b_build_neon_features.py` (offline).
  - `neon.load_its_raw()` combines both ITS products and keeps **one run per DNA sample**: the deepest run within a product (NEON re-sequenced some samples), then .002 over .001 when a sample is in both (14 cores in STER 2016).
  - `neon.parse_sample_id` accepts IDs with one or two depth fields (from 2022 on NEON IDs have one, e.g. `KONA_001-M-21-20240409-GEN-DNA1`; the earlier regex silently dropped all 2022 and 2024 samples).
- **Processed outputs:**
  - `its_core_genus.parquet` (long, one row per core and genus): `site, plotID, horizon, collectDate, soilSampleID` (core, equals the NMDC biosample name)`, dnaSampleID, product, sequenceCountQF, genus, reads, total_reads` (fungal reads of the core)`, share_pct`. All cores, QC flag kept. Fungal reads without a genus are kept as `unclassified_Fungi`.
  - `its_genus.parquet` (long): `site, plotID, collectDate, year, dnaSampleID (semicolon-joined cores), n_cores, product, genus, reads, total_reads, rel_abund_pct, its_below_threshold_share`. **Only cores passing NEON's read check** (`sequenceCountQF != "Below threshold"`; `neon.build_its_genus(..., qc_ok_only=False)` keeps all). `rel_abund_pct` is the **mean of per-core shares** (each core weighs equally, like the equal-mass cores in a composite), not pooled reads, so one deep core cannot dominate. `reads` and `total_reads` are sums over the included cores (fungal reads only). Zero rows are added for the 18 genera in `neon.GENERA` so detection frequency is defined.
  - `plot_its_timeseries.parquet` (149 rows) and `plot_its.parquet` (latest per plot, 26 rows), wide: `bio_its_share_<Genus>`, `bio_its_detected_<Genus>`, `bio_its_pct_<Genus>` (percentile within site), plus a `Rhizoctonia_complex` (Rhizoctonia + Thanatephorus + Ceratobasidium). Percentiles now span both pipelines: compare with care.
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
- When in doubt, look at the raw table, and say what you could not verify.
