## Satellite

Organizers **do not** host satellite data archives. Teams download what they need for their track (AOI + dates + bands only).

### Suggested starting point: Sentinel-2

**Source:**

Sentinel-2 L2A (surface reflectance)

**Why:**

Free, frequent revisit, good for NDVI / stress / phenology proxies

**Spatial resolution:**

10/20/60 m (band-dependent)

**Typical format**

Cloud-Optimized GeoTIFF (COG) per band

**How to get it:**

Starter notebook: [`notebooks/sentinel2_earth_search_hackathon.ipynb`](../notebooks/sentinel2_earth_search_hackathon.ipynb) (Element 84 Earth Search - **no AWS account needed**)

Other common access options (optional): Copernicus Data Space Ecosystem, Google Earth Engine (personal account), commercial APIs if your team already has access.

### Other sources (allowed)

You can use any satellite product that fits your plan - raw or derived - for example:

- Other sensors (e.g. Landsat, Sentinel-1 SAR)
- Indices / composites (NDVI, EVI, cloud-free mosaics)
- Ready-made crop or stress layers from public catalogs

Document in your team README: source, license, AOI, dates, and how to reproduce the download.

### Practical tips

- Start **small**: tiny bbox, short date range, low cloud cover, few bands.
- Prefer COGs / windowed reads over full tiles when possible.
- Do **not** commit large GeoTIFFs - keep them local (see root `.gitignore`).
- Cite the provider and product name in your demo materials.