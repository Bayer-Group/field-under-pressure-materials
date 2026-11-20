# 🤖 Instrukcje dla Agenta AI: Moduł Web (`web/`)

> Przed edycją plików w tym folderze zapoznaj się z nadrzędnym plikiem [`/AGENTS.md`](../AGENTS.md) oraz [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Zakres i Rola Modułu (`Scope`)
Folder `web/` odpowiada za lekki podgląd mapowy w przeglądarce internetowej. Służy do:
1. Wizualizacji danych przestrzennych (warstw wektorowych GeoJSON i podkładów kafelkowych) za pomocą biblioteki **MapLibre GL JS**.
2. Demonstracji odpytywania endpointów backendu FastAPI (`/api/v1/analysis/...`) bezpośrednio z przeglądarki.
3. Sprawdzenia poprawności konfiguracji nagłówków CORS po stronie serwera.

---

## 📂 Struktura Katalogu
```text
web/
└── index.html              # Jednoplikowy podgląd mapowy (HTML5 + CSS + vanilla JS + MapLibre GL JS)
```

---

## 🛑 Zasady Specyficzne dla Web (`Twarde Reguły`)

1. **Zakaz wprowadzania ciężkich frameworków:**
   * Nie instaluj ani nie konfiguruj projektów Next.js, React, Vue, Angular, Vite ani Webpack bez wyraźnej dyspozycji człowieka.
   * Moduł ma pozostać ultralekki – otwierany bezpośrednio z dysku jako plik `index.html` lub serwowany jako plik statyczny.
2. **Standardy wizualizacji mapowej:**
   * Używaj otwartoźródłowej biblioteki **MapLibre GL JS** (nie Mapbox GL, który wymaga płatnych kluczy tokenowych).
   * Jako domyślny podkład kafelkowy stosuj darmowe kafelki OpenStreetMap (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`).
3. **Komunikacja z API:**
   * Wywołania sieciowe realizuj za pomocą standardowej funkcji przeglądarki `fetch()`.
   * Zawsze obsługuj błędy sieciowe (`try-catch`), informując użytkownika w czytelny sposób o statusie połączenia z serwerem lokalnym.
