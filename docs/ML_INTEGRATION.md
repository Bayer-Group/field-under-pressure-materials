# Analityka i predykcje S.A.G.E.

Jedno API obsługuje pogodę, układ sadów, analitykę, eksporty Earth Engine i prognozę. Polecenia `python -m backend.main migrate|backfill|run` zachowują harmonogram pogody. Analityka używa sadu wybranego w górnym pasku. Zakładka Warstwy i skany pozostaje pusta. Wszystkie narzędzia analityczne są dostępne w Analityce, w tym rozwijany panel zadań Earth Engine i prognoz.

## Konfiguracja

Ustaw `EARTHENGINE_PROJECT` albo lokalny, ignorowany przez Git plik `earthengine.json` z polem `project_id`. Uwierzytelnij konto Google mające dostęp do Earth Engine i Dysku Google. Do eksportu wymagane są włączone API Earth Engine oraz odpowiednie uprawnienia projektu. Błąd `USER_PROJECT_DENIED` wymaga sprawdzenia roli `roles/serviceusage.serviceUsageConsumer` dla zalogowanego konta. Właściciel projektu nadaje ją w Google Cloud IAM.

```powershell
python -m pip install -r backend/requirements.txt
earthengine authenticate
python db/scripts/start_weather.py --with-ui
```

Dashboard i odczyt zapisanych analiz działają przy niedostępności Google. Próba nowego zadania zwraca wtedy 503 z opisem błędu. Po uzupełnieniu logowania lub uprawnień uruchom backend ponownie.

## Dane i eksport

- Podstawą są rzeczywiste `Orchard.geometry`, `Orchard.centroid` i `Tree.coordinates`. Listę drzew ogranicza aktywny układ z `layoutTreeIds`. Aktualny zrzut początkowy to `field_under_pressure_20261121_230119.archive.gz`. Import przykładowych danych jest wyłączony w runtime.
- `POST /api/analytics/orchards/{orchardId}/jobs` zgłasza eksporty w tle i zwraca identyfikator. `GET .../jobs/latest` zwraca stan oraz błędy i gotowość poszczególnych warstw. MongoDB przypisuje jedno aktywne zadanie do sadu, a osobny wątek odnawia dzierżawę. Po przerwanym przebiegu wygasłe zadanie można ponowić.
- Wyniki częściowe są widoczne w postępie zadania. Publikacja `Orchard.analysis` następuje po zapisie próbek drzew. `run_id` i skrót geometrii oraz aktywnych współrzędnych łączą całość. Zmiana układu unieważnia odczyt starej analizy. Ponowiona analiza nie publikuje wyniku przebiegu zastąpionego nowszym zadaniem.
- Zweryfikowane rastry zapisują się w GridFS `AnalysisRaster.files/chunks`. Mapy oraz prognoza na zapisanej siatce odczytują je z MongoDB. Eksport na Google Drive jest źródłem pierwszego pobrania i obsługuje starsze wyniki. Zrzut bazy przenosi również warstwy mapy. Logowanie Google jest potrzebne do nowej analizy.
- Wilgotność powstaje z modelu Random Forest nad Sentinel-1 i ERA5-Land. Prognoza Ridge wykorzystuje historię temperatury, opadu, ET₀ i wilgotności gleby. NDVI, pH, tekstura, nasłonecznienie, prognozy dzienne i prognoza do kolejnego szacowanego przelotu pozostają dostępne. Własny GeoTIFF można otworzyć na mapie w Analityce.
- Dane pogodowe do ML są buforowane w `MLWeatherCache`, z kluczem obejmującym źródło, punkt, zmienne i zakres dat. Prognoza ma ważność godziny, archiwum siedmiu dni. Indeks TTL usuwa wygasły cache.
- Starsze endpointy `/api/soil-moisture` wymagają teraz `orchardId` w JSON, a `/api/soil-moisture/forecast` parametru zapytania `orchardId`. Działają dla sadu wybranego w aplikacji.

## Kondycja i kolory

`Tree.healthIndex` reprezentuje ocenę zapisaną przez użytkownika i ma pierwszeństwo. Dla drzew bez takiej oceny aplikacja może wyświetlić szacunek `current-stress-v1` oparty na bieżących sygnałach stresu i profilu gatunku. Prognozowane ryzyko jest odrębnym wynikiem. Reguła szacunku jest punktem startowym do kalibracji i wymaga porównania z obserwacjami terenowymi.

