# Specyfikacja API i Podkładu Satelitarnego dla UI (`Field Under Pressure`)

Dokumentacja opisuje:
1. **Źródło i dokładne parametry podkładu satelitarnego**, który idealnie zgrywa się z geometrią wektorową sadu (`EPSG:4326`).
2. **Wszystkie endpointy HTTP**, ich parametry, schematy request/response oraz mapowanie na kolekcje MongoDB (`Orchard`, `Tree`, `CropPref`) wymagane do pełnej obsługi warstwy `ui/`.

---

## 1. Podkład satelitarny (źródło i parametry)

Idealnie dopasowany podkład w edytorze linii rzędów (`RowLineEditorCanvas.tsx`) renderowany jest z publicznego serwisu kafelków **Esri World Imagery** przez funkcję `buildSatelliteTiles()` w `ui/src/utils/orchardGeometry.ts`.

### Parametry żądań kafelków
| Parametr | Wartość | Opis |
|---|---|---|
| **Dostawca** | Esri World Imagery (ArcGIS Online) | Publiczne kafelki satelitarne / lotnicze wysokiej rozdzielczości |
| **Szablon URL** | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` | Uwaga na kolejność w URL Esri: `/{z}/{y}/{x}` (najpierw wiersz `y`, potem kolumna `x`) |
| **Zoom (`z`)** | `18` | Rozdzielczość rzędu ~0,37 m/px dla szerokości geograficznej Polski (~51,8°N) |
| **Rozmiar kafelka** | `256 × 256 px` | Standardowy kafelek XYZ / Slippy Map |
| **Układ kafelków (źródłowy)** | Web Mercator (`EPSG:3857`) | Natywny układ serwera kafelków Esri |
| **Układ danych wektorowych** | WGS 84 (`EPSG:4326`) | Wszystkie współrzędne `Orchard.geometry`, `Orchard.rows` i `Tree.coordinates` |
| **Margines wokół pola** | `120 m` (`padMeters = 120`) + `±1` kafelek bufora | Zapewnia pełne pokrycie otoczenia sadu podczas przesuwania widoku |
| **Limit siatki** | `maxTilesPerAxis = 7` (maks. `8 × 8` kafelków) | Ochrona przed nadmierną liczbą zapytań przy dużych działkach |

### Jak działa dopasowanie kafelków do `EPSG:4326` (dlaczego skala jest idealna)
1. Dla każdego kafelka `(z, x, y)` wyznaczane są dokładne granice geograficzne w **WGS 84 (`EPSG:4326`)** odwrotną transformacją Web Mercatora:
   - `westLng = (x / 2^z) * 360 - 180`
   - `eastLng = ((x + 1) / 2^z) * 360 - 180`
   - `northLat = (180 / π) * atan(sinh(π * (1 - 2 * y / 2^z)))`
   - `southLat = (180 / π) * atan(sinh(π * (1 - 2 * (y + 1) / 2^z)))`
2. Narożniki każdego kafelka (`SW`, `NE`) oraz wierzchołki poligonu sadu są przeliczane tym samym lokalnym rzutem metrycznym względem centroidu sadu (`lat0`, `lng0`):
   - `x [m] = (lng - lng0) * 111320 * cos(lat0)`
   - `y [m] = (lat - lat0) * 111320`
3. Każdy kafelek jest renderowany dokładnie w swoim prostokącie `[xMin..xMax, yMin..yMax]` z `preserveAspectRatio="none"`, dzięki czemu geometria wektorowa `EPSG:4326` oraz podkład satelitarny pokrywają się co do piksela bez rozjeżdżania proporcji osi.

> **Wskazówka (własny raster z backendu):** Jeśli w przyszłości backend wygeneruje własny pojedynczy raster (np. z Sentinel-2 albo drona), obiekt `OrchardBoundaryDoc` wspiera opcjonalne pole `satelliteOverlay` (`imageUrl`, `crs: "EPSG:4326"`, `bounds: { westLng, southLat, eastLng, northLat }`). Aby uniknąć rozjazdu skali, wygenerowany obraz musi mieć dokładnie proporcje pikseli odpowiadające `bounds` (bez automatycznego rozszerzania bboxa po stronie serwera rastra).

---

## 2. Konfiguracja połączenia UI ↔ Backend

Pliki po stronie UI:
- `ui/src/config/apiConfig.ts` — baza URL i rejestr ścieżek
- `ui/src/api/httpClient.ts` — klient HTTP (`Accept: application/json`, `Content-Type: application/json`, timeout `4000 ms`)
- `ui/src/api/orchardApi.ts` — funkcje transferu danych
- `ui/src/types/orchard.ts` — kontrakty TypeScript

Zmienne środowiskowe w `ui/.env`:
```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_PLACEHOLDERS=false
```

Wymagania ogólne po stronie backendu:
- **CORS:** zezwolić na origin dev serwera UI (domyślnie `http://localhost:5173`) oraz metody `GET, POST, PATCH, DELETE, OPTIONS` i nagłówki `Content-Type, Accept`.
- **Format identyfikatorów:** `ObjectIdString` to 24-znakowy hex string MongoDB `ObjectId` (np. `"6b01933c1dc02a368703a020"`).
- **Układ współrzędnych:** wszystkie pola `GeoCoord` używają **WGS 84 (`EPSG:4326`)** w formacie `{ "lat": number, "lng": number }`.

