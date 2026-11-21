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
w publicu: field_id, zone, area_ha, ndvi_z, dose_kg_n_ha, dose_kg_product_ha, geom). Eksport shapefile
z atrybutem dawki Sprawdziłem i większość terminali w John Deerach, Trimble, Topcony przyjmują shapefile
ISOXML jako rozszerzenie jeśli zostanie czas

10 Ja przychodze dostaje dane i robie lizmape warstw stref (czerwona, źółta, zielona) popup strefy z powierzchnią
i dawką, w popupie pola karta "Mapa dawek" z oszczędnością i przyciskiem do pobrania.

Może taka
<img width="605" height="356" alt="image" src="https://github.com/user-attachments/assets/9a545133-67b3-4057-bfa6-29b8be66a55d" />

