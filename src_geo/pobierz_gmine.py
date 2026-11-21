import io
import json
import urllib.request
import zipfile
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
from rasterio.warp import transform
from rasterio.windows import from_bounds
from shapely.geometry import Polygon, shape

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DATA_DIR = ROOT_DIR / "app" / "data_app"

CROP_NAMES = {
    1110: "Pszenica ozima",
    1120: "Jęczmień",
    1130: "Żyto",
    1140: "Owies",
    1150: "Kukurydza",
    1210: "Ziemniaki",
    1220: "Buraki cukrowe",
    1310: "Słonecznik",
    1320: "Soja",
    1410: "Rzepak ozimy",
    1420: "Rośliny strączkowe",
    1430: "Rośliny pastewne",
    1440: "Inne przemysłowe",
    2100: "Użytki zielone",
    2200: "Sady i uprawy trwałe",
}

def _h3_to_polygon(cell: str) -> Polygon:
    import h3
    pts = h3.cell_to_boundary(cell) if hasattr(h3, "cell_to_boundary") else h3.h3_to_geo_boundary(cell)
    return Polygon([(lon, lat) for lat, lon in pts])

def _h3_to_latlon(h3_series: pd.Series):
    import h3
    fn = h3.cell_to_latlng if hasattr(h3, "cell_to_latlng") else h3.h3_to_geo
    coords = [fn(c) for c in h3_series]
    return np.array([c[0] for c in coords]), np.array([c[1] for c in coords])