---

## 3. Lista endpointów API

### Przegląd zbiorczy

| Metoda | Ścieżka | Ekran UI | Kolekcje MongoDB / źródło |
|---|---|---|---|
| `GET` | `/api/v1/weather/temperature` | Dashboard (wykres temp. min/max) | Dane pogodowe / `Orchard.environmentalData` |
| `GET` | `/api/v1/orchard/health` | Dashboard (wskaźnik zdrowia sadu) | `Tree` (agregacja `healthIndex`) |
| `GET` | `/api/v1/orchard/scene` | Dashboard (metadane 3D, granica i drzewa) | `Orchard`, `Tree` |
| `GET` | `/api/v1/orchards/{orchardId}/point-cloud.las` | Dashboard (binarna chmura punktów `.las`) | Pliki LiDAR `ui/public/las/{_id}.las` (np. `6b01933c1dc02a368703a020.las`) |
| `GET` | `/api/v1/orchard/point-cloud` | Dashboard / warstwy 3D (alternatywny JSON) | Chmura punktów LiDAR / fotogrametria |
| `GET` | `/api/v1/orchard/trees` | Dashboard / warstwy 3D (granularny) | `Tree` |
| `GET` | `/api/v1/orchard/row-lines` | Dashboard / podgląd rzędów | `Orchard.rows` |
| `POST` | `/api/v1/orchard/row-lines` | Pomocniczy zapis samych polilinii | `Orchard.rows` |
| `PATCH` | `/api/v1/orchard/trees/{treeId}` | Inspektor pojedynczego drzewa | `Tree` |
| `GET` | `/api/v1/orchards` | Górny pasek (dropdown wyboru sadu) | `Orchard` |
| `GET` | `/api/v1/users/{userId}/preferences` | Górny pasek (odczyt preferencji użytkownika) | `User.preferences` |
| `PATCH` | `/api/v1/users/{userId}/preferences` | Górny pasek (zapis sadu, motywu i języka) | `User.preferences` |
| `GET` | `/api/v1/crop-prefs` | Edytor linii rzędów (paleta gatunków) | `CropPref` |
| `GET` | `/api/v1/orchards/{orchardId}` | Edytor linii rzędów (geometria pola + rzędy) | `Orchard` |
| `POST` | `/api/v1/orchards/{orchardId}/layout` | Edytor linii rzędów (zapis rzędów i drzew) | `Orchard` + `Tree` |

---

### 3.1. `GET /api/v1/weather/temperature`
Pobiera szereg czasowy temperatur minimalnych i maksymalnych do wykresu liniowego z dostrajaniem skali czasu.

- **Query params:**
  - `orchardId` (`string`, wymagany) — ObjectId sadu (np. `6b01933c1dc02a368703a020`)
  - `range` (`"24h" | "7d" | "30d" | "90d" | "1y"`, wymagany) — zakres czasowy
- **Response `200 OK`:**
```json
{
  "orchardId": "6b01933c1dc02a368703a020",
  "range": "30d",
  "unit": "C",
  "points": [
    {
      "timestamp": "2026-11-20T12:00:00.000Z",
      "label": "20.11",
      "minTempC": 2.4,
      "maxTempC": 11.8
    }
  ]
}
```

---

### 3.2. `GET /api/v1/orchard/health`
Zwraca uśredniony wskaźnik kondycji całego sadu oraz rozkład liczby drzew w 4-stopniowej skali zdrowia.

