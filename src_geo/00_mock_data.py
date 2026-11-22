import os
import numpy as np
import pandas as pd

np.random.seed(42)
N_FIELDS = 400
N_GRIDS = 25

os.makedirs("app/data", exist_ok=True)

# 1. Statyczna warstwa pól uprawnych (kafel 33UXR: okolice Krakowa i Tarnowa)
lats = np.random.uniform(49.85, 50.25, N_FIELDS).round(5)
lons = np.random.uniform(19.85, 20.65, N_FIELDS).round(5)
grid_ids = np.random.randint(10500, 10500 + N_GRIDS, N_FIELDS).astype("int32")

# Generowanie indeksów H3 (obsługuje h3 v4 i v3, z fallbackiem)
try:
    import h3
    if hasattr(h3, "latlng_to_cell"):
        h3_indices = [h3.latlng_to_cell(lat, lon, 10) for lat, lon in zip(lats, lons)]
    else:
        h3_indices = [h3.geo_to_h3(lat, lon, 10) for lat, lon in zip(lats, lons)]
except ImportError:
    h3_indices = [f"8a1e26b48{i:06x}" for i in range(N_FIELDS)]

crops = [
    (1110, "Pszenica ozima"),
    (1410, "Rzepak ozimy"),
    (1120, "Jęczmień jary"),
]
chosen = np.random.choice(len(crops), N_FIELDS, p=[0.50, 0.30, 0.20])

# Miks NDVI: 25% odkryta gleba pod siew (<0.25), 15% dojrzałe pod żniwa (0.25-0.31), 60% pełna wegetacja
ndvi_values = np.concatenate([
    np.random.uniform(0.12, 0.24, int(N_FIELDS * 0.25)),
    np.random.uniform(0.25, 0.30, int(N_FIELDS * 0.15)),
    np.random.uniform(0.45, 0.85, N_FIELDS - int(N_FIELDS * 0.25) - int(N_FIELDS * 0.15)),
])
np.random.shuffle(ndvi_values)

fields_df = pd.DataFrame({
    "h3_index": h3_indices,
    "lat": lats.astype("float32"),
    "lon": lons.astype("float32"),
    "grid_id": grid_ids,
    "crop_code": np.array([crops[i][0] for i in chosen], dtype="int16"),
    "crop_name": [crops[i][1] for i in chosen],
    "ndvi": ndvi_values.round(3).astype("float32"),
    "soil_ph": np.random.uniform(5.0, 7.2, N_FIELDS).round(2).astype("float32"),
    "soil_soc": np.random.uniform(11.0, 28.0, N_FIELDS).round(1).astype("float32"),
    "soil_texture": np.random.choice(["Loam", "Sandy Loam", "Silt Loam", "Clay Loam"], N_FIELDS),
})
fields_df.to_parquet("app/data/fields_static_33uxr.parquet", index=False)

# 2. Godzinowa szeregowa pogoda (72 godziny = 3 doby co 1h dla każdego grid_id)
timestamps = pd.date_range("2024-05-18 00:00", periods=72, freq="1h")
weather_rows = []

for ts in timestamps:
    hour = ts.hour
    base_temp = 17.0 + 6.0 * np.sin((hour - 8) * np.pi / 12)
    base_hum = 74.0 - 18.0 * np.sin((hour - 8) * np.pi / 12)
    base_wind = 3.2 + 2.2 * np.sin((hour - 9) * np.pi / 12)
    rain_spike = 4.5 if (ts.day == 19 and 14 <= hour <= 17) else 0.0

    for gid in range(10500, 10500 + N_GRIDS):
        weather_rows.append({
            "grid_id": np.int32(gid),
            "timestamp": ts,
            "temp_c": round(float(base_temp + np.random.normal(0, 0.8)), 1),
            "humidity_pct": round(float(np.clip(base_hum + np.random.normal(0, 3.0), 35, 98)), 1),
            "wind_ms": round(float(np.clip(base_wind + np.random.normal(0, 0.7), 0.5, 11.0)), 1),
            "precip_24h_mm": round(float(max(0.0, rain_spike + np.random.choice([0.0, 0.0, 0.5]))), 1),
        })

weather_df = pd.DataFrame(weather_rows)
weather_df.to_parquet("app/data/weather_timeseries_33uxr.parquet", index=False)
print("Gotowe! Utworzono pliki testowe w app/data/:")
print(f" - fields_static_33uxr.parquet ({len(fields_df)} pól)")
print(f" - weather_timeseries_33uxr.parquet ({len(weather_df)} rekordów godzinowych)")
