# Scenariusz demo

Gospodarstwo pod Krapkowicami (Opolskie), **27 maja 2024**, scenariusz `demo_2024`
(`scenarios/definitions/demo_2024.json`).

- 8 prawdziwych działek wyciętych z mapy upraw 2024: 4 × pszenica (Pod Lasem, Za Stodołą, Długie, Przy Drodze)
  i 4 × kukurydza (Nad Stawem, Klin, Górka, Za Torami). Tylko te dwie uprawy, bo asystent ma metodyki i nazwy
  upraw tylko dla nich (`assistant/domain.py: CROP_PL`).
- Prawdziwa pogoda 2022–2024 (bez `weather_overrides`), historia upraw 2020–2024 z rastrów, gleba z ISRIC.
- Bez zgłoszeń rolnika: dodajemy je na żywo w czacie.
- Stan na 27.05: pszenica kwitnie (BBCH 65–70). 2 pola wysokie, 2 średnie, 4 niskie. Prognoza na +3 dni:
  wszystkie 8 pól średnie.

## Przygotowanie (raz, przed pokazem)

```bash
docker compose up -d
python manage.py migrate
python manage.py rag_ingest                                    # indeks metodyk, ok. 2 min
python manage.py scenario switch demo_2024 --strict-data --reset-chat   # ok. 2 min: pogoda, dwa sezony ryzyk i cache dat (strzałki 0,3 s)
cd frontend && npm install && npm run build && cd ..
python manage.py runserver                                     # z kluczami LLM, patrz niżej
```

Klucze LLM (`GEMINI_API_KEY`, `GROQ_API_KEY`, `GEMINI_MODEL`, `LLM_PROVIDERS`) muszą trafić do zmiennych
środowiska serwera: wpisz je do `.env` w repo albo, jeśli leżą w `../.env`, uruchom serwer tak:
`set -a; . ../.env; set +a; python manage.py runserver`. Sprawdzenie: `python manage.py llm_models`.

**Reset między próbami** (kasuje zgłoszenia i rozmowy, pogody nie ładuje od nowa, ok. 2 min):

```bash
python manage.py scenario switch demo_2024 --strict-data --keep-weather --reset-chat
```

Potem odśwież stronę (Ctrl+Shift+R). Identyfikatory pól zmieniają się przy każdym przełączeniu: odwołuj się do pól
po nazwie (otwarta karta sama zaczyna nową rozmowę, gdy stara zniknęła).

Bez kluczy LLM wszystko poza czatem działa: czat jest wyszarzony z komunikatem „Asystent jest wyłączony”, a nagłówek
mówi „Połączono · asystent wyłączony”. Kroki 4–6 wymagają kluczy.

## Przebieg (ok. 5 minut)

### 1. Mapa: „co się dzieje na moich polach dziś”

- Otwórz <http://localhost:8000>. Nagłówek: „Połączono”, data **27 maja 2024**.
- Kafelki: **2 wysokie, 2 średnie, 4 niskie**. Lista pól posortowana od najgroźniejszego.
- Pokaż, że kolor zawsze idzie z ikoną i podpisem: na liście i na mapie (etykieta „▲ Pod Lasem · wysokie”, pola
  o wysokim ryzyku mają przerywany obrys i etykietę także po oddaleniu). Filtry kategorii (grzyby / szkodniki /
  wirusy) zawężają listę.

### 2. Panel pola: „dlaczego”

- Kliknij **Pod Lasem** (czerwone): wysoka septorioza plew i fuzarioza kłosów.
- Najpierw **co zrobić** (lustracja teraz, okno zabiegu z prognozy), potem streszczenie i **czynniki z wpływem**
  (godziny z mokrymi liśćmi, faza BBCH: kwitnienie, presja z poprzedniego sezonu, przedplon), faza i pewność.
- Wykres sezonu: linia ciągła do dziś, przerywana prognoza, pasma poziomów.
- To jest wytłumaczalność: każda liczba ma swoje źródło w pogodzie, fazie rozwoju i historii pola.

### 3. Prognoza: pasek dni na dole

- Kliknij **cz 30**: mapa i panel pokazują dzień +3. Wszystkie pszenice średnie, pojawia się brunatna plamistość
  liści, a pewność jest niższa (prognoza ma tylko wartości dobowe). Data demo się nie zmienia.
