from pathlib import Path
import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT_DIR / "app" / "data_app" / "gminy_polska.parquet"

print("1/2 Wczytywanie granic administracyjnych Polski (Województwo -> Powiat -> Gmina)...")
gdf = gpd.read_file("/tmp/gminy_pol.zip")

print("2/2 Obliczanie zasięgów (bbox) i zapis do Parquet...")
bounds = gdf.geometry.bounds
centroids = gdf.to_crs("EPSG:2180").geometry.centroid.to_crs("EPSG:4326")

gminy_df = pd.DataFrame({
    "wojewodztwo": gdf["NAME_1"].astype(str).str.strip(),
    "powiat": gdf["NAME_2"].astype(str).str.strip(),
    "gmina": gdf["NAME_3"].astype(str).str.strip(),
    "typ_gminy": gdf["TYPE_3"].astype(str).str.strip(),
    "min_lon": bounds["minx"].round(5).astype("float32"),
    "min_lat": bounds["miny"].round(5).astype("float32"),
    "max_lon": bounds["maxx"].round(5).astype("float32"),
    "max_lat": bounds["maxy"].round(5).astype("float32"),
    "center_lat": centroids.y.round(5).astype("float32"),
    "center_lon": centroids.x.round(5).astype("float32"),
})

gminy_df = (
    gminy_df.drop_duplicates(subset=["wojewodztwo", "powiat", "gmina"])
    .sort_values(["wojewodztwo", "powiat", "gmina"])
    .reset_index(drop=True)
)
gminy_df.to_parquet(OUT_PATH, index=False)
print(f"Gotowe! Zapisano {len(gminy_df)} gmin do {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.1f} KB).")
print(gminy_df[gminy_df["wojewodztwo"].str.contains("Małopolskie|Malopolskie", case=False)].head(5))
