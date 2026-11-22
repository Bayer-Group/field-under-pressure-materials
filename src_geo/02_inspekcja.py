from pathlib import Path
import pandas as pd
import rasterio

ROOT_DIR = Path(__file__).resolve().parents[1]

print("=== 1. KAFELKI CROPLAND PASUJĄCE DO 33UXR (lat 49.5-50.5, lon 19.5-21.1) ===")
tif_files = sorted((ROOT_DIR / "data_local" / "cropland").rglob("*.tif"))
print(f"Wszystkich plików .tif w cropland: {len(tif_files)}")
for tif_path in tif_files:
    with rasterio.open(tif_path) as src:
        b = src.bounds
        if b.left < 21.1 and b.right > 19.5 and b.bottom < 50.5 and b.top > 49.5:
            print(f"TRAFIONY: {tif_path.relative_to(ROOT_DIR)} | CRS: {src.crs} | Bounds: {b}")

print("\n=== 2. SCHEMAT GLEBY (SOIL PARQUET) ===")
soil_files = sorted((ROOT_DIR / "data_local" / "soil").rglob("*.parquet"))
if soil_files:
    df_s = pd.read_parquet(soil_files[0])
    print(f"Plik: {soil_files[0].name} | Wiersze: {len(df_s)}")
    print("Kolumny:", list(df_s.columns))
    print(df_s.head(2))

print("\n=== 3. SCHEMAT POGODY (WEATHER PARQUET) ===")
weather_files = sorted((ROOT_DIR / "data_local" / "weather").rglob("*.parquet"))
print(f"Plików pogodowych: {len(weather_files)}")
if weather_files:
    df_w = pd.read_parquet(weather_files[0])
    print(f"Plik: {weather_files[0].name} | Wiersze: {len(df_w)}")
    print("Kolumny:", list(df_w.columns))
    print(df_w.head(2))