- Wróć na **dziś**.

### 4. Asystent: pytanie o pole

Przy zaznaczonym Pod Lasem (czat pokazuje „Pytasz o: Pod Lasem”) wpisz albo kliknij gotowe pytanie pod pustym czatem:

> Dlaczego to pole jest na czerwono i co mam zrobić?

Odpowiedź składa się z powodów z silnika, opisu objawów z metodyki (cytaty: metodyka pszenicy, poradnik zbożowy,
arkusz ryzyk) i zalecenia „lustracja teraz, zabieg po przekroczeniu progu, okno pogodowe 29.05”. Pod odpowiedzią
są źródła: strony metodyk i ryzyka z silnika.

### 5. Zgłoszenie objawów: mapa się zmienia (punkt kulminacyjny)

Zaznacz **Długie** (żółte, średnie):

> Na polu Długie widzę dziś na liściach podłużne brunatne plamy z czarnymi kropkami, chyba septorioza paskowana liści. Sporo tego.

Asystent pokazuje szkic obserwacji i opis objawów z metodyki do porównania. Odpowiedz **tak**.

- Odpowiedź: „septorioza paskowana liści pszenicy: niskie → wysokie. Przeliczył też sąsiednie pola tej samej
  uprawy: Pod Lasem.”
- **Długie zmienia kolor z żółtego na czerwony** (mapa sama przeładowuje te pola, z krótkim pulsem). W panelu
  pojawia się czynnik „Rolnik zgłosił na tym polu…”.

Używaj nazwy „septorioza **paskowana liści**”: samo „septorioza” asystent bywa skłonny przypisać do septoriozy plew.

### 6. Zgłoszenie oprysku: ryzyko spada

Zaznacz **Pod Lasem**:

> Wczoraj opryskałem Pod Lasem fungicydem na choroby kłosa.

Szkic („wykonany zabieg”, data 26.05), odpowiedz **tak**. Choroby grzybowe spadają do niskich, a **Pod Lasem
zmienia kolor z czerwonego na żółty** (zostają mszyce, na które fungicyd nie działa). W panelu widać czynnik
„Zabieg przeciw: choroby grzybowe (wszystkie) (26.05.2024)” z wartością, o ile obniża wynik.

### 7. (opcjonalnie) Zmiana daty

Strzałka **›** w nagłówku przesuwa datę demo o dzień: silnik kopiuje gotowe wyniki dla nowej daty (ok. 0,3 s,
z cache budowanego przy przełączeniu scenariusza; pola zmienione zgłoszeniem w kroku 5–6 liczy od nowa, ok. 1 s), a mapa wraca
na „dziś”. Wpisaną datę zapisuje Enter albo wyjście z pola; data spoza okna z pogodą (1.09.2022–31.12.2024) nie
przejdzie, a skok o ponad miesiąc wymaga potwierdzenia. Najlepiej po pokazie, bo zmienia stan pokazany wyżej.

## Co powiedzieć o danych

- Pogoda: dane organizatorów (dobowe i godzinowe, opad satelitarny IMERG). Prognozy w danych nie ma: scenariusz
  zapisuje jako „prognozę wydaną dnia D” pogodę z dni D+1…D+7 (wartości dobowe), więc dni przyszłe mają obniżoną
  pewność (−6 % na dzień).
- Pola: prawdziwe kształty z mapy upraw 2024; uprawa z mapy 2024, przedplony z map 2020–2023.
- Silnik: reguły z metodyk IOR i arkusza ryzyk, fazy rozwoju z sum temperatur (kalibracja DWD), progi
  0,33 / 0,66. Wynik to wskaźnik sprzyjających warunków, a nie prawdopodobieństwo.

## Znane drobiazgi

- Po zgłoszeniu oprysku asystent wymienia tylko część zmian (np. rdze), choć najmocniej spadają septorioza plew
  i fuzarioza.
- Szkodniki kukurydzy pod koniec maja są niskie: kukurydza dopiero wschodzi. To prawdziwy stan, nie błąd.
- Scenariusz liczy dni do 31.12.2024, więc datę można przesuwać przez cały sezon kukurydzy. Po 1 września
  kukurydza zostaje na polu do zbioru (silnik v0.13), a pszenica nowego sezonu zaczyna od siewu 1 października.
