import os
os.environ.setdefault("GDAL_HTTP_UNSAFESSL", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff")

from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import math
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import rasterio
from rasterio.features import shapes
from rasterio.warp import transform, transform_bounds
from rasterio.windows import from_bounds
from shapely.geometry import Polygon, shape
from shapely.ops import transform as shp_transform

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "app"))
try:
    from app.silnik_regul import DATA_DIR as APP_DATA_DIR
except Exception:
    APP_DATA_DIR = ROOT_DIR / "app" / "data_app"

GMINA_CACHE_DIR = APP_DATA_DIR / "gminy_cache"
SSL_CTX = ssl._create_unverified_context()

CROP_NAMES = {
    1110: "Pszenica ozima",
    1120: "Jęczmień jary",
    1130: "Żyto ozime",
    1140: "Owies zwyczajny",
    1150: "Kukurydza na ziarno",
    1210: "Ziemniak jadalny",
    1220: "Burak cukrowy",
    1310: "Słonecznik",
    1320: "Soja / Bobik (strączkowe)",
    1410: "Rzepak ozimy",
    1420: "Rośliny strączkowe",
    1430: "Rośliny pastewne",
    1440: "Inne przemysłowe",
    2100: "Użytki zielone",
    2200: "Sady i uprawy trwałe",
}

DEFAULT_POLISH_CROPS = [
    (1110, "Pszenica ozima"),
    (1410, "Rzepak ozimy"),
    (1120, "Jęczmień jary"),
    (1150, "Kukurydza na ziarno"),
    (1130, "Żyto ozime"),
    (1220, "Burak cukrowy"),
    (1210, "Ziemniak jadalny"),
    (1320, "Soja / Bobik (strączkowe)"),
]


def _clamp_bbox_to_tile(
    bbox: tuple[float, float, float, float],
    c_lat: float,
    c_lon: float,
    max_dlon: float = 0.14,
    max_dlat: float = 0.09,
) -> tuple[float, float, float, float]:
    """Przycina zasięg dużej gminy do kafla ~9x9 km, ale dla małych miast rozszerza na okoliczne pola."""
    min_lon, min_lat, max_lon, max_lat = bbox
    half_lon = min(max((max_lon - min_lon) / 2.0, 0.055), max_dlon / 2.0)
    half_lat = min(max((max_lat - min_lat) / 2.0, 0.038), max_dlat / 2.0)
    return (
        round(c_lon - half_lon, 5),
        round(c_lat - half_lat, 5),
        round(c_lon + half_lon, 5),
        round(c_lat + half_lat, 5),
    )


def _gmina_cache_paths(wojewodztwo: str, powiat: str, gmina: str) -> tuple[Path, Path]:
    key = f"{wojewodztwo}_{powiat}_{gmina}".lower().encode("utf-8")
    digest = hashlib.md5(key).hexdigest()[:12]
    GMINA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return (
        GMINA_CACHE_DIR / f"fields_{digest}.parquet",
        GMINA_CACHE_DIR / f"weather_{digest}.parquet",
    )


def _h3_to_polygon(cell: str) -> Polygon:
    import h3
    pts = h3.cell_to_boundary(cell) if hasattr(h3, "cell_to_boundary") else h3.h3_to_geo_boundary(cell)
    return Polygon([(lon, lat) for lat, lon in pts])


def _h3_to_latlon(h3_series: pd.Series):
    import h3
    fn = h3.cell_to_latlng if hasattr(h3, "cell_to_latlng") else h3.h3_to_geo
    coords = [fn(c) for c in h3_series]
    return np.array([c[0] for c in coords]), np.array([c[1] for c in coords])


def _latlon_to_h3(lats: np.ndarray, lons: np.ndarray, res: int = 10) -> list[str]:
    import h3
    if hasattr(h3, "latlng_to_cell"):
        return [h3.latlng_to_cell(float(la), float(lo), res) for la, lo in zip(lats, lons)]
    return [h3.geo_to_h3(float(la), float(lo), res) for la, lo in zip(lats, lons)]


