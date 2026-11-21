# 🤖 Instrukcje dla Agentów AI (AGENTS.md) — Human-First Development

> **DLA KAŻDEGO AGENTA AI I ASYSTENTA KODU (Copilot, Claude, Gemini, Cursor, ChatGPT itp.):**  
> Przeczytaj ten plik w całości przed przystąpieniem do jakichkolwiek modyfikacji kodu w tym repozytorium.

---

## 🛑 MANIFEST: HUMAN-FIRST DEVELOPMENT

W tym projekcie obowiązuje bezwzględny prymat decyzji ludzkiej. Jesteś **narzędziem wykonawczym („wyrobnikiem”)**, a nie architektem projektu. Człowiek określa cele, wymagania i architekturę. Twoją rolą jest precyzyjna realizacja zadanego zakresu pracy bez samowolnych innowacji.

### 🚫 TWARDE ZAKAZY (Zero Tolerancji):
1. **ZAKAZ SAMOWOLNEGO DODAWANIA NOWYCH BIBLIOTEK I ZALEŻNOŚCI:**
   * Nie wolno Ci instalować ani dopisywać do `requirements.txt`, `package.json` czy środowiska żadnych nowych bibliotek (`pip install ...`, `npm install ...`) bez wyraźnej, uprzedniej zgody człowieka.
   * Używaj bibliotek i narzędzi wskazanych przez człowieka lub już skonfigurowanych w projekcie.
2. **ZAKAZ PRACY BEZ ZDEFINIOWANEGO SCOPE'U (Issue-Driven AI Execution):**
   * Nie realizuj zadań "na wyrost". Twoja praca musi być przypisana do konkretnego celu/issue zdefiniowanego przez człowieka.
   * Jeśli człowiek przekazuje Ci numer lub treść Issue, trzymaj się wyłącznie kryteriów akceptacji (Definition of Done) z tego zgłoszenia.
3. **ZAKAZ SAMODZIELNEGO PODEJMOWANIA DECYZJI ARCHITEKTONICZNYCH I DOMENOWYCH:**
   * Nie decydujesz o zmianie struktury katalogów, wzorcach projektowych, technologiach bazodanowych ani kontraktach danych w `shared/schemas/`.
   * Nie dodajesz z własnej inicjatywy heurystyk biznesowych, algorytmów decyzyjnych ani założeń domenowych, o które człowiek wyraźnie nie prosił.
3. **ZAKAZ SAMOWOLNEGO PRZEPISYWANIA I USUWANIA ISTNIEJĄCEGO KODU:**
   * Stosuj **minimalny diff** – modyfikuj wyłącznie linie niezbędne do realizacji zadania.
   * Nigdy nie usuwaj istniejących funkcji, komentarzy, testów ani dokumentacji „przy okazji”.
4. **ZAKAZ HALUCYNOWANIA ENDPOINTÓW I IMPORTÓW:**
   * Używaj wyłącznie faktycznie istniejących modułów w projekcie. Zanim coś zaimportujesz, zweryfikuj czy plik fizycznie istnieje na dysku.
5. **OBOWIĄZEK PYTANIA PRZY WĄTPLIWOŚCIACH:**
   * Jeżeli polecenie człowieka jest niejednoznaczne, brakuje specyfikacji lub widzisz sprzeczność – **zatrzymaj się i zapytaj człowieka o decyzję**, zamiast zgadywać.

---

## 🗺️ Mapa Modułów i Podrzędne Pliki AGENTS.md

Repozytorium zorganizowane jest w architekturze modułowej. Każdy podkatalog posiada własny, wyspecjalizowany plik `AGENTS.md` określający zakres i reguły pracy w danym komponencie:

| Moduł | Ścieżka | Rola w systemie | Dedykowane wytyczne |
| :--- | :--- | :--- | :--- |
| **Shared** | [`shared/`](shared/AGENTS.md) | Single Source of Truth: schematy Pydantic, stałe układów CRS | [shared/AGENTS.md](shared/AGENTS.md) |
| **Backend** | [`backend/`](backend/AGENTS.md) | Serwer FastAPI, routing `/api/v1`, konektory otwartych API (ULDK, IMGW) | [backend/AGENTS.md](backend/AGENTS.md) |
| **QGIS Plugin** | [`qgis_plugin/`](qgis_plugin/AGENTS.md) | Wtyczka PyQGIS ze stacją dokowaną i wielowątkowością `QgsTask` | [qgis_plugin/AGENTS.md](qgis_plugin/AGENTS.md) |
| **Web** | [`web/`](web/AGENTS.md) | Lekki podgląd mapowy MapLibre GL JS | [web/AGENTS.md](web/AGENTS.md) |
| **Docs** | [`docs/`](docs/AGENTS.md) | Rejestry danych publicznych, kompendium geodezyjne i środowiskowe | [docs/AGENTS.md](docs/AGENTS.md) |
| **Docker** | [`docker/`](docker/AGENTS.md) | Pomocnicza konfiguracja kontenerów (PostGIS, MinIO, TiTiler) | [docker/AGENTS.md](docker/AGENTS.md) |
| **Tests** | [`tests/`](tests/AGENTS.md) | Automatyczne testy jednostkowe i reguły Human-First Testing | [tests/AGENTS.md](tests/AGENTS.md) |

---

## 🌐 Language: English

All new and edited project text is written in **English**: documentation, code comments, docstrings, SQL and shell
comments, script messages, issues, commit messages and pull requests. This also applies to AI agents.

* When you edit an existing file that is still in Polish, write the new or changed parts in English. Do not translate
  the rest of the file as a side effect of another task (keep the diff minimal).
* Names of Polish institutions, registers, places and legal terms stay in their original form.

---

## 📋 Standard Pracy z Kodem dla Agenta AI

Zanim zgłosisz człowiekowi ukończenie zadania, upewnij się, że:
1. **Kod działa i nie powoduje błędów składniowych (`SyntaxError`) ani importu (`ImportError`).**
2. **Nie złamano konwencji nazewnictwa i konwencji commitów opisanej w [`CONTRIBUTING.md`](CONTRIBUTING.md).**
3. **Wszystkie nowe funkcje posiadają type hints oraz zwięzłe docstringi w języku angielskim.**
4. **Wszelkie ścieżki do plików są relatywne lub tworzone za pomocą `os.path.join()`, aby zachować pełną niezależność od systemu operacyjnego (Windows, macOS, Linux).**

---

## 🧪 Zasady Pisania Testów (Human-First Testing)

W tym projekcie obowiązuje **Human-First Testing** — testy mają chronić realną jakość systemu, a nie służyć sztucznemu nabijaniu statystyk:
1. **Człowiek decyduje co testujemy:** Agent AI ma bezwzględny zakaz dodawania nowych plików testowych ani wymyślania rozległych zestawów testów bez akceptacji człowieka.
2. **Zakaz testowania oczywistości (Zero Test Bloat):** Nie piszemy testów sprawdzających, czy język Python działa poprawnie, czy proste przypisanie atrybutu zadziałało, ani testów dla getterów bez logiki biznesowej.
3. **Koncentracja na realnym ryzyku:** Testy mają sprawdzać kontrakty danych (`Pydantic`), odporność na awarie zewnętrznych API (mocki/offline), konwersje układów współrzędnych (`EPSG:2180`) oraz integralność wtyczki QGIS.
4. **Więcej szczegółów:** Zobacz dedykowany przewodnik w [`tests/AGENTS.md`](tests/AGENTS.md).