def _fetch_open_meteo_fallback(grid_ids: list[int], lat: float, lon: float) -> pd.DataFrame:
    """Awaryjny pobór godzinowej pogody (maj 2024) z Open-Meteo dla gmin spoza Małopolski."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?latitude={lat:.4f}&longitude={lon:.4f}"
        "&start_date=2024-05-17&end_date=2024-05-30"
        "&hourly=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,soil_moisture_0_to_7cm"
        "&wind_speed_unit=ms&timezone=Europe%2FWarsaw"
    )
    req = urllib.request.urlopen(url, timeout=15)
    payload = json.loads(req.read().decode("utf-8"))
    h = payload["hourly"]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(h["time"]),
        "temp_c": np.round(h["temperature_2m"], 1).astype("float32"),
        "humidity_pct": np.round(h["relative_humidity_2m"], 1).astype("float32"),
        "wind_ms": np.round(h["wind_speed_10m"], 1).astype("float32"),
        "precip_1h": np.fillna(pd.Series(h["precipitation"]), 0.0) if hasattr(np, "fillna") else pd.Series(h["precipitation"]).fillna(0.0),
        "soil_moisture": np.round(pd.Series(h["soil_moisture_0_to_7cm"]).fillna(0.25), 3).astype("float32"),
    })
    df["precip_24h_mm"] = df["precip_1h"].rolling(24, min_periods=1).sum().round(1).astype("float32")
    df = df[df["timestamp"] >= "2024-05-18 00:00:00"].copy()

    out = []
    for gid in grid_ids:
        sub = df[["timestamp", "temp_c", "humidity_pct", "wind_ms", "precip_24h_mm", "soil_moisture"]].copy()
        sub.insert(0, "grid_id", np.int32(gid))
        out.append(sub)
    return pd.concat(out, ignore_index=True)

def build_gmina_dataset(wojewodztwo: str, powiat: str, gmina: str, max_fields: int = 250) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Wyciąga prawdziwe poligony pól, glebę SoilGrids, NDVI Sentinel-2 i pogodę
    dla wybranej gminy z gminy_polska.parquet.
    """
    gminy_df = pd.read_parquet(APP_DATA_DIR / "gminy_polska.parquet")
    row = gminy_df[
        (gminy_df["wojewodztwo"] == wojewodztwo)
        & (gminy_df["powiat"] == powiat)
        & (gminy_df["gmina"] == gmina)
    ]
    if row.empty:
        raise ValueError(f"Nie znaleziono gminy: {wojewodztwo} / {powiat} / {gmina}")

    g = row.iloc[0]
    bbox = (float(g["min_lon"]), float(g["min_lat"]), float(g["max_lon"]), float(g["max_lat"]))

    # 1. Wektoryzacja poligonów pól z rastra CLMS 10 m dla zasięgu gminy
    crop_tifs = sorted((ROOT_DIR / "data_local" / "cropland").rglob("*.tif"))
    poly_records = []
    for tif in crop_tifs:
        with rasterio.open(tif) as src:
            b = src.bounds
            il, ib = max(b.left, bbox[0]), max(b.bottom, bbox[1])
            ir, it = min(b.right, bbox[2]), min(b.top, bbox[3])
            if il >= ir or ib >= it:
                continue
            win = from_bounds(il, ib, ir, it, src.transform)
            arr = src.read(1, window=win)
            w_trans = src.window_transform(win)
            valid = np.isin(arr, list(CROP_NAMES.keys()))
            for geom_dict, val in shapes(arr, mask=valid, transform=w_trans):
                poly = shape(geom_dict).simplify(0.00012, preserve_topology=True)
                if not poly.is_empty and poly.geom_type == "Polygon":
                    poly_records.append({"crop_code": int(val), "geometry": poly})

    if not poly_records:
        # Jeśli lokalny raster nie pokrywa wybranej gminy, zwracamy domyślny zestaw 33UXR
        return (
            pd.read_parquet(APP_DATA_DIR / "fields_static_33uxr.parquet"),
            pd.read_parquet(APP_DATA_DIR / "weather_timeseries_33uxr.parquet"),
        )

    fields_gdf = gpd.GeoDataFrame(poly_records, crs="EPSG:4326")
    fields_gdf["area_ha"] = (fields_gdf.to_crs("EPSG:2180").geometry.area / 10000.0).round(2)
    fields_gdf = fields_gdf[(fields_gdf["area_ha"] >= 0.8) & (fields_gdf["area_ha"] <= 100.0)].copy()
    fields_gdf = fields_gdf.sort_values("area_ha", ascending=False).head(max_fields).reset_index(drop=True)
    fields_gdf["field_id"] = np.arange(len(fields_gdf))

    # 2. Przecięcie z glebą ISRIC SoilGrids (H3 L10)
    soil_files = sorted((ROOT_DIR / "data_local" / "soil").glob("*.parquet"))
    if soil_files:
        soil_df = pd.concat(
            [pd.read_parquet(sf, columns=["h3_index_10", "ph", "soc_0_5cm_mean", "soilTexture"]) for sf in soil_files],
            ignore_index=True,
        ).drop_duplicates(subset=["h3_index_10"]).dropna()
        soil_df["lat"], soil_df["lon"] = _h3_to_latlon(soil_df["h3_index_10"])
        soil_df = soil_df[
            (soil_df["lon"] >= bbox[0] - 0.02) & (soil_df["lon"] <= bbox[2] + 0.02) &
            (soil_df["lat"] >= bbox[1] - 0.02) & (soil_df["lat"] <= bbox[3] + 0.02)
        ].copy()

        if not soil_df.empty:
            soil_gdf = gpd.GeoDataFrame(
                soil_df,
                geometry=[_h3_to_polygon(c) for c in soil_df["h3_index_10"]],
                crs="EPSG:4326",
            )
            joined = gpd.sjoin(fields_gdf, soil_gdf, how="inner", predicate="intersects")
            if not joined.empty:
                agg = joined.groupby("field_id", as_index=False).agg({
                    "h3_index_10": "first",
                    "crop_code": "first",
                    "area_ha": "first",
                    "ph": "mean",
                    "soc_0_5cm_mean": "mean",
                    "soilTexture": lambda s: s.mode().iloc[0],
                    "geometry": "first",
                })
                fields_gdf = gpd.GeoDataFrame(agg, geometry="geometry", crs="EPSG:4326")

    if "h3_index_10" not in fields_gdf.columns:
        fields_gdf["h3_index_10"] = [f"GMINA-{i:04d}" for i in range(len(fields_gdf))]
        fields_gdf["ph"] = 6.2
        fields_gdf["soc_0_5cm_mean"] = 17.5
        fields_gdf["soilTexture"] = "Loam"

    centroids = fields_gdf.to_crs("EPSG:2180").geometry.centroid.to_crs("EPSG:4326")
    fields_gdf["lat"] = centroids.y
    fields_gdf["lon"] = centroids.x
    fields_gdf["crop_name"] = fields_gdf["crop_code"].map(CROP_NAMES)

    # 3. NDVI z lokalnej sceny Sentinel-2 (jeśli gmina leży w zasięgu kafla)
    fields_gdf["ndvi"] = np.float32(0.58)
    sent_dirs = sorted(ROOT_DIR.rglob("S2A_*_L2A"))
    if sent_dirs:
        sdir = sent_dirs[0]
        with rasterio.open(sdir / "red.tif") as sr, rasterio.open(sdir / "nir.tif") as sn, rasterio.open(sdir / "scl.tif") as ss:
            xs, ys = transform("EPSG:4326", sr.crs, fields_gdf["lon"].tolist(), fields_gdf["lat"].tolist())
            sb = sr.bounds
            in_tile = [(sb.left <= x <= sb.right) and (sb.bottom <= y <= sb.top) for x, y in zip(xs, ys)]
            if any(in_tile):
                pts = list(zip(xs, ys))
                rv = np.array([v[0] for v in sr.sample(pts)], dtype="float32")
                nv = np.array([v[0] for v in sn.sample(pts)], dtype="float32")
                sv = np.array([v[0] for v in ss.sample(pts)], dtype="int16")
                ok = np.isin(sv, [4, 5, 7]) & ((nv + rv) > 0)
                ndvi_calc = np.where(ok, (nv - rv) / (nv + rv + 1e-6), 0.55)
                fields_gdf["ndvi"] = np.clip(ndvi_calc, 0.1, 0.92).round(3)

    # 4. Siatka pogodowa + dane godzinowe
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
        fields_gdf["grid_id"] = np.int32(45503190)

    fields_gdf["polygon_json"] = [
        json.dumps([[round(float(x), 6), round(float(y), 6)] for x, y in geom.exterior.coords])
        for geom in fields_gdf.geometry
    ]

    out_fields = pd.DataFrame({
        "h3_index": fields_gdf["h3_index_10"].astype(str),
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
    })

    used_gids = list(out_fields["grid_id"].unique())
    w_local = ROOT_DIR / "data_local" / "weather" / "weather_hourly_2024_Maopolskie.parquet"
    if w_local.exists():
        w_df = pd.read_parquet(w_local)
        w_df["grid_id"] = w_df["grid_id"].astype("int32")
        w_sub = w_df[w_df["grid_id"].isin(used_gids)].copy()
        if not w_sub.empty:
            w_sub["local_time"] = pd.to_datetime(w_sub["local_time"])
            w_sub = w_sub[(w_sub["local_time"] >= "2024-05-18 00:00:00") & (w_sub["local_time"] <= "2024-05-30 23:00:00")].copy()
            sm_col = [c for c in w_sub.columns if "soil_moisture" in c.lower()]
            sm_vals = w_sub[sm_col[0]].round(3).astype("float32") if sm_col else np.float32(0.26)
            out_weather = pd.DataFrame({
                "grid_id": w_sub["grid_id"].astype("int32"),
                "timestamp": w_sub["local_time"],
                "temp_c": w_sub["temperature"].round(1).astype("float32"),
                "humidity_pct": w_sub["relative_humidity"].round(1).astype("float32"),
                "wind_ms": w_sub["wind_speed"].round(1).astype("float32"),
                "precip_24h_mm": np.float32(0.0),
                "soil_moisture": sm_vals,
            })
            return out_fields, out_weather

    out_weather = _fetch_open_meteo_fallback(used_gids, float(g["center_lat"]), float(g["center_lon"]))
    return out_fields, out_weather
