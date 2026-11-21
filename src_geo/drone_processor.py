import io
import json
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform_geom
from shapely.geometry import Polygon, mapping

def process_drone_raster(tif_bytes: bytes, fields_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Przetwarza wgrany raster GeoTIFF (.tif) z przelotu drona:
    - Jeśli plik ma 1 kanał (gotowa mapa NDVI), oblicza średnie NDVI dla każdego pola w zasięgu.
    - Jeśli plik ma >= 2 kanały (np. Red + NIR), liczy (NIR - Red) / (NIR + Red).
    Zwraca zaktualizowany DataFrame pól oraz podsumowanie przelotu.
    """
    updated_df = fields_df.copy()
    updated_count = 0

    with rasterio.MemoryFile(tif_bytes) as memfile:
        with memfile.open() as src:
            band_count = src.count
            raster_crs = src.crs

            for idx, row in updated_df.iterrows():
                if "polygon_json" not in row or pd.isna(row["polygon_json"]):
                    continue
                coords = json.loads(row["polygon_json"])
                poly_wgs84 = Polygon(coords)
                geom_proj = transform_geom("EPSG:4326", raster_crs, mapping(poly_wgs84))

                try:
                    out_img, _ = mask(src, [geom_proj], crop=True, filled=False)
                except ValueError:
                    # Poligon poza zasięgiem rastra z drona
                    continue

                if band_count == 1:
                    valid = out_img[0].compressed()
                    if valid.size == 0:
                        continue
                    mean_ndvi = float(np.nanmean(valid))
                else:
                    red = out_img[0].astype("float32")
                    nir = out_img[-1].astype("float32")
                    denom = nir + red
                    valid_mask = (~red.mask) & (~nir.mask) & (denom > 0)
                    if not np.any(valid_mask):
                        continue
                    ndvi_arr = (nir[valid_mask] - red[valid_mask]) / denom[valid_mask]
                    mean_ndvi = float(np.nanmean(ndvi_arr))

                mean_ndvi = float(np.clip(mean_ndvi, -0.2, 0.98))
                updated_df.at[idx, "ndvi"] = round(mean_ndvi, 3)
                updated_count += 1

    summary = {
        "updated_fields": updated_count,
        "total_fields": len(updated_df),
        "bands": band_count,
    }
    return updated_df, summary