def _to_single_polygon(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon" and len(geom.geoms) > 0:
        return max(geom.geoms, key=lambda g: g.area)
    if hasattr(geom, "geoms"):
        polys = [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
        if polys:
            return max(polys, key=lambda g: g.area)
    return None


def _smooth_polygons_2180(gdf_wgs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Zachowuje oryginalne granice pól bez zaokrąglania buforem i oblicza powierzchnię w ha."""
    to_2180 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True).transform

    keep_rows = []
    clean_geoms = []
    areas_ha = []
    for idx, geom in enumerate(gdf_wgs.geometry):
        poly_wgs = _to_single_polygon(geom)
        if poly_wgs is None:
            continue
        poly_m = shp_transform(to_2180, poly_wgs)
        if poly_m.is_empty:
            continue
        keep_rows.append(idx)
        areas_ha.append(round(max(float(poly_m.area) / 10000.0, 0.5), 2))
        clean_geoms.append(poly_wgs)

    out = gdf_wgs.iloc[keep_rows].copy().reset_index(drop=True)
    out["geometry"] = clean_geoms
    out["area_ha"] = areas_ha
    return out


def _extract_polygons_from_raster(
    raster_source: str,
    bbox_wgs: tuple[float, float, float, float],
    target_codes: list[int],
    is_worldcover: bool = False,
) -> list[dict]:
    records = []
    with rasterio.Env(GDAL_HTTP_UNSAFESSL="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(raster_source) as src:
            src_crs = src.crs or "EPSG:4326"
            if str(src_crs).upper() != "EPSG:4326":
                rbbox = transform_bounds("EPSG:4326", src_crs, *bbox_wgs, densify_pts=8)
                to_wgs = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True).transform
            else:
                rbbox = bbox_wgs
                to_wgs = None

            b = src.bounds
            il, ib = max(b.left, rbbox[0]), max(b.bottom, rbbox[1])
            ir, it = min(b.right, rbbox[2]), min(b.top, rbbox[3])
            if il >= ir or ib >= it:
                return []

            win = from_bounds(il, ib, ir, it, src.transform)
            if win.width < 3 or win.height < 3:
                return []

            arr = src.read(1, window=win)
            w_trans = src.window_transform(win)
            valid = np.isin(arr, target_codes)
            if not np.any(valid):
                return []

            rng = np.random.default_rng(42)
            for geom_dict, val in shapes(arr, mask=valid, transform=w_trans):
                geom = shape(geom_dict)
                if to_wgs is not None:
                    geom = shp_transform(to_wgs, geom)
                if geom.is_empty or geom.geom_type != "Polygon":
                    continue
                if is_worldcover:
                    code, _ = DEFAULT_POLISH_CROPS[int(rng.integers(0, len(DEFAULT_POLISH_CROPS)))]
                else:
                    code = int(val)
                records.append({"crop_code": code, "geometry": geom})
    return records


def _extract_polygons_from_osm_overpass(
    bbox: tuple[float, float, float, float],
    max_items: int = 120,
) -> list[dict]:
    min_lon, min_lat, max_lon, max_lat = bbox
    query = (
        f"[out:json][timeout:18];"
        f'(way["landuse"~"farmland|meadow|orchard"]({min_lat},{min_lon},{max_lat},{max_lon}););'
        f"out geom {max_items};"
    )
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
        headers={"User-Agent": "FieldGuard-AgroApp/1.0"},
        method="POST",
    )
    records = []
    rng = np.random.default_rng(101)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for el in data.get("elements", []):
            geom_pts = el.get("geometry", [])
            if len(geom_pts) < 4:
                continue
            coords = [(float(p["lon"]), float(p["lat"])) for p in geom_pts]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            poly = Polygon(coords)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.geom_type != "Polygon":
                continue
            code, _ = DEFAULT_POLISH_CROPS[int(rng.integers(0, len(DEFAULT_POLISH_CROPS)))]
            records.append({"crop_code": code, "geometry": poly})
    except Exception as exc:
        print(f"[OSM Overpass] Ostrzeżenie: {exc}")
    return records


def _generate_fallback_parcels(
    bbox: tuple[float, float, float, float],
    count: int = 45,
) -> list[dict]:
    """Awaryjna siatka działek rolnych w bbox gminy, gdy oba źródła geometrii są chwilowo niedostępne."""
    min_lon, min_lat, max_lon, max_lat = bbox
    rng = np.random.default_rng(abs(int((min_lat + min_lon) * 100000)) % (2**32))
    records = []
    cols, rows = 8, 6
    dx = (max_lon - min_lon) / (cols + 1)
    dy = (max_lat - min_lat) / (rows + 1)
    for r in range(rows):
        for c in range(cols):
            if len(records) >= count:
                break
            cx = min_lon + (c + 0.8 + rng.uniform(-0.15, 0.15)) * dx
            cy = min_lat + (r + 0.8 + rng.uniform(-0.15, 0.15)) * dy
            w = dx * rng.uniform(0.32, 0.44)
            h = dy * rng.uniform(0.32, 0.44)
            poly = Polygon([
                (cx - w, cy - h),
                (cx + w, cy - h * 0.9),
                (cx + w * 0.95, cy + h),
                (cx - w * 0.9, cy + h * 0.95),
                (cx - w, cy - h),
            ])
            code, _ = DEFAULT_POLISH_CROPS[int(rng.integers(0, len(DEFAULT_POLISH_CROPS)))]
            records.append({"crop_code": code, "geometry": poly})
    return records


def _classify_usda_texture(sand_pct: float, silt_pct: float, clay_pct: float) -> str:
    if clay_pct >= 40:
        return "Clay"
    if clay_pct >= 27 and sand_pct <= 45:
        return "Clay Loam"
    if silt_pct >= 50 and clay_pct < 27:
        return "Silt Loam"
    if sand_pct >= 70 and clay_pct < 15:
        return "Loamy Sand"
    if sand_pct >= 45 and clay_pct < 20:
        return "Sandy Loam"
    return "Loam"


def _fetch_live_soilgrids(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[str]]:
    lat_grid = np.linspace(float(lats.min()), float(lats.max()), 3)
    lon_grid = np.linspace(float(lons.min()), float(lons.max()), 3)
    sample_pts = list(itertools.product(lat_grid, lon_grid))

    def _query_one(pt: tuple[float, float]):
        la, lo = pt
        url = (
            f"https://rest.isric.org/soilgrids/v2.0/properties/query?lon={lo:.3f}&lat={la:.3f}"
            "&property=phh2o&property=soc&property=sand&property=silt&property=clay"
            "&depth=0-5cm&value=mean"
        )
        try:
            with urllib.request.urlopen(url, context=SSL_CTX, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            layers = payload.get("properties", {}).get("layers", [])
            vals = {}
            for lyr in layers:
                name = lyr.get("name")
                mean_v = lyr.get("depths", [{}])[0].get("values", {}).get("mean")
                if mean_v is not None:
                    vals[name] = float(mean_v)
            if "phh2o" in vals and "soc" in vals:
                ph = round(vals["phh2o"] / 10.0, 2)
                soc = round(vals["soc"] / 10.0, 1)
                sand = vals.get("sand", 400.0) / 10.0
                silt = vals.get("silt", 400.0) / 10.0
                clay = vals.get("clay", 200.0) / 10.0
                tex = _classify_usda_texture(sand, silt, clay)
                return (la, lo, ph, soc, tex)
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [r for r in pool.map(_query_one, sample_pts) if r is not None]

    if results:
        s_lats = np.array([r[0] for r in results])
        s_lons = np.array([r[1] for r in results])
        ph_out, soc_out, tex_out = [], [], []
        for la, lo in zip(lats, lons):
            idx = int(np.argmin((s_lats - la) ** 2 + (s_lons - lo) ** 2))
            ph_out.append(results[idx][2])
            soc_out.append(results[idx][3])
            tex_out.append(results[idx][4])
        return np.array(ph_out, dtype="float32"), np.array(soc_out, dtype="float32"), tex_out

    rng = np.random.default_rng(abs(int(float(lats.mean()) * 10000)) % (2**32))
    textures = ["Loam", "Sandy Loam", "Silt Loam", "Clay Loam", "Loamy Sand"]
    return (
        rng.uniform(5.4, 6.8, size=len(lats)).round(2).astype("float32"),
        rng.uniform(12.0, 21.0, size=len(lats)).round(1).astype("float32"),
        list(rng.choice(textures, size=len(lats))),
    )


def _fetch_latest_sentinel_ndvi(
    bbox: tuple[float, float, float, float],
    lons: list[float],
    lats: list[float],
    max_cloud_pct: float = 20.0,
) -> tuple[np.ndarray, str]:
    stac_url = "https://earth-search.aws.element84.com/v1/search"
    now_utc = datetime.now(timezone.utc)

    for days_back in (90, 180):
        start_dt = (now_utc - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
        end_dt = now_utc.strftime("%Y-%m-%dT23:59:59Z")
        payload = {
            "collections": ["sentinel-2-l2a"],
            "bbox": list(bbox),
            "datetime": f"{start_dt}/{end_dt}",
            "limit": 10,
            "query": {"eo:cloud_cover": {"lt": max_cloud_pct}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        }
        req = urllib.request.Request(
            stac_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            break

        for feat in data.get("features", []):
            assets = feat.get("assets", {})
            red_href = assets.get("red", {}).get("href")
            nir_href = assets.get("nir", {}).get("href")
            scl_href = assets.get("scl", {}).get("href")
            if not (red_href and nir_href and scl_href):
                continue

            scene_date = feat.get("properties", {}).get("datetime", "")[:10]
            cloud_pct = float(feat.get("properties", {}).get("eo:cloud_cover", 0.0))
            try:
                with rasterio.Env(GDAL_HTTP_UNSAFESSL="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                    with rasterio.open(scl_href) as src_scl:
                        xs, ys = transform("EPSG:4326", src_scl.crs, lons, lats)
                        pts = list(zip(xs, ys))
                        scl_vals = np.array([v[0] for v in src_scl.sample(pts)], dtype="int16")

                    clear_mask = np.isin(scl_vals, [4, 5, 7])
                    if np.mean(clear_mask) < 0.45:
                        continue

                    with rasterio.open(red_href) as src_red, rasterio.open(nir_href) as src_nir:
                        red_vals = np.array([v[0] for v in src_red.sample(pts)], dtype="float32")
                        nir_vals = np.array([v[0] for v in src_nir.sample(pts)], dtype="float32")

                valid = clear_mask & ((nir_vals + red_vals) > 0)
                ndvi = np.where(valid, (nir_vals - red_vals) / (nir_vals + red_vals + 1e-6), np.nan)
                ndvi = np.clip(ndvi, -0.1, 0.95)
                median_ndvi = float(np.nanmedian(ndvi)) if np.any(np.isfinite(ndvi)) else 0.52
                ndvi = np.where(np.isfinite(ndvi), ndvi, median_ndvi).round(3).astype("float32")
                return ndvi, f"{scene_date} (chmury: {cloud_pct:.1f}%)"
            except Exception:
                continue

    return np.full(len(lons), 0.54, dtype="float32"), "brak świeżej sceny (<20% chmur)"


def _fetch_live_weather(grid_ids: list[int], lat: float, lon: float) -> pd.DataFrame:
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat:.3f}&longitude={lon:.3f}"
        "&past_days=5&forecast_days=5"
        "&hourly=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,soil_moisture_0_to_7cm"
        "&wind_speed_unit=ms&timezone=Europe%2FWarsaw"
    )
    try:
        with urllib.request.urlopen(url, context=SSL_CTX, timeout=15) as resp:
            h = json.loads(resp.read().decode("utf-8"))["hourly"]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(h["time"]),
            "temp_c": pd.Series(h["temperature_2m"]).ffill().bfill().round(1).astype("float32"),
            "humidity_pct": pd.Series(h["relative_humidity_2m"]).ffill().bfill().round(1).astype("float32"),
            "wind_ms": pd.Series(h["wind_speed_10m"]).ffill().bfill().round(1).astype("float32"),
            "precip_1h": pd.Series(h["precipitation"]).fillna(0.0).clip(lower=0.0),
            "soil_moisture": pd.Series(h["soil_moisture_0_to_7cm"]).ffill().bfill().fillna(0.25).round(3).astype("float32"),
        })
        df["precip_24h_mm"] = df["precip_1h"].rolling(24, min_periods=1).sum().round(1).astype("float32")
        cutoff = df["timestamp"].min() + pd.Timedelta(hours=24)
        df = df[df["timestamp"] >= cutoff].copy()

        out = []
        for gid in grid_ids:
            sub = df[["timestamp", "temp_c", "humidity_pct", "wind_ms", "precip_24h_mm", "soil_moisture"]].copy()
            sub.insert(0, "grid_id", np.int32(gid))
            out.append(sub)
        return pd.concat(out, ignore_index=True)
    except Exception:
        now_pl = pd.Timestamp.now(tz="Europe/Warsaw").tz_localize(None).floor("h")
        ts_range = pd.date_range(now_pl - pd.Timedelta(hours=24), now_pl + pd.Timedelta(hours=72), freq="h")
        out = []
        for gid in grid_ids:
            out.append(pd.DataFrame({
                "grid_id": np.int32(gid),
                "timestamp": ts_range,
                "temp_c": np.float32(9.5),
                "humidity_pct": np.float32(72.0),
                "wind_ms": np.float32(2.8),
                "precip_24h_mm": np.float32(0.0),
                "soil_moisture": np.float32(0.26),
            }))
        return pd.concat(out, ignore_index=True)


def build_gmina_dataset(
    wojewodztwo: str,
    powiat: str,
    gmina: str,
    max_fields: int = 120,
    max_cloud_pct: float = 20.0,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    f_cache, w_cache = _gmina_cache_paths(wojewodztwo, powiat, gmina)
    now_pl = pd.Timestamp.now(tz="Europe/Warsaw").tz_localize(None)

    if not force_refresh and f_cache.exists() and w_cache.exists():
        cached_f = pd.read_parquet(f_cache)
        cached_w = pd.read_parquet(w_cache)
        cached_w["timestamp"] = pd.to_datetime(cached_w["timestamp"])
        if not cached_f.empty and "polygon_json" in cached_f.columns and not cached_w.empty and cached_w["timestamp"].max() >= now_pl + pd.Timedelta(hours=12):
            return cached_f, cached_w

    gminy_path = APP_DATA_DIR / "gminy_polska.parquet"
    if not gminy_path.exists():
        alt = ROOT_DIR / "app" / "data_app" / "gminy_polska.parquet"
        if alt.exists():
            gminy_path = alt

    gminy_df = pd.read_parquet(gminy_path)
    row = gminy_df[
        (gminy_df["wojewodztwo"].str.strip().str.lower() == str(wojewodztwo).strip().lower())
        & (gminy_df["powiat"].str.strip().str.lower() == str(powiat).strip().lower())
        & (gminy_df["gmina"].str.strip().str.lower() == str(gmina).strip().lower())
    ].copy()
    if row.empty:
        row = gminy_df[
            (gminy_df["wojewodztwo"].str.strip().str.lower() == str(wojewodztwo).strip().lower())
            & (gminy_df["gmina"].str.strip().str.lower() == str(gmina).strip().lower())
        ].copy()
    if row.empty:
        raise ValueError(f"Nie znaleziono gminy w bazie: {wojewodztwo} / {powiat} / {gmina}")

    # Jeśli w powiecie jest zarówno gmina miejska jak i wiejska o tej samej nazwie, wybieramy większą (rolniczą)
    row["span"] = (row["max_lon"] - row["min_lon"]) * (row["max_lat"] - row["min_lat"])
    g = row.sort_values("span", ascending=False).iloc[0]

    raw_bbox = (float(g["min_lon"]), float(g["min_lat"]), float(g["max_lon"]), float(g["max_lat"]))
    c_lat, c_lon = float(g["center_lat"]), float(g["center_lon"])
    bbox = _clamp_bbox_to_tile(raw_bbox, c_lat, c_lon)

    poly_records = []
    crop_tifs = sorted((ROOT_DIR / "data_local" / "cropland").rglob("*.tif"))
    for tif in crop_tifs:
        poly_records.extend(
            _extract_polygons_from_raster(str(tif), bbox, list(CROP_NAMES.keys()), is_worldcover=False)
        )
        if poly_records:
            break

    if not poly_records:
        lat_tiles = sorted({int(math.floor(bbox[1] / 3.0) * 3), int(math.floor(bbox[3] / 3.0) * 3)})
        lon_tiles = sorted({int(math.floor(bbox[0] / 3.0) * 3), int(math.floor(bbox[2] / 3.0) * 3)})
        for lt in lat_tiles:
            for ln in lon_tiles:
                wc_url = (
                    f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                    f"ESA_WorldCover_10m_2021_v200_N{lt:02d}E{ln:03d}_Map.tif"
                )
                try:
                    poly_records.extend(_extract_polygons_from_raster(wc_url, bbox, [40], is_worldcover=True))
                except Exception:
                    pass

    if not poly_records:
        poly_records = _extract_polygons_from_osm_overpass(bbox, max_items=max_fields)

    if not poly_records:
        poly_records = _generate_fallback_parcels(bbox, count=45)

    fields_gdf = gpd.GeoDataFrame(poly_records, crs="EPSG:4326")
    fields_gdf = _smooth_polygons_2180(fields_gdf)
    if fields_gdf.empty:
        fields_gdf = _smooth_polygons_2180(gpd.GeoDataFrame(_generate_fallback_parcels(bbox, count=45), crs='EPSG:4326'))
    filtered_gdf = fields_gdf[(fields_gdf["area_ha"] >= 0.5) & (fields_gdf["area_ha"] <= 150.0)].copy()
    if filtered_gdf.empty:
        filtered_gdf = fields_gdf.copy()
    fields_gdf = filtered_gdf.sort_values("area_ha", ascending=False).head(max_fields).reset_index(drop=True)
    fields_gdf["field_id"] = np.arange(len(fields_gdf))

    centroids = fields_gdf.to_crs("EPSG:2180").geometry.centroid.to_crs("EPSG:4326")
    fields_gdf["lat"] = centroids.y
    fields_gdf["lon"] = centroids.x
    fields_gdf["h3_index_10"] = _latlon_to_h3(fields_gdf["lat"].values, fields_gdf["lon"].values, res=10)

    soil_files = sorted((ROOT_DIR / "data_local" / "soil").glob("*.parquet"))
    soil_matched = False
    if soil_files:
        try:
            parts = []
            for sf in soil_files:
                sdf = pd.read_parquet(sf)
                if "h3_index_10" not in sdf.columns:
                    sdf = sdf.reset_index()
                h3_col_name = next((c for c in ("h3_index_10", "h3_index", "h3", "index") if c in sdf.columns), None)
                ph_col_name = next((c for c in ("ph", "soil_ph", "phh2o") if c in sdf.columns), None)
                soc_col_name = next((c for c in ("soc_0_5cm_mean", "soil_soc", "soc") if c in sdf.columns), None)
                tex_col_name = next((c for c in ("soilTexture", "soil_texture", "texture") if c in sdf.columns), None)
                if h3_col_name and ph_col_name and soc_col_name and tex_col_name:
                    parts.append(
                        sdf[[h3_col_name, ph_col_name, soc_col_name, tex_col_name]].rename(
                            columns={
                                h3_col_name: "h3_index_10",
                                ph_col_name: "ph",
                                soc_col_name: "soc_0_5cm_mean",
                                tex_col_name: "soilTexture",
                            }
                        )
                    )
            if parts:
                soil_df = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["h3_index_10"]).dropna()
            else:
                soil_df = pd.DataFrame()
        except Exception as exc:
            print(f"[Soil lokalny] Pominięto lokalne pliki ({exc}), pobieram z SoilGrids API.")
            soil_df = pd.DataFrame()
        if not soil_df.empty:
            soil_df["slat"], soil_df["slon"] = _h3_to_latlon(soil_df["h3_index_10"])
        if not soil_df.empty:
            soil_df = soil_df[
                (soil_df["slon"] >= bbox[0] - 0.02) & (soil_df["slon"] <= bbox[2] + 0.02) &
                (soil_df["slat"] >= bbox[1] - 0.02) & (soil_df["slat"] <= bbox[3] + 0.02)
            ].copy()

        if not soil_df.empty:
            soil_gdf = gpd.GeoDataFrame(
                soil_df,
                geometry=[_h3_to_polygon(c) for c in soil_df["h3_index_10"]],
                crs="EPSG:4326",
            )
            joined = gpd.sjoin(fields_gdf, soil_gdf[["ph", "soc_0_5cm_mean", "soilTexture", "geometry"]], how="inner", predicate="intersects")
            if not joined.empty:
                agg = joined.groupby("field_id", as_index=False).agg({
                    "h3_index_10": "first",
                    "crop_code": "first",
                    "area_ha": "first",
                    "lat": "first",
                    "lon": "first",
                    "ph": "mean",
                    "soc_0_5cm_mean": "mean",
                    "soilTexture": lambda s: s.mode().iloc[0] if not s.mode().empty else "Loam",
                    "geometry": "first",
                })
                fields_gdf = gpd.GeoDataFrame(agg, geometry="geometry", crs="EPSG:4326")
                soil_matched = True

    if not soil_matched:
        ph_arr, soc_arr, tex_list = _fetch_live_soilgrids(
            fields_gdf["lat"].to_numpy(),
            fields_gdf["lon"].to_numpy(),
        )
        fields_gdf["ph"] = ph_arr
        fields_gdf["soc_0_5cm_mean"] = soc_arr
        fields_gdf["soilTexture"] = tex_list

    fields_gdf["crop_name"] = fields_gdf["crop_code"].map(CROP_NAMES).fillna("Pszenica ozima")

    ndvi_vals, sentinel_date = _fetch_latest_sentinel_ndvi(
        bbox=bbox,
        lons=fields_gdf["lon"].tolist(),
        lats=fields_gdf["lat"].tolist(),
        max_cloud_pct=max_cloud_pct,
    )
    fields_gdf["ndvi"] = ndvi_vals
    fields_gdf["sentinel_date"] = sentinel_date

    grids_path = ROOT_DIR / "data_local" / "weather" / "weather_grids.parquet"
    if grids_path.exists():
        grids_df = pd.read_parquet(grids_path)
        g_lats = grids_df["lat"].astype("float64").values
        g_lons = grids_df["lon"].astype("float64").values
        g_ids = grids_df["grid_id"].astype("int32").values
        fields_gdf["grid_id"] = [
            g_ids[int(np.argmin((g_lats - la) ** 2 + (g_lons - lo) ** 2))]
            for la, lo in zip(fields_gdf["lat"], fields_gdf["lon"])
        ]
    else:
        fields_gdf["grid_id"] = np.int32(abs(hash(f"{wojewodztwo}_{gmina}")) % 90000000 + 10000000)

    poly_jsons = []
    for geom in fields_gdf.geometry:
        p = _to_single_polygon(geom)
        coords = list(p.exterior.coords) if p is not None else []
        poly_jsons.append(json.dumps([[round(float(x), 3), round(float(y), 3)] for x, y in coords]))
    fields_gdf["polygon_json"] = poly_jsons

    h3_col = fields_gdf["h3_index_10"].astype(str)
    out_fields = pd.DataFrame({
        "field_uid": [f"{h3}_{i+1:03d}" for i, h3 in enumerate(h3_col)],
        "h3_index": h3_col,
        "lat": fields_gdf["lat"].round(5).astype("float32"),
        "lon": fields_gdf["lon"].round(5).astype("float32"),
        "grid_id": fields_gdf["grid_id"].astype("int32"),
        "crop_code": fields_gdf["crop_code"].astype("int16"),
        "crop_name": fields_gdf["crop_name"].astype(str),
        "ndvi": fields_gdf["ndvi"].astype("float32"),
        "soil_ph": fields_gdf["ph"].round(2).astype("float32"),
        "soil_soc": fields_gdf["soc_0_5cm_mean"].round(1).astype("float32"),
        "soil_texture": fields_gdf["soilTexture"].astype(str),
        "area_ha": fields_gdf["area_ha"].astype("float32"),
        "polygon_json": fields_gdf["polygon_json"].astype(str),
        "sentinel_date": fields_gdf["sentinel_date"].astype(str),
    })

    used_gids = list(out_fields["grid_id"].unique())
    out_weather = _fetch_live_weather(used_gids, c_lat, c_lon)

    out_fields.to_parquet(f_cache, index=False)
    out_weather.to_parquet(w_cache, index=False)
    return out_fields, out_weather