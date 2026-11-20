# 🤖 Instrukcje dla Agentów AI w Module Testów (`tests/`)

> **DLA KAŻDEGO AGENTA AI I ASYSTENTA KODU:**  
> Przeczytaj ten plik przed tworzeniem, modyfikowaniem lub sugerowaniem jakichkolwiek testów w tym repozytorium.

---

## 🛑 ZASADY PISANIA TESTÓW (HUMAN-FIRST TESTING)

W tym projekcie obowiązuje **bezwzględna zasada Human-First Testing**. Człowiek decyduje o architekturze testów, celach weryfikacji i akceptowalnych kryteriach sukcesu. Agent AI jest wyłącznie wykonawcą poleceń i nie ma prawa do samowolnego rozbudowywania zestawu testów.

### 🚫 CZEGO AGENTOWI AI NIE WOLNO (Zero Tolerancji):
1. **ZAKAZ TESTOWANIA RZECZY TRYWIALNYCH I OCZYWISTYCH (Test Bloat):**
   * Nie pisz testów sprawdzających, czy język Python działa poprawnie (np. czy `1 + 1 == 2`, czy `list.append()` dodaje element, czy wbudowany słownik przechowuje klucze).
   * Nie pisz testów dla prostych getterów/setterów, pustych konstruktorów ani trywialnych przypisań atrybutów, chyba że zawierają jawną logikę walidacyjną.
   * Nie generuj sztucznych testów tylko po to, aby "zwiększyć pokrycie kodu" (code coverage padding).
2. **ZAKAZ SAMOWOLNEGO TWORZENIA NOWYCH PLIKÓW TESTOWYCH:**
   * Agent AI **nie tworzy nowych plików testowych** bez wyraźnego polecenia człowieka definiującego cel i zakres testu.
   * Jeśli zauważysz brakujący scenariusz, zapytaj człowieka: *"Czy chcesz, abym dodał test weryfikujący przypadek X?"*.
3. **ZAKAZ TESTOWANIA BEZPOŚREDNICH ZALEŻNOŚCI ZEWNĘTRZNYCH (Zero Live Network w testach):**
   * Żaden test jednostkowy nie może wykonywać rzeczywistych zapytań HTTP do zewnętrznych serwerów (ULDK, IMGW, Open-Meteo itp.).
   * Wszelkie testy integracji z usługami zewnętrznymi muszą używać mocków (`unittest.mock`), atrap lub trybu offline (`test_ingestion_offline.py`).
4. **ZAKAZ TWORZENIA TESTÓW FLAKY (Niestabilnych):**
   * Zakaz używania `time.sleep()`, losowych wartości bez ziarna (`random.seed`) czy testów zależnych od strefy czasowej lub lokalizacji użytkownika.

---

## 🎯 CO AGENT AI MA TESTOWAĆ (Na Polecenie Człowieka):

1. **Kontrakty Danych i Schematy Pydantic (`test_schemas.py`):**
   * Czy nieprawidłowe współrzędne geograficzne lub błędne typy danych są poprawnie odrzucane przez walidację (`ValidationError`).
   * Czy serializacja i deserializacja do formatu GeoJSON przebiega zgodnie ze specyfikacją RFC 7946.
2. **Transformacje Współrzędnych i Obliczenia Metryczne (`test_crs_and_geometry.py`):**
   * Czy przeliczniki pomiędzy układami EPSG:2180 a EPSG:4326/EPSG:3857 zwracają wartości w oczekiwanych tolerancjach.
   * Czy funkcja obliczania powierzchni w $m^2$ oraz hektarach poprawnie obsługuje wielokąty i zgłasza błąd przy zdegenerowanej geometrii.
3. **Obsługa Błędów i Odporność (Error Handling & Fallback):**
   * Jak kod zachowuje się przy pustej odpowiedzi z API, kodzie HTTP 500, przekroczeniu czasu oczekiwania (timeout) lub uszkodzonym formacie JSON/WKT.
4. **Struktura Wtyczki QGIS i Izolacja Środowiskowa (`test_qgis_plugin.py`):**
   * Czy wtyczka posiada poprawny plik `metadata.txt`, zgodną strukturę importów i nie wywołuje wyjątków przy braku środowiska GUI QGIS.

---

## 🛠️ STANDARDY TECHNICZNE TESTÓW

* **Framework:** Standardowy moduł biblioteki standardowej `unittest`.
* **Zero nowych zależności:** Testy muszą być uruchamialne w czystym środowisku Pythona bez konieczności instalowania dodatkowych pakietów (np. `pytest`, chyba że człowiek o to wyraźnie poprosi).
* **Izolacja ścieżek:** Każdy plik testowy musi dynamicznie ustawiać ścieżkę do projektu za pomocą `sys.path.insert(0, ...)`.
* **Warunkowe pomijanie:** W przypadku modułów opcjonalnych (np. `fastapi`), testy muszą używać `@unittest.skipIf(not MODUL_DOSTEPNY, "powód pominięcia")`, aby zestaw testów przechodził w każdym środowisku.
