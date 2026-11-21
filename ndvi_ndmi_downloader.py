from pathlib import Path
import geopandas as gpd
import numpy as np
import rasterio
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.vrt import WarpedVRT


def download_clip_sentinel_ndvi_ndmi(
    boundary_file,
    start_date,
    end_date,
    out_dir,
    max_cc=10,
    n_scenes=8,
    max_missing_ratio=0.3,
):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    boundary = gpd.read_file(boundary_file)
    boundary_wgs84 = boundary.to_crs("EPSG:4326")
    search_bbox = [float(v) for v in boundary_wgs84.total_bounds]

    client = Client.open("https://earth-search.aws.element84.com/v1")
    search = client.search(
        collections=["sentinel-2-l2a"],
        bbox=search_bbox,
        datetime=f"{start_date}/{end_date}",
        query={"eo:cloud_cover": {"lt": max_cc}},
    )

    elements = list(search.items())
    if not elements:
        print("Nie znaleziono odpowiednich zdjęć dla zadanego obszaru i czasu.")
        return []

    sorted_scenes = sorted(
        elements, key=lambda x: x.properties.get("eo:cloud_cover", 100)
    )

    saved_paths = []
    scl_exclude = (3, 8, 9, 10)

    for scene in sorted_scenes:
        if len(saved_paths) >= n_scenes:
            break

        scene_date = scene.datetime.strftime("%Y-%m-%d") if scene.datetime else "unknown"
        bands_data = {}
        out_meta = None
        shapes = None

        for band in ("red", "nir"):
            file_url = scene.assets[band].href
            with rasterio.open(file_url) as src:
                if shapes is None:
                    boundary_utm = boundary.to_crs(src.crs)
                    shapes = [geom.__geo_interface__ for geom in boundary_utm.geometry]

                img, out_transform = mask(src, shapes, crop=True, nodata=0)
                arr = img[0].astype(np.float32)
                arr[arr == 0] = np.nan
                bands_data[band] = arr

                if out_meta is None:
                    out_meta = src.meta.copy()
                    out_meta.update(
                        {
                            "driver": "GTiff",
                            "height": arr.shape[0],
                            "width": arr.shape[1],
                            "transform": out_transform,
                            "count": 2,
                            "dtype": "float32",
                            "nodata": np.nan,
                        }
                    )

        with rasterio.open(scene.assets["swir16"].href) as swir_src:
            with WarpedVRT(
                swir_src,
                crs=out_meta["crs"],
                transform=out_meta["transform"],
                width=out_meta["width"],
                height=out_meta["height"],
                resampling=Resampling.bilinear,
            ) as swir_vrt:
                swir_arr = swir_vrt.read(1).astype(np.float32)
                swir_arr[swir_arr == 0] = np.nan

        in_field = geometry_mask(
            shapes,
            out_shape=(out_meta["height"], out_meta["width"]),
            transform=out_meta["transform"],
            invert=True,
        )
        total_field_px = int(np.sum(in_field))
        if total_field_px == 0:
            continue

        swir_arr[~in_field] = np.nan

        nir, red = bands_data["nir"], bands_data["red"]

        denom_ndvi = nir + red
        ndvi = np.where(
            (denom_ndvi != 0) & ~np.isnan(denom_ndvi),
            (nir - red) / denom_ndvi,
            np.nan,
        ).astype(np.float32)

        denom_ndmi = nir + swir_arr
        ndmi = np.where(
            (denom_ndmi != 0) & ~np.isnan(denom_ndmi),
            (nir - swir_arr) / denom_ndmi,
            np.nan,
        ).astype(np.float32)

        if "scl" in scene.assets and scl_exclude:
            with rasterio.open(scene.assets["scl"].href) as scl_src:
                with WarpedVRT(
                    scl_src,
                    crs=out_meta["crs"],
                    transform=out_meta["transform"],
                    width=out_meta["width"],
                    height=out_meta["height"],
                    resampling=Resampling.nearest,
                ) as scl_vrt:
                    scl_arr = scl_vrt.read(1)
            cloud_mask = np.isin(scl_arr, scl_exclude)
            ndvi[cloud_mask] = np.nan
            ndmi[cloud_mask] = np.nan

        missing_px = int(np.sum(in_field & (np.isnan(ndvi) | np.isnan(ndmi))))
        missing_ratio = missing_px / total_field_px

        if missing_ratio > max_missing_ratio:
            print(
                f"   Pominięto: wypadło {missing_ratio:.1%} obszaru pola "
                f"(limit: {max_missing_ratio:.0%})."
            )
            continue

        out_file = out_dir / f"ndvi_ndmi_{scene_date}_{scene.id}.tif"
        with rasterio.open(out_file, "w", **out_meta) as dest:
            dest.write(ndvi, 1)
            dest.write(ndmi, 2)
            dest.set_band_description(1, "NDVI")
            dest.set_band_description(2, "NDMI")

        print(
            f"   Zapisano ({len(saved_paths) + 1}/{n_scenes}): "
            f"{out_file.name} | braki: {missing_ratio:.1%}"
        )
        saved_paths.append(out_file)

    if len(saved_paths) < n_scenes:
        print(
            f"Uwaga: udało się znaleźć tylko {len(saved_paths)} z {n_scenes} wymaganych scen.")

    return saved_paths




if __name__ == "__main__":
    boundary_file = Path("test/fields.geojson")
    download_clip_sentinel_ndvi_ndmi(boundary_file=boundary_file, start_date="2022-03-01", end_date="2022-06-30", out_dir="test/ndvi", n_scenes=1)

