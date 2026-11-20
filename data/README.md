> **GeoEarth Junction:** These are organizer dataset descriptions. The first iteration will select and validate a subset for one crop; the presence of a dataset below does not mean it has been downloaded, imported or displayed. See [project requirements](../PROJECT.md). Historical weather is not a current forecast, and the documented Sentinel-2 sample is not nationwide. Keep restricted data and access links outside Git.

## Dataset overview

| Data source | What it is                                                | Format                  | Coverage                     | Link (Docs)                                                                                                                                                                                                                                                                     |
|-------------|-----------------------------------------------------------|-------------------------|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Cropland    | CLMS HRL Crop Types (CTY) — yearly 10 m crop class map (Sentinel-1/2) | GeoTIFF (ZIP per year; 48 PL tiles) | Poland, EPSG:4326; 2020–2024 | [cropland.md](cropland.md) |
| Weather     | Gridded historical weather (temp, humidity, wind, precip, radiation, ETo/ETr, soil moisture/temp, …) + separate NASA IMERG precip; join on `grid_id` | Parquet (ZIP per voivodeship / year; daily & hourly) | Poland, 4 km grids; 2020–2025 | [weather.md](weather.md) |
| Satellite   | Sentinel 2 L2A, Bands (RED, GREEN, BLUE, NIR, CLOUD MASK) | Cloud Optimized GeoTIFF | South of Poland, tile: 33UXR | [CDSE Sentinel-2](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2), [Notebook](https://github.com/Bayer-Group/field-under-pressure-materials/blob/main/notebooks/sentinel2_earth_search_hackathon.ipynb) with the download instruction |
| Soil        | ISRIC SoilGrids / Soil 250 v2 — texture, pH, SOC, CEC, bulk density, USDA class; H3 level 10 join | Parquet (ZIP per voivodeship) | Poland (per voivodeship); static 2022 map, 250 m | [soil.md](soil.md) |
| Crop Yield Risks and Protection | Metodyki integrowanej ochrony PDFs + Excel risk summary (`zboza_ryzyka.xlsx`) — diseases, pests, favourable conditions (spray / treat / harvest / wait context) | PDF + Excel (`.xlsx`) | Agronomic reference (not a spatial layer); PL field crops | [yield-risks-protection.md](yield-risks-protection.md) |

## Download links

Presigned S3 download links will be published on **Friday morning** (20 Nov 2026) in Discord channel.

No AWS account required.

> If a link fails before the stated expiry, contact the organizers.

