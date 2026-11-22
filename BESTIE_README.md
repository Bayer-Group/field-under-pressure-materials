# farmIT — Instrukcja uruchomienia i pełnego korzystania z aplikacji (dla Jury)

Aplikacja **farmIT** to webowy dashboard w **Streamlit** wspierający decyzje agrotechniczne, monitorowanie pól i presji chorób, kalkulację kosztów i zysków (z odniesieniem do nasion Bayer / DEKALB oraz trybu EKO), a także automatyczne generowanie dokumentacji audytowej dla rolnictwa ekologicznego.

> **Informacja o wydarzeniu:** hackathon *Field Under Pressure* (`20–22 Nov 2026`, Uniwersytet Warszawski, Wydział Geologii). Poniższa instrukcja opisuje uruchomienie i pełny test naszej aplikacji na gałęzi `team/bestie`.

---

## 1. Szybkie uruchomienie aplikacji (krok po kroku)

### Krok 1. Przełączenie na gałąź zespołu i aktywacja środowiska
W głównym katalogu repozytorium:

```bash
git checkout team/bestie
python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Linux / macOS:
source .venv/bin/activate
```

### Krok 2. Instalacja zależności
```bash
pip install -r requirements.txt
```

### Krok 3. (Opcjonalnie) Konfiguracja asystenta AI **Farmhand**
Asystent **Farmhand** działa od razu także **bez klucza API** (w trybie lokalnym na podstawie aktualnych danych z aplikacji). Aby włączyć pełne odpowiedzi modelu LLM, utwórz lokalnie plik `.streamlit/secrets.toml` (nie commituj go do repozytorium) i wpisz jeden z kluczy:

```toml
GEMINI_API_KEY = "twoj_klucz_gemini"
# lub alternatywnie:
OPENAI_API_KEY = "twoj_klucz_openai"
```

### Krok 4. Start aplikacji Streamlit
```bash
streamlit run app/main.py
```

Po uruchomieniu aplikacja otworzy się w przeglądarce (domyślnie pod adresem `http://localhost:8501`).

---

## 2. Jak przetestować wszystkie funkcje aplikacji (ścieżka dla Jury)

### A. Wybór gminy i załadowanie danych LIVE (ekran startowy)
1. Na ekranie startowym wpisz nazwę gospodarstwa (lub zostaw domyślną).
2. Wybierz **Województwo**, **Powiat** oraz **Gminę** (na podstawie bazy GADM 4.1 w `app/data_app/gminy_polska.parquet`).
3. Kliknij **„Załaduj kafel pól i pogodę LIVE dla gminy …”**.
   * System buduje kafel działek (CLMS Crop Types / ESA WorldCover / OSM Overpass), wylicza metryczne powierzchnie w układzie **EPSG:2180**, pobiera parametry glebowe z **ISRIC SoilGrids**, odpytuje **Sentinel-2 L2A** (filtrując sceny `<20%` zachmurzenia i maskę `SCL`) oraz pobiera godzinową pogodę i prognozę z **Open-Meteo**, zapisując wyniki w lokalnym cache (`app/data_app/`).

### B. Zakładka „Moje Gospodarstwo” — konfiguracja działek i statusu EKO
1. Rozwiń sekcję konfiguracji/podglądu działek w wybranej gminie.
2. Zaznacz wybrane działki (bezpośrednio w tabeli **„Moje pole”** lub klikając poligony na mapie).
3. Dla wybranych działek oznacz **„Działka EKO”** oraz ustaw **„Deklarowana uprawa”** (możesz też wybrać **„Brak uprawy / Pod zasiew”**, aby zobaczyć rekomendację gatunku na podstawie pH, próchnicy/SOC i tekstury gleby).
4. Kliknij **„Zapisz profil gospodarstwa”** (lub **„Wyczyść wybór”**, aby zresetować zaznaczenia).