- **Query params:**
  - `orchardId` (`string`, wymagany)
- **Skala mapowania `averageScore` (0–100) → `HealthStatus` (kolory w UI):**
  - `0–15` → `"dead"` (czarny — martwe)
  - `16–45` → `"poor"` (czerwony — zły stan)
  - `46–72` → `"moderate"` (pomarańczowy — średni)
  - `73–100` → `"healthy"` (zielony — poprawny)
- **Response `200 OK`:**
```json
{
  "orchardId": "6b01933c1dc02a368703a020",
  "updatedAt": "2026-11-21T14:30:00.000Z",
  "averageScore": 74,
  "overallStatus": "healthy",
  "totalTrees": 117,
  "distribution": {
    "dead": 4,
    "poor": 14,
    "moderate": 26,
    "healthy": 73
  }
}
```

---

### 3.3. `GET /api/v1/orchard/scene`
Zwraca kompletny zestaw danych do renderera 3D (chmura punktów + pojedyncze drzewa 3D + linie rzędów).

- **Query params:**
  - `orchardId` (`string`, wymagany)
- **Response `200 OK`:**
```json
{
  "orchardId": "6b01933c1dc02a368703a020",
  "orchardName": "Sad Grójec — Kwatera Północna",
  "pointCloud": {
    "orchardId": "6b01933c1dc02a368703a020",
    "pointCount": 10582,
    "positions": [0.12, 0.45, -1.23],
    "colors": [0.22, 0.65, 0.31],
    "bounds": {
      "min": { "x": -36, "y": -2.2, "z": -29 },
      "max": { "x": 36, "y": 6.5, "z": 29 }
    }
  },
  "trees": [
    {
      "id": "67401e000001000001000001",
      "rowId": "row-01",
      "rowLabel": "R-01",
      "indexInRow": 1,
      "position": { "x": -14.2, "y": 0.42, "z": -10.8 },
      "geo": { "lat": 51.84512, "lng": 20.85291 },
      "heightMeters": 3.45,
      "canopyRadiusMeters": 1.35,
      "healthScore": 84,
      "healthStatus": "healthy"
    }
  ],
  "rowLines": [
    {
      "id": "row-01",
      "orchardId": "6b01933c1dc02a368703a020",
      "rowLabel": "R-01",
      "vertices": [
        { "x": -28, "y": 0.1, "z": -10.8 },
        { "x": 28, "y": 0.3, "z": -10.8 }
      ],
      "treeSpacingMeters": 3.5,
      "createdAt": "2026-11-21T14:30:00.000Z"
    }
  ]
}
```
> Uwaga: `positions` i `colors` to płaskie tablice o długości `3 * pointCount` (`[x0, y0, z0, ...]`, kolory znormalizowane do `[0.0, 1.0]`).

---

### 3.4. `GET /api/v1/orchards/{orchardId}/point-cloud.las` (binarna chmura punktów LiDAR)
Zwraca surowy binarny plik **`.las`** (nieskompresowany LAS `1.1–1.4`, obsługiwane formaty punktów `0, 1, 2, 3, 6, 7, 8`) do bezpośredniego parsowania po stronie przeglądarki (`ui/src/utils/lasParser.ts`).

- **Path param:** `orchardId` (`ObjectIdString`, dla prezentacji: `6b01933c1dc02a368703a020` → **`Grojec A`**)
- **Nagłówki odpowiedzi:**
  - `Content-Type: application/octet-stream`
  - `Content-Disposition: inline; filename="{orchardId}.las"`
- **Brak pliku (`404 Not Found`):** jeśli dla danego sadu nie ma jeszcze pliku `{_id}.las`, UI automatycznie i bezbłędnie przełącza się na **widok geometryczny 3D** (obrys działki + rzędy + pojedyncze drzewa 3D na płaszczyźnie terenu).
- **Układ współrzędnych (CRS):** PUWG 1992 (**`EPSG:2180`**). UI automatycznie przelicza wektory `Orchard` / `Tree` z **WGS 84 (`EPSG:4326`)** na `EPSG:2180` (`ui/src/utils/crs2180.ts`) oraz dopasowuje wysokość posadowienia drzew `Y` do siatki punktów gruntu (klasa ASPRS `2`) z pliku `.las`.
- **Konwencja plików w repozytorium:** `ui/public/las/{_id}.las`, np. `ui/public/las/6b01933c1dc02a368703a020.las` (`LAS 1.2`, Point Format `3` z RGB i klasyfikacją, `513 074` punktów, zasięg `220.6 × 153.3 × 8.8 m`, sad **`Grojec A`**).

