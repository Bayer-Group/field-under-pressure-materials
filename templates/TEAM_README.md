# Team Misiaki – Field Under Pressure

**Track:** Weather risk  
**Event:** [Field Under Pressure](https://geo-hackathon.g.location360.ag/) · 20-22 Nov 2026

**Farmer101** is a web geoportal for farmers in Poland. It maps the agricultural drought hazard for spring wheat,
winter wheat, potato and corn, both for the whole country and for single cadastral parcels. It combines satellite
indices (Landsat 8/9, Sentinel-2), soil data (SoilGrids) and soil temperature and moisture (ERA5-Land), and it is
rebuilt automatically every day. Nothing to install: open the link in a browser.

## Team
| Name | Role | Contact |
|------|------|---------|
| Adrianna Wierzchoń | Team Leader  | aa.wierzchon@student.uw.edu.pl |
| Katarzyna Galewska | Team member | k.galewska@student.uw.edu.pl |
| Wiktoria Malinowska | Team member | wb.malinowsk@student.uw.edu.pl |
| Sebastian Jaśkiewicz | Team member | s.jaskiewic3@student.uw.edu.pl |
| Jacek Szczepaniak | Team member | j.szczepani7@student.uw.edu.pl |
## One-liner
Helps a grower decide whether to **sow / plant now or wait**, and whether to **irrigate or inspect a field**, by scoring
the agricultural drought hazard of their parcels for spring wheat, winter wheat, potato and corn.

## Problem & scope
- **Focus area:** agricultural drought (with cold soil at sowing time) for spring wheat, winter wheat, potato and corn,
  anywhere in Poland, down to single cadastral parcels.
- **In scope for the weekend:**
  - a web map on GitHub Pages, rebuilt every day by a GitHub Actions workflow;
  - map layers from Landsat 8, ERA5-Land and SoilGrids;
  - multi-criteria drought hazard maps for the four crops;
  - parcel analysis: hazard score and class, Combined Drought Indicator (CDI), a 10 m Sentinel-2 map inside each parcel
    and a 12-month timeline.
- **Explicitly out of scope:** yield forecasting, disease and pest risk, irrigation amounts and scheduling, field
  validation of the thresholds, crops other than the four above.

## Data we use
We did not use the organizers' S3 datasets; all data come from the public sources listed there.
- Weather: ERA5-Land / ERA5 reanalysis via Open-Meteo (soil temperature and moisture, precipitation, ET0);
  Open-Meteo forecast for the current weather
- Satellite: Landsat 8 Collection 2 Level 2 (map layers), Sentinel-2 L2A (parcel analysis), both via Microsoft
  Planetary Computer
- Soil: SoilGrids 2.0 (texture converted to Polish BN-78 groups, porosity)
- Cropland: no crop-type map; parcel outlines come from the Polish cadastre (GUGiK KIEG / ULDK)
- Notes / paths: no data files are committed. The workflow downloads the map data into `_dane/` and builds the site
  in `_site/`. Parcel data are downloaded in the browser. Details: [Map layers](#map-layers) and
  [Data sources](#data-sources).

## How to run
The published website needs nothing to install. To build it locally you need Python 3.12 and an internet connection:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python skrypty/gleba_mapa.py
python skrypty/landsat_mapa.py
python skrypty/era5_mapa.py
python skrypty/analiza_mapa.py
python skrypty/siatka.py
python skrypty/strona.py
cd _site && python
```

Then open http://localhost:8000. Do not open `index.html` by double-clicking it: the browser would then block loading the data.

Other options:
- `python skrypty/strona.py --jeden-plik` embeds the add-on and the data in `_site/index.html`, so that page can be
  opened by double-clicking.
- `pip install cryptography`, then `python skrypty/serwer_https.py`, serves `_site/` over HTTPS at
  https://localhost:8443 and at the computer's address on the local network. This makes, for example, the location
  button work on a phone. The certificate is created automatically in `_certyfikat/`.
- `python skrypty/susza.py --demo` runs the drought-probability analysis on synthetic data (needs
  `pip install xarray pandas scipy`). Without `--demo` it downloads ERA5-Land from the Copernicus CDS, which needs
  `pip install earthkit-data` and a CDS key in `~/.cdsapirc`. Results go to `skrypty/wyniki_susza/`.
  Options: `python skrypty/susza.py -h`.

The folders `.venv/`, `_dane/`, `_cache_gleba/`, `_site/`, `_certyfikat/` and `skrypty/wyniki_susza/` are created
locally. Do not commit them: on GitHub the workflow downloads the data and builds the site.

## Demo notes (Sunday)
- **What to show:**
  1. *Layers*: the drought hazard map of Poland for one crop, next to the NDDI (Normalized difference drought index) and soil type layers.
  2. *Final analysis*: select a few parcels, pick a crop and a date, click **Calculate**. Show the hazard score and
     class, the CDI level, the 10 m map inside the parcels and the 12-month timeline.
- **Key result / insight:** one drought score per parcel that combines a satellite drought index (NDDI), soil type,
  soil temperature and soil water. The national maps and the parcel analysis use the same thresholds.
- **Known limits / next steps:**
  - the map layers have about 500 m resolution and come from models (SoilGrids, ERA5), so they show the regional picture;
  - the thresholds come from expert tables and are not yet validated with field measurements or yields;
  - NNI is calibrated for winter wheat in China and is only indicative;
  - next: validation on real fields, a crop-type map, more crops.

## Links
- Repo: https://github.com/aawierzchon-ops/Farmer101
- Website: https://aawierzchon-ops.github.io/Farmer101/
- Slides / recording (if any):

---

## What is on the website

Collapsible panels in the lower-left corner (`+` / `-`):

| Panel | Contents |
|---|---|
| **Layers** | base maps (OpenTopoMap, ESRI Satellite), cadastral parcels (KIEG), analysis layers with legend and transparency slider (Landsat, ERA5-Land, soil), drought hazard maps for four crops |
| **Final analysis** | analysis of selected parcels: pick parcels on the map, a crop and a date, then **Calculate**. Result: hazard score and class I-IV, CDI drought level, a 10 m map inside each parcel and a 12-month timeline |
| **Detailed data** | after a calculation in “Final analysis”: every parameter separately, per parcel and as an area-weighted mean |

Also:
- **Click on the map** to open a popup with the parcel, the soil at that point and the current weather (Open-Meteo).
- **Search** finds addresses (Nominatim, OpenStreetMap) and parcels (ULDK GUGiK). Enter a parcel as a full identifier,
  e.g. `141201_1.0001.6509`, or as “precinct number”, e.g. `Zakrzew 10`.

---

## Repository layout

Code identifiers and comments are in Polish. Everything shown on the website is in English.

| Path | Contents |
|---|---|
| `mapa/` | qgis2web export (OpenLayers): `index.html`, `layers/`, `resources/`, `images/` (logo, favicon) |
| `mapa/resources/parcel-search.js` | address and parcel search, parcel popup |
| `mapa/resources/panel-warstw.js` | the **Layers**, **Detailed data** and **Final analysis** panels and the logo |
| `mapa/resources/analiza-cdi.js` | analysis of selected parcels: hazard score, CDI, 10 m map, timeline |
| `rolnik/rolnik.js`, `rolnik/rolnik.css` | analysis layers, legends, hazard maps, click popup; reads `rolnik/dane/meta.json` |
| `skrypty/siatka.py` | common map grid (EPSG:3857, 800 m pixels), writes PNG layers, merges descriptions into `meta.json` |
| `skrypty/gleba_mapa.py` | soil from SoilGrids 2.0: Polish texture groups (BN-78), porosity, bulk density |
| `skrypty/landsat_mapa.py` | Landsat 8/9 composite: NDVI, GNDVI, OSAVI, NDWI, NDDI, NNI, land surface temperature |
| `skrypty/era5_mapa.py` | ERA5-Land / ERA5 via Open-Meteo: soil temperature and moisture, 7-day precipitation |
| `skrypty/analiza_mapa.py` | multi-criteria analysis: hazard maps for each crop, criteria and thresholds for the website |
| `skrypty/strona.py` | builds the site from the qgis2web export, the `rolnik/` add-on and the data, into `_site/` |
| `skrypty/serwer_https.py` | local HTTPS server (e.g. for testing on a phone) |
| `skrypty/susza.py` | separate drought-probability analysis from ERA5-Land (Copernicus CDS); results go to files, not to the website |
| `.github/workflows/mapa.yml` | daily data download, site build and publication |
| `requirements.txt` | Python packages for the workflow |

---

## Map layers

Layers computed by the scripts have 800 m pixels in EPSG:3857, which is about 500 m on the ground in Poland.
They are stored as 8-bit PNG images described in `meta.json`.

| Source | Layers | Refresh |
|---|---|---|
| **Landsat 8/9** Collection 2 Level 2 (USGS, via Microsoft Planetary Computer) | NDVI, GNDVI, OSAVI, NDWI, NDDI, NNI, land surface temperature (LST) | daily; newest cloud-free pixel from the last 90 days, scenes with < 10% cloud |
| **ERA5-Land / ERA5** (Copernicus, via Open-Meteo) | soil temperature and moisture 0-7 cm (3-day mean), 7-day precipitation total | daily; the data lag about 5 days |
| **SoilGrids 2.0** (ISRIC) | soil type (20 BN-78 texture groups), porosity, sand, clay, bulk density | once (kept in the workflow cache) |
| **Multi-criteria analysis** (`analiza_mapa.py`) | drought hazard classes I-IV for spring wheat, winter wheat, potato and corn | daily |

### Reading the indices

Scales follow the Polish Space Agency (POLSA).

| Index | Range |
|---|---|
| NDVI, GNDVI, OSAVI, NDWI, NDDI | −1 - 1 |
| NNI | 0.7 - 1.3 |
| LST | 0 - 30 °C |

| Index | Value | Meaning |
|---|---|---|
| NDVI | ≈ −1 | water |
| NDVI | < 0 | water, built-up areas |
| NDVI | −0.1 - 0.1 | bare soil without vegetation |
| NDVI | < 0.2 | sparse vegetation in poor condition |
| NDVI | 0.2 - 0.4 | vegetation in an early growth stage or in weak condition |
| NDVI | > 0.6 | healthy vegetation with high vitality |
| NDVI | ≈ 1 | peak growth stage, very good condition |
| GNDVI | 0.5 - 0.8 | healthy plants |
| GNDVI | < 0.3 | strong stress |
| OSAVI | ≈ 0 | bare soil; the higher the value, the denser the plant cover |
| NDWI | > 0.4 | no drought |
| NDWI | 0.3 - 0.4 | slightly dry |
| NDWI | 0.2 - 0.3 | moderately dry |
| NDWI | 0.0 - 0.2 | very dry |
| NDWI | < 0 | extremely dry |
| NDDI | > 0.25 | drought, when at the same time NDVI < 0.5 and NDWI < 0.3; NDDI rises as drought gets more severe |
| NNI | ≤ 0.7 | strong nitrogen deficiency |
| NNI | 0.7 - 0.9 | nitrogen deficiency |
| NNI | 0.9 - 1.1 | optimum |
| NNI | 1.1 - 1.3 | nitrogen excess |
| NNI | ≥ 1.3 | strong nitrogen excess |
| LST | 2 °C classes from < 0 to > 30 °C | map legend only, no interpretation thresholds |

---

## Multi-criteria drought hazard analysis

The analysis estimates the **agricultural drought hazard** for four crops: spring wheat, winter wheat, potato and
corn. It has four criteria. Each criterion is assigned a hazard class I-IV, and each class gives points.
The total (**0-24 points**) gives the final class.

### Points per class

| Criterion | Class I | Class II | Class III | Class IV |
|---|---|---|---|---|
| NDDI | 0 | 2 | 4 | 6 |
| Soil type | 0 | 2 | 4 | 6 |
| Soil temperature | 0 | 2 | 4 | 6 |
| Soil water | 0 | 2 | 4 | 6 |

### Final classification

| Final class | Points | Meaning |
|---|---|---|
| **I - low** | 0-4 | No drought risk. Soil and vegetation are in good condition and crops have enough water. |
| **II - moderate** | 5-13 | Low drought risk. First signs of water shortage or a vulnerable soil, but crops are still coping. |
| **III - high** | 14-20 | Moderate drought risk. Several indicators point to water shortage; slower growth and lower yield are possible. |
| **IV - very high** | 21-24 | High drought risk. Nearly all indicators confirm severe water stress; significant yield losses are expected. |

### Criterion 1: NDDI (drought, Landsat)

The same thresholds apply to all crops.

| Class | NDDI | Meaning |
|---|---|---|
| I - low | < 0.1 | No drought. Crops have enough water; no action needed. |
| II - moderate | 0.1-0.3 | Low drought risk. First signs of water shortage; watch the weather and soil moisture. |
| III - high | 0.3-0.5 | Moderate drought risk. Plants lack water and growth slows; consider irrigation, especially in critical growth stages. |
| IV - very high | > 0.5 | High drought risk. Severe water stress and major yield losses are likely; act quickly and inspect the fields. |

### Criterion 2: Soil type

Soil types are grouped as follows (Polish BN-78 symbols in brackets):

| Group | Soil types |
|---|---|
| **A** | Sand, Fine sand, Loamy sand (pl, plp, ps, psp) |
| **B** | Sandy loam (pgl, pglp, pgm, pgmp) |
| **C** | Loam, Loamy very fine sand, Fine sandy loam, Silt (gl, glp, płg, płp, płz) |
| **D** | Silt loam, Clay loam, Clay, Silty clay, Heavy clay (gs, gsp, gc, gcp, płi, i, ip) |

| Crop | Class I | Class II | Class III | Class IV |
|---|---|---|---|---|
| Spring wheat | - | B | D | C, A |
| Winter wheat | - | B | C | D, A |
| Potato | - | D | C | B, A |
| Corn | - | B | D | C, A |

Sands (group A) are in class IV for every crop: they hold little water, it drains away fast, and crops suffer even
after short dry spells. No soil type is in class I.

### Criterion 3: Soil temperature 0-7 cm [°C] (ERA5-Land)

| Crop | Class I | Class II | Class III | Class IV |
|---|---|---|---|---|
| Spring wheat | ≥ 6 | 4-6 | 3-4 | < 3 |
| Winter wheat | 12-25 | 8-12 | 4-8 | < 4 |
| Potato | ≥ 8 | 6-8 | 4-6 | < 4 |
| Corn | ≥ 10 | 8-10 | 6-8 | < 6 |

For winter wheat, temperatures above 25 °C are not covered by the table; the code puts them in class II.

**Spring wheat**

| Class | °C | Meaning |
|---|---|---|
| I - low | ≥ 6 | Favourable: warm enough for germination and emergence. No action needed. |
| II - moderate | 4-6 | Moderately cool: germination and emergence may take longer. Check the soil before sowing. |
| III - high | 3-4 | Cold: emergence may be much delayed and uneven. Consider waiting. |
| IV - very high | < 3 | Very cold: poor germination and early growth. Avoid sowing if possible. |

**Winter wheat**

| Class | °C | Meaning |
|---|---|---|
| I - low | 12-25 | Favourable for growth and root development. No action needed. |
| II - moderate | 8-12 | Cooling soil may slow root development and growth. Monitor the crop and the soil temperature. |
| III - high | 4-8 | Cold: establishment may be delayed and uneven. Consider waiting for warmer soil. |
| IV - very high | < 4 | Very cold: root activity and growth are strongly reduced; the crop may stay largely dormant. |

**Potato**

| Class | °C | Meaning |
|---|---|---|
| I - low | ≥ 8 | Favourable for planting, sprouting and emergence. No action needed. |
| II - moderate | 6-8 | Relatively cool: sprouting and emergence may slow down. Check the soil before planting. |
| III - high | 4-6 | Cold: sprouting and emergence may be delayed; risk of poor establishment. Consider waiting. |
| IV - very high | < 4 | Very cold: unfavourable for planting; postpone it if possible. |

**Corn**

| Class | °C | Meaning |
|---|---|---|
| I - low | ≥ 10 | Favourable for germination and establishment. No action needed. |
| II - moderate | 8-10 | Germination may start, but emergence may be slower and less even. Check the soil before sowing. |
| III - high | 6-8 | Cold: germination, emergence and early growth may be delayed. Consider waiting. |
| IV - very high | < 6 | Very cold: germination is very slow and uneven. Postpone sowing if possible. |

### Criterion 4: Soil water [%]

Share of soil pores filled with water: ERA5-Land soil moisture 0-7 cm (m³/m³) divided by the soil porosity from
SoilGrids. More water means a lower drought hazard.

| Crop | Class I | Class II | Class III | Class IV |
|---|---|---|---|---|
| Spring wheat | > 75 | 55-75 | 30-55 | < 30 |
| Winter wheat | > 70 | 45-70 | 25-45 | < 25 |
| Potato | > 80 | 65-80 | 35-65 | < 35 |
| Corn | > 75 | 50-75 | 30-50 | < 30 |

| Class | Meaning |
|---|---|
| I - low | Low drought hazard. Water is generally sufficient; no action needed. |
| II - moderate | Moderate drought hazard. Water may run short in long dry or hot spells; monitor soil moisture and the weather. |
| III - high | High drought hazard. Water shortage may slow growth; monitor closely and consider irrigation. |
| IV - very high | Very high drought hazard. |

### Reference tables (not scored directly)

**Total porosity and soil type.** Porosity is not a separate criterion; it is used to compute soil water (criterion 4).

| Total porosity [%] | Soil types | Drought susceptibility |
|---|---|---|
| < 40 | Sand, Fine sand, Loamy sand | Very high: little water is held and it drains quickly. |
| 40-45 | Sandy loam | High: limited water storage; regular rain or irrigation needed. |
| 45-50 | Loam, Loamy very fine sand, Fine sandy loam, Silt | Moderate: copes with short dry spells, but not with long ones. |
| > 50 | Silt loam, Clay loam, Clay, Silty clay, Heavy clay | Low: holds a lot of water and releases it slowly; crops are most drought-resistant. |

**KBW (climatic water balance).**

| KBW | Drought risk |
|---|---|
| < −0.1 | high |
| −0.1 - 0.1 | low |
| > 0.1 | none |

The CDI in the parcel analysis computes KBW in mm (precipitation − ET0) and compares it with the drought thresholds of
the Polish regulation Dz.U. 2019 poz. 739 (see below).

### Rules

- A value equal to a threshold belongs to the range that starts at that value.
- Where NDDI is missing (bare soil with NDVI < 0.2, or clouds), the score from the other three criteria is scaled to 24 points.
- All thresholds and points are defined in one place: at the top of `skrypty/analiza_mapa.py` (`KRYTERIA`,
  `KLASY_ZAGROZENIA`). The script writes them into `meta.json`, so the hazard maps and the parcel analysis in the
  browser always use the same thresholds.

---

## Parcel analysis (Final analysis)

1. Click **Select parcels**, then click parcels on the map. Click a parcel again to remove it. Parcel outlines come from ULDK GUGiK.
2. Pick a crop and an analysis date (from 2019 to today), then click **Calculate**.

For each parcel the browser downloads:
- **ERA5 / ERA5-Land** (Open-Meteo, daily data since 1991): precipitation, reference evapotranspiration (ET0),
  soil moisture 0-7 cm and 0-100 cm, soil temperature 0-7 cm;
- **Sentinel-2 L2A** (Planetary Computer): NDVI, NDWI and NDDI inside the parcel outline over the 60 days before the
  analysis date, and over the same weeks in every year since 2018 (for the NDDI anomaly);
- **soil** from the map layers: the dominant soil type and the mean porosity from up to 25 points inside the parcel.

### Results

- **Hazard score and class I-IV** from the criteria above. With several parcels, an area-weighted mean is also shown.
- **CDI** (Combined Drought Indicator): the European Drought Observatory scheme, with NDDI instead of fAPAR.
  - *Watch*: any of SPI-3 < −1, SPI-1 < −2, or a climatic water balance (KBW) below the drought threshold of the
    Polish regulation (Dz.U. 2019 poz. 739). That threshold depends on the crop and the soil category.
  - *Warning*: Watch and SMA < −1.
  - *Alert*: Warning and an NDDI anomaly > +1. The anomaly is computed only in April-September, with NDVI ≥ 0.3 and
    at least 3 years of history.
- **Within-parcel map**: about 10 m pixels from the median of the 3 newest cloud-free Sentinel-2 scenes. Each pixel has
  its own NDDI; the other criteria are shared by the whole parcel.
- **Timeline** (*Load timeline* button): every 10 days over the 12 months before the analysis date. It shows the hazard
  score, NDDI, NDVI, soil water, soil temperature, KBW, SPI-1, SPI-3 and SMA. Loading takes 0.5-2 minutes.

### Supporting indicators

- **SPI-1 / SPI-3**: 30-day / 90-day precipitation total compared with the same periods since 1991 (gamma distribution).
- **SMA**: soil moisture anomaly from the 10-day mean of soil moisture 0-100 cm.
- **KBW**: precipitation − ET0 over the last completed 60-day period of the season (21 March - 30 September).

---

## Publishing on GitHub

The `mapa.yml` workflow runs:
- every day at 3:37 UTC;
- on every push to `main` that changes `mapa/`, `rolnik/`, `skrypty/` or the workflow;
- manually: *Actions → Map → Run workflow*.

Steps:
1. Install the packages from `requirements.txt`.
2. **Soil** (`gleba_mapa.py`). It is computed only when `gleba_mapa.py` or `siatka.py` has changed; otherwise the
   ready files are taken from the cache.
3. **Landsat** (`landsat_mapa.py`) and **ERA5** (`era5_mapa.py`).
4. **Multi-criteria analysis** (`analiza_mapa.py`).
5. **Site build**: `siatka.py --polacz` creates `meta.json`, then `strona.py` builds `_site/`.
6. Publish `_site/` to GitHub Pages.

First-time setup: *Settings → Pages → Build and deployment → Source: **GitHub Actions***.

---

## When changing the code

- **Script names** appear in `mapa.yml`. If you rename a file, change it there too. GitHub is case-sensitive.
- **Change the multi-criteria thresholds** only in `skrypty/analiza_mapa.py`. The website reads them from `meta.json`.
- **Changing `gleba_mapa.py` or `siatka.py`** forces the soil to be recomputed from SoilGrids, so that run takes longer.
- **After editing a file in `mapa/resources/`**, raise its `?v=…` number in `mapa/index.html`. Otherwise browsers may
  keep using the old cached copy.

---

## Methods

- **BN-78 texture groups** (PN-BN-78/9180-11, Feret triangle): USDA fractions from SoilGrids converted to the Polish
  fraction limits.
- **Porosity**: Saxton & Rawls (2006) pedotransfer function, from texture and organic matter (C × 1.724).
- **NDVI**, **GNDVI** (Gitelson et al. 1996), **OSAVI** (Rondeaux et al. 1996), **NDWI** (Gao 1996),
  **NDDI** (Gu et al. 2007).
- **NNI** = 1.01 · EVI + 0.28 (Zhao et al. 2021). The model was calibrated for winter wheat in China, so treat the
  result as indicative.
- **CDI**: European Drought Observatory scheme. **KBW** thresholds: Dz.U. 2019 poz. 739. **SPI**: gamma distribution.

**Limitations:** the map layers have about 500 m resolution and come from models (SoilGrids, ERA5). They show the
regional picture but do not replace soil tests from a specific field.

---

## Data sources

- **Landsat 8**: Microsoft Planetary Computer
- **Sentinel-2 L2A**: Copernicus / ESA, via Microsoft Planetary Computer
- **ERA5, ERA5-Land**: Copernicus Climate Change Service
- **SoilGrids 2.0**: ISRIC (CC BY 4.0)
- **Parcels**: GUGiK
- **Address search**: Nominatim, © OpenStreetMap contributors
- **Base maps**: OpenTopoMap, Esri World Imagery
- **Map**: QGIS + qgis2web, OpenLayers
