import io
import json
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
APP_DATA_DIR = ROOT_DIR / "app" / "data"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

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

def h3_to_polygon(cell: str) -> Polygon:
    import h3
    if hasattr(h3, "cell_to_boundary"):
        pts = h3.cell_to_boundary(cell)  # [(lat, lon), ...]
    else:
        pts = h3.h3_to_geo_boundary(cell)
    return Polygon([(lon, lat) for lat, lon in pts])

def h3_to_latlon(h3_series: pd.Series):
    import h3
    fn = h3.cell_to_latlng if hasattr(h3, "cell_to_latlng") else h3.h3_to_geo
    coords = [fn(c) for c in h3_series]
    return np.array([c[0] for c in coords]), np.array([c[1] for c in coords])

# Skupiamy się na gęstym zagłębiu rolniczym w obrębie 33UXR (okolice Proszowic / Brzeska / Kazimierzy Wielkiej)
# Dzięki temu na mapie zobaczysz prawdziwą mozaikę sąsiadujących ze sobą pól zamiast rozrzuconych kropek
AOI_BOUNDS = (20.15, 50.05, 20.55, 50.32)  # (min_lon, min_lat, max_lon, max_lat)

print("1/6 Wczytywanie heksagonów glebowych ISRIC SoilGrids (H3 L10)...")
soil_files = sorted((ROOT_DIR / "data_local" / "soil").glob("*.parquet"))
soil_list = [
    pd.read_parquet(sf, columns=["h3_index_10", "ph", "soc_0_5cm_mean", "soilTexture"])
    for sf in soil_files
]
soil_df = pd.concat(soil_list, ignore_index=True).drop_duplicates(subset=["h3_index_10"])
soil_df = soil_df.dropna(subset=["ph", "soc_0_5cm_mean", "soilTexture"]).reset_index(drop=True)
soil_df["lat"], soil_df["lon"] = h3_to_latlon(soil_df["h3_index_10"])

mask_aoi = (
    (soil_df["lon"] >= AOI_BOUNDS[0] - 0.02) & (soil_df["lon"] <= AOI_BOUNDS[2] + 0.02) &
    (soil_df["lat"] >= AOI_BOUNDS[1] - 0.02) & (soil_df["lat"] <= AOI_BOUNDS[3] + 0.02)
)
soil_df = soil_df[mask_aoi].copy().reset_index(drop=True)
soil_gdf = gpd.GeoDataFrame(
    soil_df,
    geometry=[h3_to_polygon(c) for c in soil_df["h3_index_10"]],
    crs="EPSG:4326"
)
print(f"   Heksagony glebowe w rejonie gospodarstw: {len(soil_gdf)}")

print("2/6 Wektoryzacja prawdziwych poligonów pól z rastra CLMS Crop Types 10 m...")
crop_tifs = sorted((ROOT_DIR / "data_local" / "cropland").rglob("*.tif"))
poly_records = []

for tif in crop_tifs:
    with rasterio.open(tif) as src:
        b = src.bounds
        inter_left = max(b.left, AOI_BOUNDS[0])
        inter_bottom = max(b.bottom, AOI_BOUNDS[1])
        inter_right = min(b.right, AOI_BOUNDS[2])
        inter_top = min(b.top, AOI_BOUNDS[3])
        if inter_left >= inter_right or inter_bottom >= inter_top:
            continue

        win = from_bounds(inter_left, inter_bottom, inter_right, inter_top, src.transform)
        arr = src.read(1, window=win)
        win_transform = src.window_transform(win)
        valid_mask = np.isin(arr, list(CROP_NAMES.keys()))

        for geom_dict, val in shapes(arr, mask=valid_mask, transform=win_transform):
            code = int(val)
            poly = shape(geom_dict).simplify(0.00012, preserve_topology=True)
            if poly.is_empty or poly.geom_type != "Polygon":
                continue
            poly_records.append({"crop_code": code, "geometry": poly})

fields_gdf = gpd.GeoDataFrame(poly_records, crs="EPSG:4326")
# Obliczamy prawdziwą powierzchnię w hektarach (układ metryczny EPSG:2180 - PUWG 1992)
fields_metric = fields_gdf.to_crs("EPSG:2180")
fields_gdf["area_ha"] = (fields_metric.geometry.area / 10000.0).round(2)