### 3.5. Granularne endpointy danych 3D i drzew
Przygotowane do niezależnego dociągania warstw:

- **`GET /api/v1/orchard/point-cloud?orchardId={id}`** → zwraca sam obiekt `PointCloudData` (jak `scene.pointCloud`).
- **`GET /api/v1/orchard/trees?orchardId={id}`** → zwraca tablicę `OrchardTree3D[]` (jak `scene.trees`).
- **`GET /api/v1/orchard/row-lines?orchardId={id}`** → zwraca tablicę `RowLineRecord[]` (jak `scene.rowLines`).
- **`POST /api/v1/orchard/row-lines`** — wysyła polilinie rzędów (`{ "rows": RowLineInput[] }`), zwraca `RowLineRecord[]`.
- **`PATCH /api/v1/orchard/trees/{treeId}`** — aktualizuje metadane pojedynczego drzewa:
  - **Path param:** `treeId` (`ObjectIdString`)
  - **Request body:**
    ```json
    {
      "healthStatus": "moderate",
      "healthScore": 62,
      "notes": "Widoczne uszkodzenia przymrozkowe"
    }
    ```
  - **Response `200 OK`:** `{ "id": "<treeId>", "updated": true }`

---

### 3.5. `GET /api/v1/crop-prefs`
Pobiera katalog gatunków drzew z kolekcji MongoDB `CropPref` do panelu wyboru gatunku w Edytorze Linii Rzędów.

- **Query params:** brak
- **Response `200 OK`:** tablica `CropPrefDoc[]`
```json
[
  {
    "_id": "6b00ce879a422805ed102006",
    "code": "malus-domestica",
    "scientificName": "Malus domestica",
    "namePl": "Jabłoń domowa",
    "nameEn": "Apple",
    "variety": "Malus domestica",
    "category": "pome",
    "recommendedSpacingMeters": 3.5,
    "colorHex": "#ef4444"
  }
]
```
> Pola `namePl`, `nameEn`, `recommendedSpacingMeters`, `colorHex` mogą być przechowywane bezpośrednio w `CropPref` albo mapowane w warstwie API na podstawie `CropPref.species` (np. `Malus domestica`, `Pyrus communis`, `Prunus avium`, `Prunus armeniaca`, `Juglans regia`). Kluczowe jest zwracanie prawdziwego `_id` z kolekcji `CropPref`, ponieważ trafia ono jako `Tree.species`.

---

### 3.6. `GET /api/v1/orchards/{orchardId}`
Pobiera geometrię działki sadu oraz zapisane rzędy z kolekcji MongoDB `Orchard`. Dla nowego („pustego”) sadu pole `rows` powinno wynosić `[]`.

- **Path param:** `orchardId` (`ObjectIdString`, np. `6b01933c1dc02a368703a020`)
- **Response `200 OK`:** `OrchardBoundaryDoc`
```json
{
  "_id": "6b01933c1dc02a368703a020",
  "name": "Orchard 6b01933c…a020",
  "locationLabel": "Okolice Grójca · WGS 84 (EPSG:4326)",
  "geometry": [
    { "lat": 51.8444703, "lng": 20.8518509 },
    { "lat": 51.8455777, "lng": 20.8519484 }
  ],
  "center": { "lat": 51.845271, "lng": 20.8532721 },
  "areaHectares": 2.22,
  "shapeAreaM2": 22195.94,
  "shapeLengthM": 666.7,
  "rows": []
}
```
> W MongoDB `Orchard.geometry` ma obecnie format GeoJSON `MultiPolygon` z tablicą `[lng, lat, 0]` oraz polami `shapeArea`, `shapeLength`. Backend mapuje zewnętrzny pierścień na listę `{ lat, lng }` (WGS 84 / `EPSG:4326`) i wylicza `center` oraz `areaHectares = shapeArea / 10000`.

---

### 3.8. `GET /api/v1/orchards`
Zwraca listę sadów przypisanych do użytkownika do dropdownu wyboru sadu na górnym pasku.

- **Response `200 OK`:** `OrchardOption[]`
```json
[
  {
    "_id": "6b01933c1dc02a368703a020",
    "name": "Grojec A",
    "areaHectares": 2.22,
    "centroid": { "lat": 51.8450065, "long": 20.8530536 }
  }
]
```

