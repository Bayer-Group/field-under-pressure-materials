# 🤝 Przewodnik Kontrybucji (CONTRIBUTING)

Dziękujemy za wkład w rozwój projektu **PyQGIS FastAPI Bridge**!  
Niezależnie od tego, czy pracujesz samodzielnie, w zespole ludzkim, czy wspomagasz się agentami AI, w projekcie obowiązują poniższe zasady pracy z repozytorium, standardy kodu oraz konwencje commitów.

---

## 🧭 Filozofia: Human-First Development

W tym repozytorium obowiązuje żelazna zasada **Human-First**:
* **Człowiek jest Architektem i Decydentem.** Wszystkie decyzje o architekturze, strukturze danych, doborze technologii i logice biznesowej podejmuje człowiek.
* **AI jest Narzędziem Wykonawczym.** Asystenci AI (Copilot, Claude, Gemini, ChatGPT itp.) pełnią rolę precyzyjnych wykonawców poleceń – nigdy nie podejmują decyzji za człowieka, nie zmieniają architektury i nie dodają bibliotek bez wyraźnej dyspozycji.

Szczegółowe wytyczne dla agentów sztucznej inteligencji znajdują się w plikach [`AGENTS.md`](AGENTS.md) w poszczególnych katalogach.

---

## 🎯 Model Pracy: Issue-Driven Development (Zwinny Podział Obowiązków)

Aby utrzymać przejrzysty podział obowiązków, uniknąć konfliktów w kodzie i nie tamować tempa prac niepotrzebną biurokracją:

1. **Każde zadanie zaczynamy od GitHub Issue:**
   * Zanim zaczniesz pisać kod lub zlecisz zadanie agentowi AI, utwórz krótkie zgłoszenie w zakładce **Issues**.
   * Wybierz szablon **🚀 Nowe Zadanie (Task)** lub utwórz zwięzłe zgłoszenie.
2. **Lekki, nietamujący format Issue:**
   Wystarczą 3 konkretne punkty:
   * **Cel (1-2 zdania):** Co robimy i po co (np. *"Dodać endpoint pobierania obrysu działki w formacie GeoJSON z ULDK"*).
   * **Moduł i Odpowiedzialny:** Kto bierze zadanie (`backend`, `qgis_plugin`, `web`, `docs`).
   * **Checklista ukończenia (Definition of Done):** 2-3 punkty weryfikujące gotowość (np. `- [ ] endpoint zwraca 200 OK`, `- [ ] test jednostkowy przechodzi`).
3. **Płynny przepływ (Issue $\rightarrow$ Branch $\rightarrow$ Commit):**
   * Tworzymy gałąź powiązaną z zadaniem: np. `feat/12-uldk-geojson` (gdzie 12 to numer issue).
   * Commit zamykający: `feat(backend): add uldk geojson endpoint (closes #12)`.
   * Dzięki temu cały zespół od razu widzi, kto nad czym pracuje, bez chaosu i dublowania pracy.

---

## 🌿 Model Pracy z Gitem (GitHub Flow)

Pracujemy w oparciu o prosty, zwinny model **GitHub Flow**:
1. Gałąź `master` (lub `main`) jest zawsze stabilna i gotowa do uruchomienia.
2. Każdą nową funkcjonalność lub poprawkę tworzymy na dedykowanej gałęzi odchodzącej od `master`.
3. Nazewnictwo gałęzi:
   * `feat/<nazwa-funkcji>` – nowe funkcjonalności (np. `feat/uldk-polygon-loader`)
   * `fix/<opis-bledu>` – naprawa błędów (np. `fix/crs-transformation-epsg2180`)
   * `docs/<temat>` – zmiany w dokumentacji (np. `docs/update-datasets-guide`)
   * `refactor/<zakres>` – przebudowa istniejącego kodu bez zmiany zachowania
4. Po ukończeniu prac tworzymy Pull Request lub po weryfikacji przez człowieka scalamy do `master`.

---

## 📝 Konwencja Commitów (Conventional Commits)

Wszystkie commity w repozytorium **muszą** być formatowane zgodnie ze specyfikacją [Conventional Commits v1.0.0](https://www.conventionalcommits.org/):

```text
<typ>(<opcjonalny-zakres>): <zwięzły opis w trybie rozkazującym>

[opcjonalna treść wyjaśniająca motywację i kontekst zmiany]
```

### Dozwolone typy:
* **`feat`** – dodanie nowej funkcjonalności (np. `feat(backend): add endpoint for parcel bounding box`)
* **`fix`** – naprawa błędu (np. `fix(qgis): resolve task crash on empty polygon geometry`)
* **`docs`** – zmiany wyłącznie w dokumentacji (np. `docs: add contributing guide and agent rules`)
* **`refactor`** – refaktoryzacja kodu (np. `refactor(shared): simplify geo response schema`)
* **`perf`** – optymalizacja wydajności (np. `perf(backend): cache spatial index lookups`)
* **`test`** – dodanie lub modyfikacja testów jednostkowych
* **`chore`** – prace porządkowe, konfiguracja repozytorium, skrypty pomocnicze (np. `chore: update gitignore`)

### Przykłady poprawnych komunikatów:
* `feat(ingestion): add retry logic to uldk connector`
* `fix(plugin): prevent GUI freeze by offloading network request to QgsTask`
* `docs(datasets): register new LiDAR WCS endpoint from GUGiK`
* `refactor(backend): decouple router configuration from app instance`

---

## 💻 Standardy Jakości Kodu

### 1. Python (Backend & Shared)
* Kod zgodny z **PEP 8** (czytelne nazwy, wcięcia 4 spacje, przejrzyste moduły).
* Obowiązkowe **Type Hints** we wszystkich sygnaturach funkcji i metod.
* Używamy modeli **Pydantic** do walidacji danych wejściowych i wyjściowych API.
* **Decyzja o zależnościach należy do człowieka:** Agent AI nie instaluje ani nie dodaje samowolnie nowych bibliotek. Wybór narzędzi (np. `httpx`, `requests`, `shapely`, `geopandas`) jest dyspozycją człowieka w ramach danego zadania.

### 2. PyQGIS (Wtyczka QGIS)
* **Wielowątkowość:** Żadne operacje I/O (zapytania sieciowe, ciężkie obliczenia na geometrii) **nie mogą** być wykonywane synchronicznie w głównym wątku GUI. Obowiązkowo używamy wzorca `QgsTask` (`AsyncApiTask`).
* **Interfejs UI:** Wszystkie zmiany wizualne wykonujemy w Qt Designerze w pliku `dockwidget.ui`. Kod Pythona ładuje widok dynamicznie przez `uic.loadUiType` – nie kompilujemy ręcznie do `_ui.py`.
* **Czyste logowanie:** Zamiast `print()` w konsoli systemowej, komunikaty dla użytkownika kierujemy do okna logów panelu lub paska informacyjnego `iface.messageBar()`.

### 3. Frontend Web (`web/`)
* Czysty, lekki kod (HTML5, CSS, vanilla JS) zintegrowany z MapLibre GL JS.
* Nie wprowadzamy ciężkich frameworków (Next.js, Vue, Angular) bez wyraźnej decyzji człowieka.

---

## 🔒 Bezpieczeństwo i Higiena Danych
1. **Nigdy nie commituj kluczy API, haseł ani tokenów!** Wszelkie wrażliwe dane trzymamy w plikach `.env` (plik ten jest ignorowany przez `.gitignore`).
2. **Żadnych danych biznesowych ani pre-codingu:** Repozytorium przed startem oficjalnego wydarzenia musi zachować status uniwersalnej biblioteki narzędziowej.