# Filtrujemy realne działki rolne (od 1.0 ha do 80 ha, odrzucając pojedyncze piksele szumu)
fields_gdf = fields_gdf[(fields_gdf["area_ha"] >= 1.0) & (fields_gdf["area_ha"] <= 80.0)].copy()
fields_gdf = fields_gdf.sort_values("area_ha", ascending=False).head(350).reset_index(drop=True)
fields_gdf["field_id"] = np.arange(len(fields_gdf))
print(f"   Wyodrębniono {len(fields_gdf)} rzeczywistych poligonów pól (łączny areał: {fields_gdf['area_ha'].sum():.1f} ha).")

print("3/6 Przestrzenne łączenie poligonów pól z heksagonami H3 (sjoin)...")
joined = gpd.sjoin(fields_gdf, soil_gdf, how="inner", predicate="intersects")
agg_fields = (
    joined.groupby("field_id", as_index=False)
    .agg({
        "h3_index_10": "first",
        "crop_code": "first",
        "area_ha": "first",
        "ph": "mean",
        "soc_0_5cm_mean": "mean",
        "soilTexture": lambda s: s.mode().iloc[0],
        "geometry": "first",
    })
)
fields_final = gpd.GeoDataFrame(agg_fields, geometry="geometry", crs="EPSG:4326").reset_index(drop=True)
centroids = fields_final.to_crs("EPSG:2180").geometry.centroid.to_crs("EPSG:4326")
fields_final["lat"] = centroids.y
fields_final["lon"] = centroids.x
fields_final["crop_name"] = fields_final["crop_code"].map(CROP_NAMES)
print(f"   Pola połączone z danymi glebowymi H3: {len(fields_final)}")

print("4/6 Obliczanie NDVI z pasm Sentinel-2 L2A (2024-05-28) dla środków pól...")
sent_dir = sorted(ROOT_DIR.rglob("S2A_34UDA_20240528_0_L2A"))[0]
with rasterio.open(sent_dir / "red.tif") as src_red, \
     rasterio.open(sent_dir / "nir.tif") as src_nir, \
     rasterio.open(sent_dir / "scl.tif") as src_scl:

    xs, ys = transform("EPSG:4326", src_red.crs, fields_final["lon"].tolist(), fields_final["lat"].tolist())
    pts_utm = list(zip(xs, ys))

    red_vals = np.array([v[0] for v in src_red.sample(pts_utm)], dtype="float32")
    nir_vals = np.array([v[0] for v in src_nir.sample(pts_utm)], dtype="float32")
    scl_vals = np.array([v[0] for v in src_scl.sample(pts_utm)], dtype="int16")

clear_sky = np.isin(scl_vals, [4, 5, 7]) & ((nir_vals + red_vals) > 0)
ndvi = np.where(clear_sky, (nir_vals - red_vals) / (nir_vals + red_vals + 1e-6), np.nan)
fields_final["ndvi"] = np.clip(ndvi, -0.2, 0.95)
fields_final = fields_final.dropna(subset=["ndvi"]).copy().reset_index(drop=True)

print("5/6 Dopasowanie siatki pogodowej i serializacja geometrii poligonów...")
grids_df = pd.read_parquet(ROOT_DIR / "data_local" / "weather" / "weather_grids.parquet")
grids_mp = grids_df[grids_df["l1_name"].str.contains("Małopolskie", case=False, na=False)].copy().reset_index(drop=True)
g_lats = grids_mp["lat"].astype("float64").values
g_lons = grids_mp["lon"].astype("float64").values
g_ids = grids_mp["grid_id"].astype("int32").values

fields_final["grid_id"] = [
    g_ids[int(np.argmin((g_lats - lat) ** 2 + (g_lons - lon) ** 2))]
    for lat, lon in zip(fields_final["lat"], fields_final["lon"])
]

# Zapisujemy współrzędne poligonu jako JSON string (niezawodny w Parquet i PyDeck)
fields_final["polygon_json"] = [
    json.dumps([[round(float(x), 6), round(float(y), 6)] for x, y in geom.exterior.coords])
    for geom in fields_final.geometry
]

