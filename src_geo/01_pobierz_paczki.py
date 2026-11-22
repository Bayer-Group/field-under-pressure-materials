import subprocess
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
txt_path = ROOT_DIR / "data_local" / "dhub-pl-hackathon-2026_presigned_urls.txt"

# Dokładne klucze plików potrzebnych dla kafla 33UXR (Kraków / Tarnów / Nowy Sącz)
TARGETS = {
    "cropland/cropland_pl_4326_2024.zip": ROOT_DIR / "data_local" / "cropland",
    "soil_isric_250_v2/soil_Slaskie_isric_250_v2.zip": ROOT_DIR / "data_local" / "soil",
    "soil_isric_250_v2/soil_Swietokrzyskie_isric_250_v2.zip": ROOT_DIR / "data_local" / "soil",
    "soil_isric_250_v2/soil_Podkarpackie_isric_250_v2.zip": ROOT_DIR / "data_local" / "soil",
    "weather_data/hourly/2024/weather_hourly_2024_Malopolskie.zip": ROOT_DIR / "data_local" / "weather",
}

entries = {}
with open(txt_path, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1].startswith("http"):
            entries[parts[0]] = parts[1]

print(f"Wczytano {len(entries)} świeżych linków z pliku .txt.\n")

for key, target_dir in TARGETS.items():
    if key not in entries:
        print(f"[UWAGA] Nie znaleziono klucza: {key}")
        continue

    url = entries[key]
    raw_name = Path(key).name
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / raw_name

    print(f"Pobieranie: {raw_name} -> {target_dir}/ ...")
    subprocess.run(["curl", "-fL", url, "-o", str(file_path)], check=True)

    if file_path.suffix == ".zip":
        print(f"Rozpakowywanie {raw_name}...")
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(target_dir)
        file_path.unlink()
        print(f"Gotowe ({raw_name} rozpakowany i usunięty).\n")

print("Wszystkie paczki (Cropland + Soil + Weather 2024) są gotowe w data_local/!")