Szacunek wymaga opublikowanego przebiegu zgodnego z aktualnym układem, sceny sprzed najwyżej 14 dni, zgodnego GPS i co najmniej 55% pokrycia wag dostępnych sygnałów. Wymagany jest też ważny odczyt NDVI albo wilgotności. Brak danych daje `null` i kolor szary. Modelowy wynik w dolnym przedziale ma status `poor`. Status `dead` pochodzi z zapisanej oceny terenowej.

Wspólny serwis `backend/tree_health.py` zasila `healthScore`, `healthStatus`, `healthSource`, `healthAssessedAt` i `healthCoverage` w scenie 3D i Analityce. Paleta kondycji pochodzi z `HEALTH_PALETTE`. Mapa analityczna pozwala przełączyć kondycję i ryzyko. Karta sadu podaje średnią znanych ocen, rozkład i liczbę ocenionych drzew. Wiele drzew może dzielić piksel satelitarny. Rozdzielczość i wiek danych ograniczają niezależność ich szacunków.

## Testy regresji

```powershell
python -m pip install pytest httpx
$env:SAGE_TEST_MONGO_BIN = "C:\sciezka\do\mongod.exe"
python -m pytest tests/test_ml_integration.py -q
cd ui
npm ci
npm run typecheck
npm run build
```

Sześć testów uruchamia odizolowany MongoDB i odtwarza zrzuty zespołu. Sprawdzają wspólne trasy, brak konfiguracji Google, GPS, rastry testowe, zgodność ocen 2D i 3D, aktualność analizy po zmianie układu, współbieżne zgłaszanie zadań i walidację czasową Ridge. Osobny test odtwarza rzeczywisty checkpoint i porównuje próbki 12 drzew z czterema rastrami odczytanymi przez API bez Google. Test setupu wykonuje backup.sh, restore.sh i init-restore.sh w odizolowanej bazie. Sprawdza usunięcie kolekcji spoza zrzutu oraz zachowanie dokumentów, rastrów, indeksów i walidatorów. Rastry testowe pozostają w tymczasowych katalogach.

Checkpoint `230119` zawiera rzeczywisty przebieg dla Grojec A (`6b01933c1dc02a368703a020`). Cztery eksporty zakończyły się poprawnie. Próbki wszystkich 12 drzew porównano z pikselami GeoTIFF po przeliczeniu ich własnego GPS. Scena Sentinel-1 pochodzi z 21.11.2026, 16:26:50 UTC. Pozostałe sady nie otrzymały zastępczych wyników. Ridge zwrócił prognozę na trzy doby. Wyniki i rastry są częścią zrzutu. Po 14 dniach szacunek kondycji wygasa, jeśli nie wykonano nowej analizy.

Przetestowano również start z pustego katalogu danych przez `start_weather.py --with-ui --check`. Odtworzono 624 dokumenty bez błędów, uruchomiono Vite i backend oraz odczytano wszystkie pięć zakresów wykresu temperatury. W przeglądarce sprawdzono Dashboard, Analitykę, prognozę na dzisiaj oraz pustą zakładkę Warstwy i skany. Rzeczywista prognoza do kolejnego szacowanego przelotu zwróciła HTTP 200 i tabelę wyników dla wybranego sadu.

Ponowny odbiór setupu obejmował nowe środowisko Python z instalacją `backend/requirements.txt`, czyste `npm ci`, typecheck i build UI oraz sześć testów integracyjnych. Docelową bazę odtworzono od zera w domyślnym `data/weather-mongodb`. Przez API frontendu sprawdzono pięć zakresów temperatur dla każdego z sześciu sadów, GPS wszystkich 12 drzew, zgodność ocen 2D i 3D oraz cztery rastry w MongoDB. Edytor odczytał dwa rzędy i 12 drzew. Poprzednie procesy bazy, strony i aktualizacji zostały zamknięte.

Środowisko bez Dockera umożliwia weryfikację lokalną. Kontenery nie zostały uruchomione w środowisku integracji, ponieważ nie ma Docker Engine. Test kontenerów wykonuje się na komputerze z Docker Engine.
