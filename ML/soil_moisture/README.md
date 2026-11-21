# Analiza wilgotności i nasłonecznienia

Instalacja narzędzi do pracy w środowisku Python:

```powershell
python -m pip install -r ML/soil_moisture/requirements.txt
```

Uruchamiaj polecenia z głównego katalogu repozytorium. Do operacji GEE użyj [konfiguracji projektu i logowania](../../README.md#uruchomienie-z-docker-compose). Skrypty czytają `Orchard.geometry` z MongoDB. Przed pracą lokalną ustaw `MONGO_URI` na adres używany w Compass. [MongoDB i dane drzew](../../db/SETUP.md)

| Polecenie (po `python -m`) | Wynik |
| --- | --- |
| `ML.soil_moisture.import_fields` | Importuje przykładowe granice GeoJSON do `Orchard` |
| `ML.soil_moisture.earth_engine` | Trenuje model, ocenia go i wysyła mapę oraz raporty na Google Drive |
| `ML.soil_moisture.forecast` | Zwraca prognozę z SAR i danych pogodowych do szacowanego przelotu |
| `ML.soil_moisture.solar_intensity_calc` | Zwraca raport nasłonecznienia za zakończoną dobę |
| `ML.soil_moisture.tree_pixel_analysis` | Przypisuje drzewa do pikseli i zapisuje wynik w `TreePixelAnalysis` |
| `ML.soil_moisture.ndvi` | Wysyła medianę NDVI z odfiltrowanych scen Sentinel‑2 na Google Drive |
| `ML.soil_moisture.soil_parameters` | Wysyła na Google Drive osobne rastry pH i klas tekstury gleby OpenLandMap |

`--help` pokazuje opcje każdego polecenia. Do eksportu trzech pasm dla analizy drzew dodaj `--export-tree-raster` w poleceniu GEE. Instrukcja analizy drzew zawiera format dokumentu i przykład uruchomienia. [Przypisywanie drzew do pikseli](../../db/SETUP.md#obserwacje-satelitarne-drzew)

## NDVI i parametry gleby

```powershell
python -m ML.soil_moisture.ndvi --start 2025-06-01 --end 2025-09-01
python -m ML.soil_moisture.soil_parameters --depth-cm 0
```

Oba polecenia odczytują granice z `Orchard.geometry` i respektują `MONGO_ORCHARD_ID`. Możesz też podać `--fields-geojson`. Po uruchomieniu skrypt wypisuje identyfikator zadania GEE. Gotowe GeoTIFF-y znajdziesz na Dysku Google w folderze `ndvi` lub `soil_parameters`. Opcja `--drive-folder` zmienia folder.

`ndvi` liczy bezwymiarowy indeks z pasm B8 i B4 w każdej scenie po zamaskowaniu chmur, cienia chmur i śniegu. Następnie wyznacza medianę w każdym pikselu i eksportuje raster na siatce 10 m. Data `--end` jest wyłączona, a `--max-cloud-percent` ogranicza zachmurzenie całej sceny do 20% domyślnie. [Sentinel‑2 SR Harmonized](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)

`soil_parameters` eksportuje pH w H₂O i całkowite kody tekstury USDA. Katalog OpenLandMap podaje rozdzielczość 250 m, a eksport zachowuje dokładną siatkę źródłową każdego pasma. Dostępne głębokości to 0, 10, 30, 60, 100 i 200 cm. Piksel zostaje uwzględniony, jeśli przecina wybrane pole. Oba skrypty oznaczają brak danych wartością `-9999`. [OpenLandMap pH](https://developers.google.com/earth-engine/datasets/catalog/OpenLandMap_SOL_SOL_PH-H2O_USDA-4C1A2A_M_v02) · [OpenLandMap USDA texture](https://developers.google.com/earth-engine/datasets/catalog/OpenLandMap_SOL_SOL_TEXTURE-CLASS_USDA-TT_M_v02)
