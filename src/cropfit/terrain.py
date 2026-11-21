"""Terrain per plot from the USGS 3DEP 10 m elevation model (Planetary Computer `3dep-seamless`, keyless)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import stac

NEIGHBOURHOOD_M = 150.0


def terrain_metrics(z: np.ndarray, dx_m: float, dy_m: float, half_px: float) -> dict:
    """z: square elevation window centred on the plot. Slope and aspect from the central gradient over the
    plot (half_px pixels each side of the centre); tpi = plot elevation minus the mean of the whole window
    (negative = lower than its surroundings, where water and fine material collect)."""
    gy, gx = np.gradient(z.astype(float), dy_m, dx_m)
    c = z.shape[0] // 2, z.shape[1] // 2
    k = max(1, int(round(half_px)))
    sl = (slice(c[0] - k, c[0] + k + 1), slice(c[1] - k, c[1] + k + 1))
    sx, sy = float(np.nanmean(gx[sl])), float(-np.nanmean(gy[sl]))      # rows run north -> south
    slope = math.degrees(math.atan(math.hypot(sx, sy)))
    aspect = (math.degrees(math.atan2(-sx, -sy)) + 360) % 360 if slope > 0.05 else float("nan")
    elev = float(np.nanmean(z[sl]))
    return dict(elevation_m=elev, slope_deg=slope, aspect_deg=aspect, tpi_150m=elev - float(np.nanmean(z)),
                relief_150m=float(np.nanmax(z) - np.nanmin(z)))


def plot_terrain(lat: float, lon: float, half_m: float = 20.0) -> dict:
    import rasterio
    items = [i for i in stac.search("3dep-seamless", lon, lat) if i.properties.get("gsd") == 10]
    if not items:
        return {}
    it = items[0]
    with rasterio.Env(**stac.GDAL_ENV):
        with rasterio.open(stac.sign(it.assets["data"].href)) as ds:      # geographic grid, ~1/3 arc-second
            dy = abs(ds.transform.e) * 111_320.0
            dx = abs(ds.transform.a) * 111_320.0 * math.cos(math.radians(lat))
            n = int(round(NEIGHBOURHOOD_M / min(dx, dy)))
            row, col = ds.index(lon, lat)
            from rasterio.windows import Window
            z = ds.read(1, window=Window(col - n, row - n, 2 * n + 1, 2 * n + 1), boundless=True,
                        fill_value=np.nan).astype(float)
            if ds.nodata is not None:
                z[z == ds.nodata] = np.nan
    out = terrain_metrics(z, dx, dy, half_m / min(dx, dy))
    out["terrain_source"] = f"3dep-seamless/{it.id}"
    return out


def build(geom: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for p in geom.to_dict("records"):
        try:
            rows.append(dict(plotID=p["plotID"], **plot_terrain(p["lat"], p["lon"], p["half_m"])))
        except Exception as e:  # noqa: BLE001
            print(f"terrain FAILED {p['plotID']}: {type(e).__name__}")
            rows.append(dict(plotID=p["plotID"]))
    return pd.DataFrame(rows)