### C. Zakładka „Pola i pogoda” — decyzje zabiegowe, mapa i monitoring
1. Użyj suwaka godziny, aby sprawdzić rekomendacje deterministycznego silnika reguł (`PRYSKAJ TERAZ`, `NAWOŹ`, `ZASIEJ`, `ZBIERAJ`, `MONITORUJ`, `CZEKAJ`).
2. Przełącz **„Tryb rolnictwa EKO”** oraz **„Tylko moje pola”**.
3. Najedź kursorem na poligony na mapie **PyDeck**, aby zobaczyć szczegóły działki, zalecenie, nawozy/środki EKO, parametry gleby i pogodę.
4. Przejrzyj wykresy (siła wiatru względem progu `4,0 m/s` oraz temperatura LIVE + prognoza + linia trendu), dodaj wpis w **Notatniku pogodowym** i sprawdź sekcję **„Monitoring presji chorób i przebieg od daty zasiania”** (z filtrem zachmurzenia Sentinel `< 20%` i przełącznikami wskaźników).

### D. Zakładka „Kalkulator nawozów i oprysków · Kalkulator zysków”
1. Wybierz konkretne pole z listy — parametry powierzchni, uprawy, dawki oraz trybu EKO automatycznie dopasują się do wybranej działki.
2. Sprawdź przeliczenie ilości nawozu/środka oraz wody do opryskiwacza.
3. Niżej w **Kalkulatorze zysków i ryzyka pola (Bayer / DEKALB)** przetestuj suwak korekty `% straty plonu`, rozwiń edytowalny cennik i przeanalizuj koszty (ziarno, nawozy, pestycydy), przychód po stracie oraz zysk netto.

### E. Zakładka „Dokumentacja EKO i Audyt” oraz „Zasady zabiegów”
1. W **„Dokumentacja EKO i Audyt”** wybierz działki ekologiczne, uzupełnij dane gospodarstwa/doradcy (opcjonalnie własne zabiegi i maszyny) i kliknij **„Pobierz wypełnioną Dokumentację Rolnika Ekologicznego (.xlsx)”** — wygeneruje się 5-arkuszowy plik Excel zgodny ze wzorem audytowym ARiMR/IJHARS (`Wzor_Dokumentacji_Rolnika_Ekologicznego_Audyt-v4.xlsx`).
2. W **„Zasady zabiegów”** przejrzyj tabelę 52 reguł agronomicznych i przetestuj formularz **„➕ Dodaj własną regułę zabiegową”**.

### F. Asystent polowy **Farmhand** (pływający przycisk `🌾 Farmhand` w prawym dolnym rogu)
* Kliknij przycisk **„🌾 Farmhand”** w prawym dolnym rogu (dostępny w każdym widoku), użyj szybkiego pytania lub wpisz własne pytanie dotyczące bieżących pól, pogody i zabiegów.

---

## 3. Rozwiązywanie typowych problemów podczas testów
* **Brak połączenia z zewnętrznym API / wolniejszy internet:** aplikacja korzysta z lokalnego cache w `app/data_app/` oraz posiada wbudowane mechanizmy awaryjne (m.in. fallback w potoku danych oraz tryb lokalny w asystencie **Farmhand**).
* **Błąd brakującego pakietu przy czystym środowisku:** upewnij się, że instalacja została wykonana po aktywacji `.venv` poleceniem `pip install -r requirements.txt`.

---

## 4. Struktura kluczowych plików projektu

| Ścieżka | Opis |
| :--- | :--- |
| `app/main.py` | Główny interfejs aplikacji Streamlit (onboarding, mapa PyDeck, wykresy, kalkulatory, zakładki). |
| `app/silnik_regul.py` | Deterministyczny silnik reguł agronomicznych, rekomendacje siewu/nawożenia (w tym EKO) oraz prognoza zysków (Bayer/DEKALB). |
| `app/eko_dokumentacja.py` | Generator wypełnionej dokumentacji rolnika ekologicznego (`.xlsx`) do audytu ARiMR / IJHARS. |
| `app/farmhand.py` | Kontekstowy asystent polowy AI (Gemini / OpenAI + deterministyczny tryb offline). |
| `app/data_app/` | Słownik gmin Polski (`gminy_polska.parquet`), reguły agronomiczne (`reguly_agronomiczne.csv`), szablon audytu EKO oraz cache kafli. |
| `src_geo/pobierz_gmine.py` | Potok pobierania i łączenia danych geoprzestrzennych (poligony pól, Sentinel-2 L2A, SoilGrids, Open-Meteo). |