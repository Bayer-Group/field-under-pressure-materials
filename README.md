# field-under-pressure-materials

Data and source documentation for the **Field Under Pressure** hackathon.

Datasets are hosted in cloud storage. Below you can find **one download link per data source**. Links expire after the hackathon - download what you need before then. **No AWS account is required.**

---

## How to get the sample data

1. Use the download links shared by the organizers (one link per data source below).
2. Download each package locally (or into your team’s shared drive).
3. Work from the local copy.

| Data source | Download link | Expires |
|---|---|---|
| Cropland | <!-- paste link --> | <!-- date --> |
| Weather | <!-- paste link --> | <!-- date --> |
| Satellite | <!-- paste link --> | <!-- date --> |
| Soil | <!-- paste link --> | <!-- date --> |

> If a link fails before the stated expiry, contact the organizers.

### After download

```bash
# Example: inspect a Parquet file (Python)
# pip install pyarrow pandas
python -c "import pandas as pd; print(pd.read_parquet('Dolnośląskie_daily_2020.parquet').head())"
```

## Dataset overview

| Data source | What it is | Format | Coverage | Notes |
|-------------|---|---|---|---|
| Cropland    | | | | |
| Weather     | | | | |
| Satellite   | | | | |
| Soil        | | | | |

## Datasets in detail

### Cropland

**Download:** see [How to get the data](#how-to-get-the-data)

| Field | Value |
|---|---|
| Source | <!-- TODO: provider / product name --> |
| Description | <!-- TODO: what the layer represents --> |
| Spatial extent | <!-- TODO --> |
| Temporal coverage | <!-- TODO --> |
| Resolution / CRS | <!-- TODO --> |
| File format | <!-- TODO --> |
| Schema / attributes | <!-- TODO: column or band list --> |
---

### Weather

### Satellite

### Soil

## Licensing & usage

1. Data is for hackathon use only unless stated otherwise.
2. Download via the provided links only; links expire after the event.
3. Cite sources as listed in each dataset section.