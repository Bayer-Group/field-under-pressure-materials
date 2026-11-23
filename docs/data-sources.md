# Data sources

## Organizer datasets

The hackathon organizers provided the datasets below. Their original descriptions, together with the crop-protection
methodologies and a starter notebook, are kept unchanged in the
[`bayer/`](https://github.com/geoearth-junction/field-under-pressure-materials/tree/team/geoearth-junction/bayer) folder of the
repository. The data files are not committed: they are downloaded into `data/` (ignored by git) and loaded into PostGIS.

| Dataset | What it is | Used in the prototype | Description |
| --- | --- | --- | --- |
| Weather | gridded historical weather on 4 km cells (temperature, humidity, wind, precipitation, radiation, soil moisture, …), 2020–2025, plus NASA IMERG precipitation | yes: wet hours, degree days and spray window weather (2024, Mazowieckie) | [weather.md](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/bayer/data/weather.md) |
| Cropland | CLMS HRL Crop Types: a yearly 10 m crop class map, 2020–2024 | yes: the crop map behind each crop area | [cropland.md](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/bayer/data/cropland.md) |
| Soil | ISRIC SoilGrids / Soil 250 v2 on H3 cells: texture, pH, organic carbon, CEC, bulk density | yes: soil context of a crop area | [soil.md](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/bayer/data/soil.md) |
| Satellite | Sentinel-2 L2A bands, tile 33UXR | no | [satellite.md](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/bayer/data/satellite.md) |
| Crop yield risks and protection | Polish *metodyki integrowanej ochrony* (PDF) and an Excel summary of risks per crop | reference for the disease rules | [yield-risks-protection.md](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/bayer/data/yield-risks-protection.md) |

How the files map to database tables, and the units checked on load, are described in
[`docker/README.md`](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/docker/README.md)
and [`docker/RAW_SCHEMA.md`](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/docker/RAW_SCHEMA.md).

## Public services used at run time

| Service | Used for |
| --- | --- |
| GUGiK ULDK | cadastral parcels by number or by a clicked point, and their place names |
| OpenStreetMap tiles | the base map of the web client |

## Register of Polish public spatial data

The [register of public GIS services](polskie_rejestry_publiczne_gis.md) lists 46 official services (WMS, WFS, WCS, STAC, REST)
from GUGiK, IMGW, IUNG, GIOŚ, PIG and Copernicus, also as a
[CSV file](polskie_rejestry_publiczne_gis.csv). It is a reference for extending the project; most of these services are not
used by the prototype yet.

## Licences

The code is released under the MIT licence (`LICENSE`). Data keeps the licence of its source: the organizer datasets are
provided for the hackathon under the organizers' terms, and public data (GUGiK, IMGW, Copernicus) under the terms of its
publisher.
