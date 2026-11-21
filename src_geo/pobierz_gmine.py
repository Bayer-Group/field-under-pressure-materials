import json
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone
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

# Kontekst SSL odporny na brak lokalnych certyfikatów w Pythonie na macOS
SSL_CTX = ssl._create_unverified_context()

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


def _fetch_latest_sentinel_ndvi(
    bbox: tuple[float, float, float, float],
    lons: list[float],
    lats: list[float],
    max_cloud_pct: float = 20.0,
) -> tuple[np.ndarray, str]:
    """
    Wyszukuje w Earth Search STAC najświeższą scenę Sentinel-2 L2A dla bbox gminy
    z zachmurzeniem < max_cloud_pct, sprawdza maskę chmur SCL nad polami i liczy NDVI.
    """
    stac_url = "https://earth-search.aws.element84.com/v1/search"
    now_utc = datetime.now(timezone.utc)

    for days_back in (60, 150):
        start_dt = (now_utc - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
        end_dt = now_utc.strftime("%Y-%m-%dT23:59:59Z")
        payload = {
            "collections": ["sentinel-2-l2a"],
            "bbox": list(bbox),
            "datetime": f"{start_dt}/{end_dt}",
            "limit": 8,
            "query": {
                "eo:cloud_cover": {"lt": max_cloud_pct},
            },
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
        except Exception as exc:
            print(f"[Sentinel STAC] Błąd połączenia: {exc}")
            break

        features = data.get("features", [])
        for feat in features:
            assets = feat.get("assets", {})
            red_href = assets.get("red", {}).get("href")
            nir_href = assets.get("nir", {}).get("href")
            scl_href = assets.get("scl", {}).get("href")
            if not (red_href and nir_href and scl_href):
                continue

            scene_date = feat.get("properties", {}).get("datetime", "")[:10]
            try:
                with rasterio.Env(
                    GDAL_HTTP_UNSAFESSL="YES",
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF",
                ):
                    with rasterio.open(scl_href) as src_scl:
                        xs, ys = transform("EPSG:4326", src_scl.crs, lons, lats)
                        pts = list(zip(xs, ys))
                        scl_vals = np.array([v[0] for v in src_scl.sample(pts)], dtype="int16")

                    # Klasy SCL bez chmur i cieni: 4=roślinność, 5=gleba, 6=woda, 7=niesklasyfikowane
                    clear_mask = np.isin(scl_vals, [4, 5, 7])
                    if np.mean(clear_mask) < 0.5:
                        # Większość pól pod lokalną chmurą mimo niskiego cloud_cover kafla — sprawdzamy starszą scenę
                        continue

                    with rasterio.open(red_href) as src_red, rasterio.open(nir_href) as src_nir:
                        red_vals = np.array([v[0] for v in src_red.sample(pts)], dtype="float32")
                        nir_vals = np.array([v[0] for v in src_nir.sample(pts)], dtype="float32")

                valid = clear_mask & ((nir_vals + red_vals) > 0)
                ndvi = np.where(valid, (nir_vals - red_vals) / (nir_vals + red_vals + 1e-6), np.nan)
                ndvi = np.clip(ndvi, -0.1, 0.95)
                median_ndvi = float(np.nanmedian(ndvi)) if np.any(np.isfinite(ndvi)) else 0.55
                ndvi = np.where(np.isfinite(ndvi), ndvi, median_ndvi).round(3).astype("float32")
                print(f"[Sentinel-2] Pobrano świeże pasma z dnia {scene_date} (czyste piksele: {np.mean(clear_mask)*100:.0f}%).")
                return ndvi, scene_date
            except Exception as exc:
                print(f"[Sentinel-2] Pominięto scenę {scene_date}: {exc}")
                continue

    # Fallback do lokalnej sceny Sentinel-2 w razie braku internetu
    sent_dirs = sorted(ROOT_DIR.rglob("S2A_*_L2A"))
    if sent_dirs:
        sdir = sent_dirs[0]
        with rasterio.open(sdir / "red.tif") as sr, rasterio.open(sdir / "nir.tif") as sn, rasterio.open(sdir / "scl.tif") as ss:
            xs, ys = transform("EPSG:4326", sr.crs, lons, lats)
            sb = sr.bounds
            if any((sb.left <= x <= sb.right) and (sb.bottom <= y <= sb.top) for x, y in zip(xs, ys)):
                pts = list(zip(xs, ys))
                rv = np.array([v[0] for v in sr.sample(pts)], dtype="float32")
                nv = np.array([v[0] for v in sn.sample(pts)], dtype="float32")
                sv = np.array([v[0] for v in ss.sample(pts)], dtype="int16")
                ok = np.isin(sv, [4, 5, 7]) & ((nv + rv) > 0)
                ndvi_local = np.where(ok, (nv - rv) / (nv + rv + 1e-6), 0.55)
                return np.clip(ndvi_local, 0.1, 0.92).round(3).astype("float32"), "2024-05-28 (lokalny)"

    return np.full(len(lons), 0.58, dtype="float32"), "brak świeżej sceny"


def _fetch_live_weather(grid_ids: list[int], lat: float, lon: float) -> pd.DataFrame:
    """
    Pobiera aktualną pogodę godzinową (ostatnie 5 dni + 4 dni prognozy) z Open-Meteo
    dla wybranego kafla gminy wraz z wilgotnością gleby i kroczącym opadem 24h.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
        "&past_days=5&forecast_days=4"
        "&hourly=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,soil_moisture_0_to_7cm"
        "&wind_speed_unit=ms&timezone=Europe%2FWarsaw"
    )
    try:
        with urllib.request.urlopen(url, context=SSL_CTX, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        h = payload["hourly"]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(h["time"]),
            "temp_c": pd.Series(h["temperature_2m"]).ffill().bfill().round(1).astype("float32"),
            "humidity_pct": pd.Series(h["relative_humidity_2m"]).ffill().bfill().round(1).astype("float32"),
            "wind_ms": pd.Series(h["wind_speed_10m"]).ffill().bfill().round(1).astype("float32"),
            "precip_1h": pd.Series(h["precipitation"]).fillna(0.0).clip(lower=0.0),
            "soil_moisture": pd.Series(h["soil_moisture_0_to_7cm"]).ffill().bfill().fillna(0.25).round(3).astype("float32"),
        })
        df["precip_24h_mm"] = df["precip_1h"].rolling(24, min_periods=1).sum().round(1).astype("float32")
        # Odrzucamy pierwsze 24h bufora kroczącego
        cutoff = df["timestamp"].min() + pd.Timedelta(hours=24)
        df = df[df["timestamp"] >= cutoff].copy()

        out = []
        for gid in grid_ids:
            sub = df[["timestamp", "temp_c", "humidity_pct", "wind_ms", "precip_24h_mm", "soil_moisture"]].copy()
            sub.insert(0, "grid_id", np.int32(gid))
            out.append(sub)
        print(f"[Pogoda Live] Pobrano {len(df)} godzin aktualnej pogody i prognozy dla ({lat:.3f}, {lon:.3f}).")
        return pd.concat(out, ignore_index=True)
    except Exception as exc:
        print(f"[Pogoda Live] Błąd pobierania z Open-Meteo ({exc}), używam lokalnego zapasu.")
        return pd.read_parquet(APP_DATA_DIR / "weather_timeseries_33uxr.parquet")


def build_gmina_dataset(
    wojewodztwo: str,
    powiat: str,
    gmina: str,
    max_fields: int = 250,
    max_cloud_pct: float = 20.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Dla wybranej gminy:
    1. Wycina rzeczywiste poligony pól z rastra CLMS 10 m,
    2. Łączy je z parametrami gleby ISRIC SoilGrids (pH, SOC, tekstura),
    3. Pobiera najświeższe bezchmurne dane satelitarne Sentinel-2 L2A (NDVI + maska chmur SCL),
    4. Pobiera aktualną pogodę godzinową i prognozę (Open-Meteo + wilgotność gleby).
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
        fields_fallback = pd.read_parquet(APP_DATA_DIR / "fields_static_33uxr.parquet")
        weather_live = _fetch_live_weather(
            list(fields_fallback["grid_id"].unique()),
            float(g["center_lat"]),
            float(g["center_lon"]),
        )
        return fields_fallback, weather_live

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
        fields_gdf["h3_index_10"] = [f"{gmina[:4].upper()}-{i:04d}" for i in range(len(fields_gdf))]
        fields_gdf["ph"] = 6.2
        fields_gdf["soc_0_5cm_mean"] = 17.5
        fields_gdf["soilTexture"] = "Loam"

    centroids = fields_gdf.to_crs("EPSG:2180").geometry.centroid.to_crs("EPSG:4326")
    fields_gdf["lat"] = centroids.y
    fields_gdf["lon"] = centroids.x
    fields_gdf["crop_name"] = fields_gdf["crop_code"].map(CROP_NAMES)

    # 3. Najświeższe dane Sentinel-2 spełniające warunek zachmurzenia i maski SCL
    ndvi_vals, sentinel_date = _fetch_latest_sentinel_ndvi(
        bbox=bbox,
        lons=fields_gdf["lon"].tolist(),
        lats=fields_gdf["lat"].tolist(),
        max_cloud_pct=max_cloud_pct,
    )
    fields_gdf["ndvi"] = ndvi_vals
    fields_gdf["sentinel_date"] = sentinel_date

    # 4. Dopasowanie grid_id i aktualna pogoda godzinowa dla kafla gminy
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
        "sentinel_date": fields_gdf["sentinel_date"].astype(str),
    })

    used_gids = list(out_fields["grid_id"].unique())
    out_weather = _fetch_live_weather(used_gids, float(g["center_lat"]), float(g["center_lon"]))
    return out_fields, out_weather