---

### 3.9. `GET` / `PATCH /api/v1/users/{userId}/preferences`
Odczytuje i zapisuje 3 wybory użytkownika z górnego paska (wyświetlany sad, motyw i język) bezpośrednio w `User.preferences` w MongoDB.

- **Path param:** `userId` (`ObjectIdString`, np. `6b00ded99a422805ed10200c`)
- **Request body (`PATCH`) / Response `200 OK` (`GET` i `PATCH`):**
```json
{
  "theme": "OS",
  "lang": "pl",
  "activeOrchardId": "6b01933c1dc02a368703a020"
}
```
- **Walidacja MongoDB `User.preferences`:**
  - `theme`: enum `"Light" | "Dark" | "OS"` (UI mapuje `light/dark/system` ↔ `Light/Dark/OS`)
  - `lang`: `"pl" | "en"`
  - `activeOrchardId`: `ObjectId` sadu lub `null`

---

### 3.10. `POST /api/v1/orchards/{orchardId}/layout`
Główny endpoint zapisu z **Edytora Linii Rzędów**. Przyjmuje narysowane rzędy oraz wyliczone współrzędne pojedynczych drzew.

- **Path param:** `orchardId` (`ObjectIdString`)
- **Request body (`SaveOrchardLayoutRequest`):**
```json
{
  "orchardId": "6b01933c1dc02a368703a020",
  "orchardRows": [
    {
      "id": "row-1763733000000-1",
      "label": "R-01",
      "start": { "lat": 51.84461, "lng": 20.85192 },
      "end": { "lat": 51.84462, "lng": 20.85355 },
      "averageSpacingMeters": 3.5,
      "treeIds": [
        "67401e000001000001000001",
        "67401e000001000001000002"
      ]
    }
  ],
  "trees": [
    {
      "_id": "67401e000001000001000001",
      "orchardId": "6b01933c1dc02a368703a020",
      "coordinates": { "lat": 51.8446105, "lng": 20.8519852 },
      "healthIndex": null,
      "species": "6b00ce879a422805ed102006"
    },
    {
      "_id": "67401e000001000001000002",
      "orchardId": "6b01933c1dc02a368703a020",
      "coordinates": { "lat": 51.8446111, "lng": 20.8520361 },
      "healthIndex": null,
      "species": "6b00ce879a422805ed102006"
    }
  ]
}
```
- **Oczekiwane zachowanie backendu:**
  1. Zapisać dokumenty z tablicy `trees` w kolekcji **`Tree`** z prawdziwymi `ObjectId` (`_id`), zachowując `coordinates` (`EPSG:4326`), `species` (jako `ObjectId` do `CropPref`) oraz `healthIndex: null` (lub od razu wyliczony/zakolejkowany do wyliczenia przez silnik ML/analityczny).
  2. Zaktualizować dokument w kolekcji **`Orchard`** (`_id: orchardId`), zapisując w polu `rows` dwa punkty (`start`, `end`), `averageSpacingMeters` oraz **uporządkowaną tablicę `treeIds`** (`ObjectId[]`) odpowiadającą kolejności drzew na tym rzędzie (jeśli backend generuje własne `_id` zamiast używać tymczasowych z UI, powinien zmapować je 1:1 do `orchardRows[i].treeIds`).
- **Response `200 OK` (`SaveOrchardLayoutResponse`):**
```json
{
  "orchardId": "6b01933c1dc02a368703a020",
  "savedRowsCount": 1,
  "savedTreesCount": 2,
  "updatedAt": "2026-11-21T15:15:00.000Z",
  "orchard": {
    "_id": "6b01933c1dc02a368703a020",
    "rows": [
      {
        "id": "row-1763733000000-1",
        "label": "R-01",
        "start": { "lat": 51.84461, "lng": 20.85192 },
        "end": { "lat": 51.84462, "lng": 20.85355 },
        "averageSpacingMeters": 3.5,
        "treeIds": [
          "67401e000001000001000001",
          "67401e000001000001000002"
        ]
      }
    ]
  },
  "trees": [
    {
      "_id": "67401e000001000001000001",
      "orchardId": "6b01933c1dc02a368703a020",
      "coordinates": { "lat": 51.8446105, "lng": 20.8519852 },
      "healthIndex": null,
      "species": "6b00ce879a422805ed102006"
    }
  ]
}
```
