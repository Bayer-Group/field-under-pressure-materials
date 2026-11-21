# Pomysły

## Moduł 1: strefy w polu i mapa dawek azotu
Każde pole >= 3ha dzielimy na 3 strefy z NDVI 10m i dajemy każdej strefie własną dawkę N.
Wynik to będzie plik ro rozsiewacza i kwota oszczędności. To główna funkcja na prezentację.

### STEP BY STEP
1 Sceny Sentinel-2. Z sezonu np marzec-czerwiec 2024 bierzemy 8 scen z zachmurzeniem <20 %.
Chmury i cienie maskujemy pasmem SCL (o tym co mowilem na poczatku na tablicy rozpisywałem)
Klasy 3, 8 ,9. 10

2 NDVI w 10m liczymy to w natywnej rozdzielczości 10m bez przepróbkowywania do 20m

3 Przycięcie do pola z buforem 10metrow. Piksele na granicy mieszają się z miedzą i drogą więc je odrzucamy.

4 Dla każdej sceny normalizujemy NDVI w obrębie pola (wpiszcie do chata z-score to moze ogarnie)
potem bierzemy medianę ze scen. I wtedy strefa "słaba" to miejsce słąbsze ZAWSZE a nie w jednym dniu.

5 3 strefy kp-means i potem filtr większościowy 3x3 żeby usunąć pojedyncze piksele

6 Wektoryzacja - rasterio.features.shapes (Raster strefy na poligony) - scalacie kawalłki <0.3ha z sąsiednią
strefą. Poligony w 2180 i powierzchnie

7 Dawki. Rolnik podaje dawkę bazową (kg N/ha) i wybiera strategię wyrównawczą (więcej azotu dla słabej strefy)
albo pod potencjał (więcej dla mocnej). Domyślnie +-20% wokół dawki bazowej. Dawkę przeliczymy na kg wg
zawartości N w tych podanych nawozach i juz wyszukałem wartosci i będzie to:
Saletra - 34%, Mocznik - 46%, RSM 32%, Saletrosan 26%

8 Porównujemy sumę nawozu przy dawce jednolitej i zmiennej. Cena nawozu zł/t podaje użytkownik albo
z tej giełdy co mówiłem ona jest na zdjeciu ktore natalka zrobiła i przesłała na grupe

9 Ten kto to robi musi: postawić kontener postgisa czy tam lokalny klaster w/e stworzyć tabele field_zones
w publicu: field_id, zone, area_ha, ndvi_z, dose_kg_n_ha, dose_kg_product_ha, geom) potem dumpa pg_dump. Eksport shapefile z atrybutem dawki Sprawdziłem i większość terminali w John Deerach, Trimble, Topcony przyjmują shapefile ISOXML jako rozszerzenie jeśli zostanie czas.

10 Ja przychodze dostaje dane i robie lizmape warstw stref (czerwona, źółta, zielona) popup strefy z powierzchnią
i dawką, w popupie pola karta "Mapa dawek" z oszczędnością i przyciskiem do pobrania.

Może taka

<img width="605" height="356" alt="image" src="https://github.com/user-attachments/assets/9a545133-67b3-4057-bfa6-29b8be66a55d" />

## Moduł 2: presja chorób i okno oprysku
Na każdy dzień liczymy ryzyko infekcji dla głównych chorób uprawy i wskazujemy godziny, w któych można
bezpiecznie pryskać. To są reguły podane z arkusza co podesłali wiec bez ML a spoko dodatek bo da sie ocene wyjaśnić

### STEP BY STEP
1 Pogoda godzinowa - temperatura, wilgotność względna, punkt rosy, opad, watr
2 Godzina zwilżenia liści (przybliżenie) godzina będzie mokra gdy wilgotność >90% albo temperatura punktu rosy <2 stopnie albo pada
3 Reguły z arkusza ryzyka_zebrane.xlsx np dla pszenicy septorioza paskowania liści 4-18 stopni przy opadach i wysokiej wilgotnści ,rdza brunatna 15-18 stopni, fuzarioza kosów 15-25 przy wysokiej wilgotności, mączniak prawdziwy 5-30 stopni. Dla każdej choroby liczymy godziny mokre w jej zakresie temperatur w oknie 48h
4 Poziom ryzyka: niski, średni wysoki wg liczby takich godzin. Progi są demontracyjne i tak je opisujemy, podobnie jak progi opadów w koncepcji.
5 Okno oprysku: godziny bez opadu przez kolejne kilka godzin, z umiarkowanym wiatrem i temperaturą w zakresie stosowania. Konkretnie bierzemy progi z metodyk w katalogu
6 To samo - klaster bazy pg_dump i w publicu.field_disease (field_id, day, disease, risk, wet_hours, reason) i potem ja dodam nowy pasek w kalendarzu "ochrona"

## Moduł 3: Odtworzenie sezonu 2024 z walidacją
Przewijamy sezon 2024 dzień po dniu i pokazujemy że ostrzeżenia systemu poprzedzały realne zmiany na polu.
Jak sie spruje żyri czy to zadziała no to im pokazemy. Pogode z Bayera, dodamy NDVI i sporządzić trzeba wykresy: opad, choroba dla dni ostrzeżeń i krzywa NDVI. Jak przyjde to dodam w lizmapie suwak daty albo przełącznik tygodnia w popupie???

## Moduł 4: Powiadomienia telegramowe
telegram_alerts wysyła rolnikowi wiadomość z najlepszym terminem nawożenia, oceną 7 dni i linkiem do pola w Lizmapie. Dane weżmie z field_calender. Poczytajcie o @BotFather w tym telegramie /newbot skopiować token i napisać cokolwiek potem na scenie wysyłamy wiadomosć na żywo i pokazujemy telefon. Link w wiadomośći prowadzi na localhost wiec bede musial wystawic na publica lizmape.



