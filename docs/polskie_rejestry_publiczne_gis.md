# 🗺️ Rejestr Polskich i Europejskich Publicznych Danych Przestrzennych (GIS)

> Kompletne repozytorium wiedzy o oficjalnych, otwartych rejestrach państwowych, usługach sieciowych (WMS, WFS, WCS, REST API) oraz źródłach teledetekcyjnych przydatnych w zaawansowanych analizach przestrzennych, środowiskowych, infrastrukturalnych i hydrologicznych w Polsce.  
> Źródłowy plik tabelaryczny: [`polskie_rejestry_publiczne_gis.csv`](polskie_rejestry_publiczne_gis.csv).

---

## 📑 Spis Treści i Kategorie Źródeł

1. [Kataster, Granice Administracyjne i Ewidencja Gruntów](#1-kataster-granice-administracyjne-i-ewidencja-gruntów)
2. [Numeryczne Modele Terenu, LiDAR i Fotogrametria](#2-numeryczne-modele-terenu-lidar-i-fotogrametria)
3. [Topografia, Sieci i Infrastruktura](#3-topografia-sieci-i-infrastruktura)
4. [Meteorologia, Klimat i Radary Pogodowe](#4-meteorologia-klimat-i-radary-pogodowe)
5. [Wody, Hydrografia i Zagrożenie Powodziowe](#5-wody-hydrografia-i-zagrożenie-powodziowe)
6. [Gleboznawstwo, Geologia i Ruchy Masowe Ziemi](#6-gleboznawstwo-geologia-i-ruchy-masowe-ziemi)
7. [Ochrona Środowiska i Monitorowanie Jakości Powietrza](#7-ochrona-środowiska-i-monitorowanie-jakości-powietrza)
8. [Teledetekcja Satelitarna (Copernicus & Landsat)](#8-teledetekcja-satelitarna)
9. [Statystyka Społeczno-Gospodarcza (GUS BDL)](#9-statystyka-społeczno-gospodarcza)

---

## 1. Kataster, Granice Administracyjne i Ewidencja Gruntów

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **ULDK GUGiK** *(Lokalizacja Działek Katastralnych)* | REST API (WKT, GeoJSON, GML) | `https://uldk.gugik.gov.pl/` | Błyskawiczne pobieranie geometrii i granic działek ewidencyjnych w układzie EPSG:2180 po identyfikatorze TERYT lub klikniętym punkcie XY. |
| **KIEG** *(Krajowa Integracja Ewidencji Gruntów)* | WMS, WFS | `https://integracja.gugik.gov.pl/.../KrajowaIntegracjaEwidencjiGruntow` | Zagregowane granice działek, numery ewidencyjne, kontury klasyfikacyjne i użytki gruntowe ze wszystkich powiatów w Polsce. |
| **PRG** *(Państwowy Rejestr Granic)* | WFS, GML, SHP, GeoPackage | `https://geoportal.gov.pl`, WFS GUGiK | Oficjalny podział terytorialny Polski: granice państwa, województw, powiatów, gmin i obrębów ewidencyjnych. |
| **EMUiA** *(Adresy i Ulice)* | WMS, WFS, CSV | `https://integracja.gugik.gov.pl/.../KrajowaIntegracjaNumeracjiAdresowej` | Punktowa baza wszystkich numerów porządkowych adresów oraz osie ulic w Polsce (geokodowanie). |
| **PRNG** *(Rejestr Nazw Geograficznych)* | GML, SHP, GeoPackage, CSV | `https://dane.gov.pl` | Standaryzowane nazwy miejscowości, rzek, jezior, pasm górskich i lasów. |
| **BDOO** *(Baza Obiektów Ogólnogeograficznych)* | Shapefile, GeoPackage | `https://dane.gov.pl` | Wektorowa mapa ogólnogeograficzna w skali 1:250 000 dla obszaru całego kraju. |
| **LPIS / Działki Referencyjne ARiMR** | WMS, WFS, SHP, GPKG | `https://geoportal.gov.pl`, `https://dane.gov.pl` | Granice bloków i działek referencyjnych w ewidencji gruntów i płatności powierzchniowych. |
| **Corine Land Cover (CLC 2018/2024)** | GeoPackage, SHP, GeoTIFF | `https://clc.gios.gov.pl` | Europejska klasyfikacja pokrycia i użytkowania terenu (44 klasy) dla całej Polski. |
| **Urban Atlas (Copernicus CLMS)** | Shapefile, GeoPackage | `https://land.copernicus.eu` | Wysokorozdzielcza klasyfikacja użytkowania gruntów dla miejskich obszarów funkcjonalnych (FUA). |

---

## 2. Numeryczne Modele Terenu, LiDAR i Fotogrametria

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **NMT GUGiK (Siatka 1 m)** | WCS, WMS, GeoTIFF, ASCII GRID | `https://mapy.geoportal.gov.pl/.../DigitalTerrainModel` | Wysokorozdzielczy model wysokościowy z lotniczego skaningu laserowego (LiDAR 1x1 m): spadki, ekspozycje, bezodpływowe zagłębienia terenu, wskaźnik TWI (*Topographic Wetness Index*). |
| **NMPT GUGiK (Pokrycie Terenu)** | WCS, WMS, GeoTIFF | `https://mapy.geoportal.gov.pl/.../DigitalSurfaceModel` | Model wysokościowy uwzględniający obiekty nad terenem: budynki, lasy, zadrzewienia (barierowość wiatrowa, zacienienie, korytarze przewietrzania). |
| **Chmury Punktów LiDAR (LAS/LAZ)** | LAS, LAZ | `https://geoportal.gov.pl` (skorowidze PZGiK) | Prawdziwe chmury punktów ze skaningu lotniczego (gęstość 4–12 pkt/m²) z klasyfikacją gruntu, budynków i niskiej/średniej/wysokiej wegetacji. |
| **Copernicus DEM (GLO-30)** | Cloud Optimized GeoTIFF (COG) | AWS Open Data, Copernicus Space Data | Jednolity raster wysokościowy 30 m dla całej Europy do analiz makroregionalnych. |
| **Ortofotomapa Lotnicza GUGiK (RGB/CIR)** | WMS, WMTS, WCS, GeoTIFF | `https://mapy.geoportal.gov.pl/.../StandardResolution` | Fotogrametria lotnicza o pikselu 5–25 cm w barwach naturalnych i bliskiej podczerwieni. |

---

## 3. Topografia, Sieci i Infrastruktura

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **BDOT10k (Obiekty Topograficzne)** | WFS, GML, GeoPackage, SHP | `https://geoportal.gov.pl`, WFS GUGiK | Odpowiednik mapy topograficznej 1:10 000: sieć dróg, cieków, budynków, rowów melioracyjnych, ogrodzeń. |
| **GESUT (Sieci Uzbrojenia Terenu)** | WMS | `https://integracja.gugik.gov.pl/.../KrajowaIntegracjaUzbrojeniaTerenu` | Przebiegi sieci wodociągowych, kanalizacyjnych, gazowych, energetycznych i telekomunikacyjnych. |
| **OpenStreetMap Polska (Geofabrik)** | PBF, Shapefile (SHP) | `https://download.geofabrik.de/europe/poland.html` | Pełna baza wektorowa OpenStreetMap dla Polski z codzienną aktualizacją. |
| **GDDKiA (Średni Dobowy Ruch SDR)** | Shapefile, WMS, CSV | `https://www.gov.pl/web/gddkia` | Geometria dróg krajowych i autostrad wraz z natężeniem ruchu pojazdów (Generalny Pomiar Ruchu). |

---

## 4. Meteorologia, Klimat i Radary Pogodowe

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **IMGW-PIB Dane Synoptyczne** | REST API (JSON, CSV, XML) | `https://danepubliczne.imgw.pl/api/data/synop` | Bieżące (co 1h) odczyty ze stacji synoptycznych w Polsce: temperatura powietrza, opad, wilgotność, wiatr, ciśnienie. |
| **IMGW-PIB Dane Meteorologiczne** | REST API (JSON, CSV) | `https://danepubliczne.imgw.pl/api/data/meteo` | Telemetria 10-minutowa ze stacji automatycznych: temperatura gruntu (5 cm), opad 10-minutowy. |
| **IMGW-PIB Ostrzeżenia Meteo/Hydro** | REST API (JSON, GeoJSON) | `https://danepubliczne.imgw.pl/api/data/warnings/meteo` | Aktywne alerty meteorologiczne dla powiatów (przymrozki, burze, grad, upały, wichury). |
| **IMGW-PIB Dane Historyczne** | CSV (paczki ZIP) | `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/` | Wielodekadowe archiwa dobowe i terminowe do kalibracji modeli klimatycznych i analiz trendów. |
| **POLRAD IMGW (Sieć Radarowa)** | WMS, GeoTIFF, HDF5 | `https://danepubliczne.imgw.pl`, WMS IMGW | Mapy odbiciowości radarowej i natężenia opadu co 5–10 minut (detekcja komórek burzowych i gradu). |
| **Open-Meteo Weather & Soil API** | REST API (JSON, CSV) | `https://api.open-meteo.com/v1/forecast` | Darmowe prognozy godzinowe o rozdzielczości 2 km: temperatura, wiatr, wilgotność profilu gleby (0–54 cm). |
| **ERA5-Land Reanalysis (ECMWF)** | NetCDF, GRIB | `https://cds.climate.copernicus.eu` | Globalna reanaliza parametrów lądowych i hydrometeorologicznych w siatce 9 km od 1950 r. |

---

## 5. Wody, Hydrografia i Zagrożenie Powodziowe

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **MPHP (Mapa Podziału Hydrograficznego)** | WFS, Shapefile, GeoPackage | `https://dane.gov.pl`, Wody Polskie | Podstawowy podział hydrograficzny kraju: granice zlewni, działy wodne, osie rzek i jeziora. |
| **Hydroportal / ISOK (Mapy Powodziowe)** | WMS, WFS, Shapefile | `https://wody.isok.gov.pl` | Strefy zalewowe dla prawdopodobieństwa powodzi 10% (raz na 10 lat), 1% (raz na 100 lat) oraz 0.2%. |
| **IMGW-PIB Dane Hydrologiczne** | REST API (JSON, CSV) | `https://danepubliczne.imgw.pl/api/data/hydro` | Stany wód i przepływy na wodowskazach rzecznych w całej Polsce w czasie rzeczywistym. |
| **GIOŚ Monitoring Jakości Wód** | REST API, CSV, Shapefile | `https://wody.gios.gov.pl` | Pomiary fizykochemiczne i biologiczne wód powierzchniowych i podziemnych. |

---

## 6. Gleboznawstwo, Geologia i Ruchy Masowe Ziemi

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **SMSR IUNG-PIB (Monitoring Suszy)** | WMS, CSV, Tabele | `https://susza.iung.pulawy.pl/` | Dekadowy Klimatyczny Bilans Wodny (KBW) oraz wskaźniki deficytu wodnego w podziale na gminy. |
| **Mapy Glebowo-Rolnicze (IUNG/WODGiK)** | WMS, WFS, SHP, GPKG | `https://geoportal.gov.pl` | Kompleksy przydatności rolniczej gleb (1:25 000 / 1:100 000), typy genetyczne, skład granulometryczny i retencja wodna. |
| **Monitoring Chemizmu Gleb Ornych (GIOŚ)** | CSV, XLS, Shapefile | `https://www.gios.gov.pl/chemizm_gleb/` | Pomiary odczynu pH, zawartości węgla organicznego, próchnicy, makro- i mikroelementów w 216 stałych punktach. |
| **SMGP i Mapa Hydrogeologiczna (PIG-PIB)** | WMS, WFS, Shapefile | `https://geologia.pgi.gov.pl` | Szczegółowa Mapa Geologiczna Polski (1:50 000), głębokość zwierciadła wód podziemnych i wodoprzepuszczalność. |
| **MIDAS (Baza Złóż Kopalin PIG-PIB)** | WMS, WFS, Shapefile | `http://midas.pgi.gov.pl` | Lokalizacje złóż kopalin, obszary i tereny górnicze w Polsce. |
| **SOPO (Osłona Przeciwosuwiskowa PIG)** | WMS, WFS, Shapefile | `https://osuwiska.pgi.gov.pl` | Rejestr aktywnych i nieaktywnych osuwisk oraz terenów zagrożonych ruchami masowymi ziemi. |
| **SoilGrids 2.0 (ISRIC / ESDAC)** | WCS, COG (GeoTIFF) | `https://rest.isric.org` | Globalne rastry właściwości gleby 250 m (zawartość piasku, iłu, węgla organicznego, gęstość). |

---

## 7. Ochrona Środowiska i Monitorowanie Jakości Powietrza

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **CRFOP GDOŚ (Formy Ochrony Przyrody)** | WFS, WMS, SHP, GPKG | `https://sdi.gdos.gov.pl/wfs` | Granice obszarów Natura 2000, parków narodowych, rezerwatów i parków krajobrazowych (strefy buforowe). |
| **GIOŚ Jakość Powietrza (Portal Powietrze)** | REST API (JSON) | `https://powietrze.gios.gov.pl/pjp/current/api` | Bieżące dane telemetryczne ze stacji monitoringu powietrza (PM10, PM2.5, NO₂, SO₂, O₃, indeks AQI). |

---

## 8. Teledetekcja Satelitarna

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **Sentinel-2 L2A (Copernicus CDSE)** | STAC API, COG, S3 | `https://catalogue.dataspace.copernicus.eu/stac` | Zobrazowania multispektralne (10–20 m, co 2–5 dni): pasma Red-Edge, NIR, SWIR (wskaźniki NDVI, NDRE, NDMI, chlorofil, wilgotność biomasy). |
| **Sentinel-1 SAR (Copernicus CDSE)** | STAC API, GeoTIFF, S3 | `https://catalogue.dataspace.copernicus.eu/stac` | Radar z syntetyczną aperturą (SAR): niezależne od zachmurzenia pomiary szorstkości, wilgotności przypowierzchniowej i deformacji. |
| **Sentinel-3 SLSTR / OLCI (CDSE)** | STAC API, NetCDF, GeoTIFF | `https://catalogue.dataspace.copernicus.eu/stac` | Codzienne pomiary temperatury powierzchni lądu (LST, 1 km) do wykrywania anomalii termicznych. |
| **Landsat 8/9 Collection 2** | STAC API, COG (GeoTIFF) | `https://earth-search.aws.element84.com/v1` | Pomiary optyczne (30 m) i termalne TIRS (100 m) do bilansów radiacyjnych. |
| **CLMS High Resolution Vegetation (HR-VPP)** | COG, WMS | `https://land.copernicus.eu` | Gotowe rastry 10 m dynamiki wegetacji: start, szczyt i długość sezonu produktywności biomasy. |
| **CLMS Soil Water Index (SWI)** | NetCDF, GeoTIFF | `https://land.copernicus.eu` | Wskaźnik wilgotności profilu glebowego w cyklu dobowym wyliczany z danych radarowych. |

---

## 9. Statystyka Społeczno-Gospodarcza

| Rejestr / Usługa | Protokół & Format | Endpoint / Źródło | Zastosowanie w analizach GIS |
| :--- | :--- | :--- | :--- |
| **GUS BDL (Bank Danych Lokalnych)** | REST API (JSON, XML, CSV) | `https://bdl.stat.gov.pl/api/v1/` | Największa baza statystyczna dla gmin, powiatów i województw (demografia, gospodarka, środowisko, infrastruktura). |
