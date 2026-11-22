# 🗺️ Register of Polish and European Public Spatial Data (GIS)

> A complete knowledge base of official, open national registers, network services (WMS, WFS, WCS, REST API) and remote sensing sources useful in advanced spatial, environmental, infrastructure and hydrological analyses in Poland.  
> Source table file: [`polskie_rejestry_publiczne_gis.csv`](polskie_rejestry_publiczne_gis.csv).

---

## 📑 Table of Contents and Source Categories

1. [Cadastre, Administrative Boundaries and Land Records](#1-cadastre-administrative-boundaries-and-land-records)
2. [Digital Terrain Models, LiDAR and Photogrammetry](#2-digital-terrain-models-lidar-and-photogrammetry)
3. [Topography, Networks and Infrastructure](#3-topography-networks-and-infrastructure)
4. [Meteorology, Climate and Weather Radars](#4-meteorology-climate-and-weather-radars)
5. [Water, Hydrography and Flood Hazard](#5-water-hydrography-and-flood-hazard)
6. [Soil Science, Geology and Mass Ground Movements](#6-soil-science-geology-and-mass-ground-movements)
7. [Environmental Protection and Air Quality Monitoring](#7-environmental-protection-and-air-quality-monitoring)
8. [Satellite Remote Sensing (Copernicus & Landsat)](#8-satellite-remote-sensing)
9. [Socio-Economic Statistics (GUS BDL)](#9-socio-economic-statistics)

---

## 1. Cadastre, Administrative Boundaries and Land Records

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **ULDK GUGiK** *(Cadastral Parcel Location Service)* | REST API (WKT, GeoJSON, GML) | `https://uldk.gugik.gov.pl/` | Instant retrieval of cadastral parcel geometries and boundaries in EPSG:2180 by TERYT code or clicked XY point. |
| **KIEG** *(National Integration of Land Records)* | WMS, WFS | `https://integracja.gugik.gov.pl/.../KrajowaIntegracjaEwidencjiGruntow` | Aggregated parcel boundaries, cadastral numbers, classification contours and land use types from all counties in Poland. |
| **PRG** *(National Boundary Register)* | WFS, GML, SHP, GeoPackage | `https://geoportal.gov.pl`, WFS GUGiK | Official territorial division of Poland: boundaries of the country, voivodeships, counties, municipalities and cadastral districts. |
| **EMUiA** *(Addresses and Streets)* | WMS, WFS, CSV | `https://integracja.gugik.gov.pl/.../KrajowaIntegracjaNumeracjiAdresowej` | Point database of all address numbers and street centrelines in Poland (geocoding). |
| **PRNG** *(Register of Geographical Names)* | GML, SHP, GeoPackage, CSV | `https://dane.gov.pl` | Standardized names of localities, rivers, lakes, mountain ranges and forests. |
| **BDOO** *(General Geographic Objects Database)* | Shapefile, GeoPackage | `https://dane.gov.pl` | Vector general-geographic map at 1:250,000 scale for the whole country. |
| **LPIS / ARiMR Reference Parcels** | WMS, WFS, SHP, GPKG | `https://geoportal.gov.pl`, `https://dane.gov.pl` | Boundaries of reference blocks and parcels in the land records and area-based payments. |
| **Corine Land Cover (CLC 2018/2024)** | GeoPackage, SHP, GeoTIFF | `https://clc.gios.gov.pl` | European land cover and land use classification (44 classes) for the whole of Poland. |
| **Urban Atlas (Copernicus CLMS)** | Shapefile, GeoPackage | `https://land.copernicus.eu` | High-resolution land use classification for urban functional areas (FUA). |

---

## 2. Digital Terrain Models, LiDAR and Photogrammetry

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **NMT GUGiK (1 m grid)** | WCS, WMS, GeoTIFF, ASCII GRID | `https://mapy.geoportal.gov.pl/.../DigitalTerrainModel` | High-resolution elevation model from airborne laser scanning (LiDAR 1x1 m): slopes, aspects, closed terrain depressions, the TWI index (*Topographic Wetness Index*). |
| **NMPT GUGiK (Land Cover Surface)** | WCS, WMS, GeoTIFF | `https://mapy.geoportal.gov.pl/.../DigitalSurfaceModel` | Elevation model including objects above the terrain: buildings, forests, tree cover (wind barrier effect, shading, ventilation corridors). |
| **LiDAR Point Clouds (LAS/LAZ)** | LAS, LAZ | `https://geoportal.gov.pl` (PZGiK indexes) | True point clouds from airborne scanning (density 4–12 points/m²) with classification of ground, buildings and low/medium/high vegetation. |
| **Copernicus DEM (GLO-30)** | Cloud Optimized GeoTIFF (COG) | AWS Open Data, Copernicus Space Data | Uniform 30 m elevation raster for the whole of Europe for macro-regional analyses. |
| **GUGiK Aerial Orthophotomap (RGB/CIR)** | WMS, WMTS, WCS, GeoTIFF | `https://mapy.geoportal.gov.pl/.../StandardResolution` | Aerial photogrammetry with a 5–25 cm pixel in natural colours and near infrared. |

---

## 3. Topography, Networks and Infrastructure

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **BDOT10k (Topographic Objects)** | WFS, GML, GeoPackage, SHP | `https://geoportal.gov.pl`, WFS GUGiK | Equivalent of the 1:10,000 topographic map: network of roads, watercourses, buildings, drainage ditches, fences. |
| **GESUT (Utility Networks)** | WMS | `https://integracja.gugik.gov.pl/.../KrajowaIntegracjaUzbrojeniaTerenu` | Routes of water supply, sewage, gas, power and telecommunications networks. |
| **OpenStreetMap Poland (Geofabrik)** | PBF, Shapefile (SHP) | `https://download.geofabrik.de/europe/poland.html` | Full OpenStreetMap vector database for Poland with daily updates. |
| **GDDKiA (Average Daily Traffic)** | Shapefile, WMS, CSV | `https://www.gov.pl/web/gddkia` | Geometry of national roads and motorways together with vehicle traffic intensity (General Traffic Measurement). |

---

## 4. Meteorology, Climate and Weather Radars

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **IMGW-PIB Synoptic Data** | REST API (JSON, CSV, XML) | `https://danepubliczne.imgw.pl/api/data/synop` | Current (hourly) readings from synoptic stations in Poland: air temperature, precipitation, humidity, wind, pressure. |
| **IMGW-PIB Meteorological Data** | REST API (JSON, CSV) | `https://danepubliczne.imgw.pl/api/data/meteo` | 10-minute telemetry from automatic stations: ground temperature (5 cm), 10-minute precipitation. |
| **IMGW-PIB Meteo/Hydro Warnings** | REST API (JSON, GeoJSON) | `https://danepubliczne.imgw.pl/api/data/warnings/meteo` | Active meteorological alerts for counties (frost, storms, hail, heat waves, gales). |
| **IMGW-PIB Historical Data** | CSV (ZIP packages) | `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/` | Multi-decade daily and term archives for calibrating climate models and trend analyses. |
| **POLRAD IMGW (Radar Network)** | WMS, GeoTIFF, HDF5 | `https://danepubliczne.imgw.pl`, WMS IMGW | Maps of radar reflectivity and precipitation intensity every 5–10 minutes (detection of storm cells and hail). |
| **Open-Meteo Weather & Soil API** | REST API (JSON, CSV) | `https://api.open-meteo.com/v1/forecast` | Free hourly forecasts at 2 km resolution: temperature, wind, soil profile moisture (0–54 cm). |
| **ERA5-Land Reanalysis (ECMWF)** | NetCDF, GRIB | `https://cds.climate.copernicus.eu` | Global reanalysis of land and hydrometeorological parameters on a 9 km grid since 1950. |

---

## 5. Water, Hydrography and Flood Hazard

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **MPHP (Hydrographic Division Map)** | WFS, Shapefile, GeoPackage | `https://dane.gov.pl`, Wody Polskie | Basic hydrographic division of the country: catchment boundaries, watersheds, river axes and lakes. |
| **Hydroportal / ISOK (Flood Maps)** | WMS, WFS, Shapefile | `https://wody.isok.gov.pl` | Flood zones for flood probabilities of 10% (once in 10 years), 1% (once in 100 years) and 0.2%. |
| **IMGW-PIB Hydrological Data** | REST API (JSON, CSV) | `https://danepubliczne.imgw.pl/api/data/hydro` | Water levels and flows at river gauging stations across Poland in real time. |
| **GIOŚ Water Quality Monitoring** | REST API, CSV, Shapefile | `https://wody.gios.gov.pl` | Physicochemical and biological measurements of surface and groundwater. |

---

## 6. Soil Science, Geology and Mass Ground Movements

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **SMSR IUNG-PIB (Drought Monitoring)** | WMS, CSV, Tables | `https://susza.iung.pulawy.pl/` | Ten-day Climatic Water Balance (KBW) and water deficit indicators by municipality. |
| **Soil and Agricultural Maps (IUNG/WODGiK)** | WMS, WFS, SHP, GPKG | `https://geoportal.gov.pl` | Soil agricultural suitability complexes (1:25,000 / 1:100,000), genetic types, particle size composition and water retention. |
| **Arable Soil Chemistry Monitoring (GIOŚ)** | CSV, XLS, Shapefile | `https://www.gios.gov.pl/chemizm_gleb/` | Measurements of pH, organic carbon, humus, macro- and micronutrients at 216 permanent points. |
| **SMGP and Hydrogeological Map (PIG-PIB)** | WMS, WFS, Shapefile | `https://geologia.pgi.gov.pl` | Detailed Geological Map of Poland (1:50,000), groundwater table depth and water permeability. |
| **MIDAS (Mineral Deposits Database, PIG-PIB)** | WMS, WFS, Shapefile | `http://midas.pgi.gov.pl` | Locations of mineral deposits, mining areas and mining grounds in Poland. |
| **SOPO (Landslide Counteraction System, PIG)** | WMS, WFS, Shapefile | `https://osuwiska.pgi.gov.pl` | Register of active and inactive landslides and areas at risk of mass ground movements. |
| **SoilGrids 2.0 (ISRIC / ESDAC)** | WCS, COG (GeoTIFF) | `https://rest.isric.org` | Global 250 m soil property rasters (sand and clay content, organic carbon, density). |

---

## 7. Environmental Protection and Air Quality Monitoring

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **CRFOP GDOŚ (Forms of Nature Protection)** | WFS, WMS, SHP, GPKG | `https://sdi.gdos.gov.pl/wfs` | Boundaries of Natura 2000 areas, national parks, nature reserves and landscape parks (buffer zones). |
| **GIOŚ Air Quality (Portal Powietrze)** | REST API (JSON) | `https://powietrze.gios.gov.pl/pjp/current/api` | Current telemetry data from air quality monitoring stations (PM10, PM2.5, NO₂, SO₂, O₃, AQI index). |

---

## 8. Satellite Remote Sensing

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **Sentinel-2 L2A (Copernicus CDSE)** | STAC API, COG, S3 | `https://catalogue.dataspace.copernicus.eu/stac` | Multispectral imagery (10–20 m, every 2–5 days): Red-Edge, NIR, SWIR bands (NDVI, NDRE, NDMI indices, chlorophyll, biomass moisture). |
| **Sentinel-1 SAR (Copernicus CDSE)** | STAC API, GeoTIFF, S3 | `https://catalogue.dataspace.copernicus.eu/stac` | Synthetic aperture radar (SAR): cloud-independent measurements of roughness, near-surface moisture and deformation. |
| **Sentinel-3 SLSTR / OLCI (CDSE)** | STAC API, NetCDF, GeoTIFF | `https://catalogue.dataspace.copernicus.eu/stac` | Daily land surface temperature measurements (LST, 1 km) for detecting thermal anomalies. |
| **Landsat 8/9 Collection 2** | STAC API, COG (GeoTIFF) | `https://earth-search.aws.element84.com/v1` | Optical (30 m) and thermal TIRS (100 m) measurements for radiation balances. |
| **CLMS High Resolution Vegetation (HR-VPP)** | COG, WMS | `https://land.copernicus.eu` | Ready-made 10 m rasters of vegetation dynamics: start, peak and length of the biomass productivity season. |
| **CLMS Soil Water Index (SWI)** | NetCDF, GeoTIFF | `https://land.copernicus.eu` | Soil profile moisture index on a daily cycle computed from radar data. |

---

## 9. Socio-Economic Statistics

| Register / Service | Protocol & Format | Endpoint / Source | Use in GIS analyses |
| :--- | :--- | :--- | :--- |
| **GUS BDL (Local Data Bank)** | REST API (JSON, XML, CSV) | `https://bdl.stat.gov.pl/api/v1/` | The largest statistical database for municipalities, counties and voivodeships (demography, economy, environment, infrastructure). |