out_static = pd.DataFrame({
    "h3_index": fields_final["h3_index_10"].astype(str),
    "lat": fields_final["lat"].round(5).astype("float32"),
    "lon": fields_final["lon"].round(5).astype("float32"),
    "grid_id": fields_final["grid_id"].astype("int32"),
    "crop_code": fields_final["crop_code"].astype("int16"),
    "crop_name": fields_final["crop_name"].astype(str),
    "ndvi": fields_final["ndvi"].round(3).astype("float32"),
    "soil_ph": fields_final["ph"].round(2).astype("float32"),
    "soil_soc": fields_final["soc_0_5cm_mean"].round(1).astype("float32"),
    "soil_texture": fields_final["soilTexture"].astype(str),
    "area_ha": fields_final["area_ha"].astype("float32"),
    "polygon_json": fields_final["polygon_json"].astype(str),
})
out_static.to_parquet(APP_DATA_DIR / "fields_static_33uxr.parquet", index=False)
print(f"   Zapisano {len(out_static)} prawdziwych poligonów pól do fields_static_33uxr.parquet.")

print("6/6 Aktualizacja szeregu godzinowego pogody + IMERG dla dopasowanych oczek siatki...")
used_gids = set(out_static["grid_id"].unique())
weather_path = ROOT_DIR / "data_local" / "weather" / "weather_hourly_2024_Maopolskie.parquet"
w_df = pd.read_parquet(
    weather_path,
    columns=["grid_id", "utc_time", "local_time", "temperature", "relative_humidity", "wind_speed"]
)
w_df["grid_id"] = w_df["grid_id"].astype("int32")
w_df = w_df[w_df["grid_id"].isin(used_gids)].copy()
w_df["local_time"] = pd.to_datetime(w_df["local_time"])
w_df["utc_time"] = pd.to_datetime(w_df["utc_time"])
w_df = w_df[(w_df["local_time"] >= "2024-05-17 00:00:00") & (w_df["local_time"] <= "2024-05-30 23:00:00")].copy()

precip_zip = ROOT_DIR / "data_local" / "weather" / "hourly" / "2024" / "precip_hourly_2024_Maopolskie.zip"
with zipfile.ZipFile(precip_zip, "r") as zf:
    pq_name = [n for n in zf.namelist() if n.endswith(".parquet")][0]
    p_df = pd.read_parquet(io.BytesIO(zf.read(pq_name)))

p_df["grid_id"] = p_df["grid_id"].astype("int32")
p_df = p_df[p_df["grid_id"].isin(used_gids)].copy()
p_time_col = "utc_time" if "utc_time" in p_df.columns else ("local_time" if "local_time" in p_df.columns else "timestamp")
p_val_col = [c for c in p_df.columns if "precip" in c.lower() or "rain" in c.lower() or "imerg" in c.lower()][0]
p_df[p_time_col] = pd.to_datetime(p_df[p_time_col])

join_time_col = "utc_time" if p_time_col == "utc_time" else "local_time"
merged = pd.merge(
    w_df,
    p_df[["grid_id", p_time_col, p_val_col]],
    left_on=["grid_id", join_time_col],
    right_on=["grid_id", p_time_col],
    how="left"
).sort_values(["grid_id", "local_time"]).reset_index(drop=True)

merged["precip_1h"] = merged[p_val_col].fillna(0.0).clip(lower=0.0)
merged["precip_24h_mm"] = (
    merged.groupby("grid_id")["precip_1h"]
    .transform(lambda s: s.rolling(24, min_periods=1).sum())
    .round(1)
)
merged = merged[merged["local_time"] >= "2024-05-18 00:00:00"].copy()

weather_ts = pd.DataFrame({
    "grid_id": merged["grid_id"].astype("int32"),
    "timestamp": merged["local_time"],
    "temp_c": merged["temperature"].round(1).astype("float32"),
    "humidity_pct": merged["relative_humidity"].round(1).astype("float32"),
    "wind_ms": merged["wind_speed"].round(1).astype("float32"),
    "precip_24h_mm": merged["precip_24h_mm"].astype("float32"),
})
weather_ts.to_parquet(APP_DATA_DIR / "weather_timeseries_33uxr.parquet", index=False)
print(f"   Zapisano {len(weather_ts)} rekordów godzinowych pogody.")
print("\nGOTOWE! Prawdziwe poligony pól są gotowe do wyświetlenia.")
