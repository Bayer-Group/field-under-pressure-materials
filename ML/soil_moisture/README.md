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

`--help` pokazuje opcje każdego polecenia. Do eksportu trzech pasm dla analizy drzew dodaj `--export-tree-raster` w poleceniu GEE. Instrukcja analizy drzew zawiera format dokumentu i przykład uruchomienia. [Przypisywanie drzew do pikseli](../../db/SETUP.md#obserwacje-satelitarne-drzew)
