"""Summarize field pixels and read values at tree positions in a raster's own grid."""

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform, transform_geom
from shapely.geometry import mapping

WGS84 = "EPSG:4326"


def band_values(data, limits, categorical):
    values = np.ma.asarray(data).compressed()
    values = values[np.isfinite(values) & (values >= limits[0]) & (values <= limits[1])]
    if categorical:
        return values[values == np.floor(values)].astype(int)
    return values


def analyze_raster(
    path,
    boundary,
    positions,
    *,
    limits,
    categorical=False,
    all_touched=False,
    last_band=False,
):
    with rasterio.open(path) as raster:
        allowed_bands = (1, 3) if last_band else (1,)
        if not raster.crs or raster.count not in allowed_bands:
            raise ValueError(
                f"{path.name}: raster wymaga CRS i liczby pasm z {allowed_bands}."
            )
        band = raster.count if last_band else 1
        geometry = transform_geom(WGS84, raster.crs, mapping(boundary))
        try:
            data, _ = mask(
                raster,
                [geometry],
                crop=True,
                filled=False,
                indexes=band,
                all_touched=all_touched,
            )
        except ValueError:
            # Rasterio raises ValueError for a cropped geometry outside the raster.
            data = np.empty(0)
        values = band_values(data, limits, categorical)
        summary = {"raster": path.name, "valid_pixels": int(values.size)}
        if categorical:
            classes, counts = np.unique(values, return_counts=True)
            summary["dominant_class"] = (
                int(classes[counts.argmax()]) if classes.size else None
            )
            summary["class_pixel_counts"] = {
                str(code): int(count)
                for code, count in zip(classes, counts, strict=True)
            }
        else:
            summary["mean"] = float(values.mean(dtype=float)) if values.size else None

        readings = dict.fromkeys(positions)
        if positions:
            xs, ys = transform(
                WGS84, raster.crs, *zip(*positions.values(), strict=True)
            )
            points = {}
            for tree_id, x, y in zip(positions, xs, ys, strict=True):
                row, col = raster.index(x, y)
                if 0 <= row < raster.height and 0 <= col < raster.width:
                    points[tree_id] = (x, y)
            for tree_id, data in zip(
                points,
                raster.sample(points.values(), indexes=band, masked=True),
                strict=True,
            ):
                value = band_values(data, limits, categorical)
                if value.size:
                    readings[tree_id] = value[0].item()
        return summary, readings
