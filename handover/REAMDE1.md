# HANDOVER
BĘDZIE DUŻO DO POPRAWY I DUŻO KILKA NOWYCH FUNKCJONALNOŚCI - ZMIENI SIĘ CORE BO WEDŁUG MNIE NIE JEST DOBRZE

Działa już mapa pól w Lizmapie, kalendarz 7 dni dla 108 pól >= 3ha (tryb historyczny od 14.04.2025), popup z oceną dnia, podświetlenie pola.

## Obecnie Lizmapa wygląda tak
<img width="1905" height="910" alt="image" src="https://github.com/user-attachments/assets/ba361121-e481-4000-a131-4be5ecb1f50e" />
<img width="1912" height="910" alt="image" src="https://github.com/user-attachments/assets/a86c2319-5e09-4b99-9e20-ddb50711991e" />


Największe ryzyka to brak danych satelitarnych dla naszego obszaru - kagel 33UXR vs pola 34U...), domyślny profil gleby i nieużywane dane Bayera. Na prezentację pokazujemy jedno pole i jedną historię z wynikiem w pln-ach.


## AUDYT CO BYŁO ZŁE I CO Z TYM ROBIMY

Główny błąd koncepcji: ocena opiera się na jednej średniej dla całego pola, a temat hackathonu to MAPA RYZYKA!!!!!!!!. Pole 12ha ma miejsca mokre, piaszczyste i słabsze, a średnia to ukrywa.

Założenia koncepcji

Ocena per pole (średnia) - rolnik co może z tym zrobić? gówno w sumie - rozsiewacz potrzebuje mapy dawek - strefy 10m w polu i mapa dawek N

LSTM prognozujący NDVI/NDMI na 7 dni - wyszło na to że prognoza się chu8 zmienia z rzadkich i zachmurzonych obserwacji - jury może się zapytać o dokładność a nie ma czym jej wykazać; model nie ma wpływu na decyzje - IMO bym to wyrzucił i zamiast tego porównanie z normą upraw z lat wstecz czytaj 2020-2024

Te klasy nie wiem kto robił bonitacyjne I-VI z SoilGrids - jest 'wzór' na klase gdzie szpont komuś wkleił własne wagi. Lepiej przejść na inną nomenklaturę - do zastanowienia nwm ideks jakości gleby (szacunkowy) czy cos

Moduł nawadniania - w Polsce uprawy polowe prawie nie są nawadniane xd dobrze ze to sprawdziłem bo by nas wyśmiali - chat zaproponował że można przejść na "stres wodny" bez zaleceń

Brak ochrony roślinności - temat to CROP RISK i Bayer zarabia na ochronie roślinnośći - do rozważenia moduł presji chorób i okna oprysku

Brak danych Bayera - decydujemy się na dane tylko z meteo no tylko ze w skoro organiator je dał to imo nie możemy skorzystać z innych no bo po co by dawał

"Co gdzie zasiać" - pomysł bez danych któe by to uzasadniały - do wy@bania

## Kod:

1. satelite_img_downloader.ipynb - domyślnie raster 20m i jedna scena z najmniejszym zachmurzeniem ale NDBI da się wyliczyć w 10m bo jedna scena nie daje szeregu czasowego

1.1 DO ZMIANY 10m + kilka scen z sezonu

2. soil_bonification.py jw. zmienność gleby w polu znika

2.2 DO ZMIANY profil per strefa; nazwa indeksu

3. meteo.py - brak historycznego trybu


## Stan danych

Granice pól - na razie mam 1983 z okolic łowicza gdzie 108 przekracza te nasze 3ha, na bazie to jest scheamt public.fields; jeśli chcemy zmieniac region no to pobrać FTW dla nowego obszaru

Kalendarz nawożenia - 108 pól x 7 dni x 4 nawozy (teraz z open meteo docelowo od Niemca)

Gleba - profil domyślny (ten sam dla wszystkich pól) SoulGrids - wgra zipy do soil_data/ i uruchomić loader ponownie

Uprawy - brak na razie - crop_type jest pusty ten bk/assign_crops.py - uruchomić skrypt i zapisać uprawę do field_profile

Ryzyka chorób są w ryzyka_zebrane.xlsx


# Opis modułów które bym wdrożył są w drugim readme
