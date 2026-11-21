# Feature contract (shared by all modules)

> Column dictionary for the per-unit processed tables (`plots.parquet`, `fields.parquet`, `plot_biology*.parquet`, `plot_its*.parquet`). See `AGENT.md` for how each table is produced. Crop-group names and the "unit" concept come from the prototype that wrote this contract (a unit is a NEON plot or a CSB field).

Every unit (a NEON plot or a CSB field) becomes one row with these columns. Producers must use exactly these names. Missing → NaN, never 0.

## Keys
| column | type | notes |
|---|---|---|
| `unit_id` | str | NEON `plotID` (e.g. `STER_026`) or `CSB_<CSBID>` |
| `unit_type` | str | `plot` or `field` |
| `site` | str | `STER` / `KONA` (window or NEON site) |
| `lat`, `lon` | float | WGS84 centroid |

## Soil (SSURGO via SDA; dominant major component, surface horizon unless noted)
| column | unit | source column |
|---|---|---|
| `mukey`, `muname`, `compname` | – | mapunit / component |
| `mukey_share` | 0–1 | share of sample points (plots) or field area (fields) in the dominant mukey |
| `ph_surface` | pH 1:1 H2O | `chorizon.ph1to1h2o_r`, hzdept_r = 0 |
| `clay_pct` | % | `claytotal_r` |
| `om_pct` | % | `om_r` |
| `caco3_pct` | % | `caco3_r` (NaN when not reported; treat NaN as 0 only for the IDC rule, and say so) |
| `ec_dsm` | dS/m | `ec_r` |
| `awc100_mm` | mm | Σ `awc_r` (cm/cm) × horizon thickness (cm) × 10, for horizons clipped to 0–100 cm |
| `drainage_class` | str | `component.drainagecl` (e.g. "Well drained", "Poorly drained") |

## Climate (Daymet 2008–2025, per pixel; summarise per year, then median over years)
| column | definition |
|---|---|
| `gdd10_may_sep` | Σ over 1 May–30 Sep of max(0, (min(tmax,30) + max(tmin,10))/2 − 10), °C·d, median |
| `frost_free_days` | days between last spring (before 1 Jul) and first fall (after 1 Jul) tmin ≤ 0 °C, median |
| `prcp_apr_sep_mm` | median Apr–Sep precip |
| `prcp_oct_jun_mm` | median Oct(prev yr)–Jun precip (winter wheat season) |
| `prcp_may_mm` | median May precip |
| `hot_days_jul_aug` | median count of Jul–Aug days with tmax ≥ 35 °C |
| `p_wet_may` | share of years with May precip > 100 mm |
| `p_hot_dry_jul_aug` | share of years with ≥ 15 Jul–Aug days tmax ≥ 35 °C AND Jul–Aug precip below that pixel's 25th percentile |
| `p_june_heat` | share of years with ≥ 5 June days tmax > 32 °C |
| `water_supply_summer_mm` | `prcp_apr_sep_mm + awc100_mm` |
| `water_supply_winter_mm` | `prcp_oct_jun_mm + awc100_mm` |

Function contract in `src/cropfit/daymet.py`:
- `fetch_daymet(lat, lon, start_year, end_year) -> pd.DataFrame` with columns `date, year, yday, tmax, tmin, prcp` (cached on disk).
- `yearly_climate(df) -> pd.DataFrame` with one row per year.
- `climate_features(lat, lon, start_year=2008, end_year=2025) -> dict` returning the columns above (minus the water-supply columns, which need soil).

## Rotation (crop groups via `rules/cdl_codes.csv`)
| column | notes |
|---|---|
| `crop_2008` … `crop_2025` | crop group per year (plots: CDL 2008–2021 via Planetary Computer + CSB 2018–2025; fields: CSB 2018–2025 only) |
| `crop_t1` … `crop_t5` | the same, relative to the planning year 2026 (t1 = 2025) |
| `history_source` | `csb`, `cdl`, or `csb+cdl` |

Crop group vocabulary (exact strings): `corn, soybean, winter_wheat, spring_wheat, sorghum, sunflower, alfalfa, millet, dry_bean, barley_oats, other_crop, fallow, grass_pasture, noncrop, double_wheat_soy, unknown`.

## Biology (plots only; NaN for fields)
| column | notes |
|---|---|
| `bio_metagenome_date` | date of the latest metagenome used |
| `bio_ko_depth_ok` | bool: ≥ 50k annotated genes and marker mean ≥ 20 |
| `bio_pct_<group>` | functional-potential percentile within site-year (groups: `nitrification, denitrification, nosZ, p_mobilisation, n_fixation, phlD, acdS, chitinase`), only when depth_ok |
| `bio_status_<group>` | `ok` / `insufficient_depth` (metagenome below depth gate) / `not_detected` (0 genes in the whole site-year reference set, e.g. phlD) / `too_few_genes` (<20 genes summed over the reference set, e.g. n_fixation). Percentile is NaN unless `ok`. Never render `not_detected` as "absent". |
| `bio_genus_pct_<Genus>` | read share percentile (Kraken2, % of bacterial reads) within site-year, e.g. `Bradyrhizobium` |
| `bio_its_pct_<Genus>` | NEON ITS genus relative-abundance percentile within site (2016-2024; mixes ITS pipelines DP1.10081.001 and .002, see AGENT.md 3.2), e.g. `Fusarium, Macrophomina, Gaeumannomyces, Rhizoctonia, Sclerotinia` |
| `bio_its_detected_<Genus>` | bool |
