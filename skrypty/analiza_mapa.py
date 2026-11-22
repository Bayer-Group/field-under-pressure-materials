import argparse
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import siatka as S
# UPRAWY (id w kodzie: nazwa na stronie):
UPRAWY = {
    "pszenica_jara": "Spring wheat",
    "pszenica_ozima": "Winter wheat",
    "ziemniak": "Potato",
    "kukurydza": "Corn",
}

# KLASY ZAGROŻENIA (nazwa na stronie, punkty od, punkty do):
KLASY_ZAGROZENIA = [
    ("I – low", 0, 4),
    ("II – moderate", 5, 13),
    ("III – high", 14, 20),
    ("IV – very high", 21, 24),
]

# GRUPY GLEB (nazwy jak w legendzie warstwy "Soil type" z gleba_mapa.py):
PIASKI = ["Sand", "Fine sand", "Loamy sand"]
PIASKI_GLINIASTE = ["Sandy loam"]
GLINY_LEKKIE_I_PYLY = ["Loam", "Loamy very fine sand", "Fine sandy loam", "Silt"]
GLEBY_SREDNIE_I_CIEZKIE = ["Silt loam", "Clay loam", "Clay", "Silty clay", "Heavy clay"]

# KRYTERIA:
# punkty      - punkty za klasy I, II, III, IV
# wymagane    - False: przy braku danych wynik liczony z pozostałych kryteriów i przeskalowany do 24 pkt
# przedzialy  - (od, do, klasa): "od" włącznie, "do" wyłącznie, None = bez granicy; "*" = wszystkie uprawy
# grupy       - typy gleb w klasach I, II, III, IV
KRYTERIA = [
    {"id": "nddi", "nazwa": "NDDI (drought)", "warstwa": "nddi", "jednostka": "",
     "punkty": [0, 2, 4, 6], "wymagane": False,
     "przedzialy": {"*": [(None, 0.1, 1), (0.1, 0.3, 2), (0.3, 0.5, 3), (0.5, None, 4)]}},

    {"id": "gleba", "nazwa": "Soil type", "warstwa": "gleba_klasa", "jednostka": "",
     "punkty": [0, 2, 4, 6], "wymagane": True,
     # piaski: najwyższe ryzyko suszy (woda szybko ucieka) - klasa IV, 6 pkt; klasa I bez typów gleb
     "grupy": {
         "pszenica_jara": [[], PIASKI_GLINIASTE, GLEBY_SREDNIE_I_CIEZKIE, GLINY_LEKKIE_I_PYLY + PIASKI],
         "pszenica_ozima": [[], PIASKI_GLINIASTE, GLINY_LEKKIE_I_PYLY, GLEBY_SREDNIE_I_CIEZKIE + PIASKI],
         "ziemniak": [[], GLEBY_SREDNIE_I_CIEZKIE, GLINY_LEKKIE_I_PYLY, PIASKI_GLINIASTE + PIASKI],
         "kukurydza": [[], PIASKI_GLINIASTE, GLEBY_SREDNIE_I_CIEZKIE, GLINY_LEKKIE_I_PYLY + PIASKI],
     }},

    {"id": "temperatura", "nazwa": "Soil temperature", "warstwa": "t_gleby_era5", "jednostka": "°C",
     "punkty": [0, 2, 4, 6], "wymagane": True,
     "przedzialy": {
         "pszenica_jara": [(6, None, 1), (4, 6, 2), (3, 4, 3), (None, 3, 4)],
         # powyżej 25 °C tabela nie podaje klasy - przyjęta klasa II
         "pszenica_ozima": [(12, 25, 1), (8, 12, 2), (4, 8, 3), (None, 4, 4), (25, None, 2)],
         "ziemniak": [(8, None, 1), (6, 8, 2), (4, 6, 3), (None, 4, 4)],
         "kukurydza": [(10, None, 1), (8, 10, 2), (6, 8, 3), (None, 6, 4)],
     }},

    {"id": "woda", "nazwa": "Soil water", "warstwa": "woda_w_porach", "jednostka": "%",
     "punkty": [0, 2, 4, 6], "wymagane": True,
     "przedzialy": {
         # dużo wody w porach = małe zagrożenie (klasa I), mało wody = klasa IV
         "pszenica_jara": [(75, None, 1), (55, 75, 2), (30, 55, 3), (None, 30, 4)],
         "pszenica_ozima": [(70, None, 1), (45, 70, 2), (25, 45, 3), (None, 25, 4)],
         "ziemniak": [(80, None, 1), (65, 80, 2), (35, 65, 3), (None, 35, 4)],
         "kukurydza": [(75, None, 1), (50, 75, 2), (30, 50, 3), (None, 30, 4)],
     }},
]
MAKS_PUNKTOW = sum(max(k["punkty"]) for k in KRYTERIA)

GRUPA = "Final analysis"
OPIS = ("Multi-criteria hazard assessment from four criteria: NDDI, soil type, soil temperature and soil water. "
        "Each criterion gives 0, 2, 4 or 6 points for hazard classes I–IV; the sum (0–24 points) gives the final "
        "class: I low 0–4, II moderate 5–13, III high 14–20, IV very high 21–24. Where NDDI is missing (bare soil, "
        "clouds), the score from the other three criteria is scaled to 24 points.")

# ODCZYT WARSTW Z PNG:
def wczytaj_opisy(katalog):
    opisy, zrodla = {}, {}
    for plik in sorted(glob.glob(os.path.join(katalog, "meta_*.json"))):
        if os.path.basename(plik) == "meta_analiza.json":
            continue
        with open(plik, encoding="utf-8") as f:
            m = json.load(f)
        for w in m.pop("warstwy"):
            opisy[w["id"]] = w
        zrodla[m.pop("zrodlo")] = m
    return opisy, zrodla


def opis_danych(zrodla):
    czesci = []
    if "era5" in zrodla:
        czesci.append(f"Soil temperature and water: ERA5-Land, 3-day mean to {zrodla['era5'].get('ostatni_dzien', '?')}")
    if "landsat" in zrodla:
        czesci.append(f"NDDI: Landsat, {zrodla['landsat'].get('opis', '')}")
    if "gleba" in zrodla:
        czesci.append("Soil: SoilGrids 2.0")
    return " · ".join(czesci)


def odczytaj(katalog, w, s):
    q = np.array(Image.open(os.path.join(katalog, w["plik"]))).astype("float64")
    if q.shape != (s["wys"], s["szer"]):
        sys.exit(f"Warstwa {w['id']} ma rozmiar {q.shape}, a siatka {(s['wys'], s['szer'])}.")
    v = q.copy() if w.get("kategorie") else w["min"] + (q - 1) / 254 * (w["max"] - w["min"])
    v[q == 0] = np.nan
    return v

# KLASYFIKACJA:
def klasa_z_przedzialow(v, przedzialy):
    klasa = np.full(v.shape, np.nan)
    for od, do, k in przedzialy:
        m = np.isfinite(v) & np.isnan(klasa)
        if od is not None:
            m &= v >= od
        if do is not None:
            m &= v < do
        klasa[m] = k
    return klasa


def klasa_gleby(nr, kategorie, grupy):
    tablica = np.full(256, np.nan)
    for i, etykieta in enumerate(kategorie, start=1):
        nazwa = etykieta.split(" (")[0].strip().lower()
        for k, nazwy in enumerate(grupy, start=1):
            if nazwa in (n.lower() for n in nazwy):
                tablica[i] = k
        if np.isnan(tablica[i]):
            sys.exit(f"Typ gleby '{etykieta}' nie ma przypisanej klasy zagrożenia w KRYTERIA.")
    return np.where(np.isfinite(nr), tablica[np.nan_to_num(nr).astype(int).clip(0, 255)], np.nan)


def klasa_kryterium(kr, uprawa, v, opis_warstwy):
    if "grupy" in kr:
        return klasa_gleby(v, opis_warstwy["kategorie"], kr["grupy"][uprawa])
    return klasa_z_przedzialow(v, kr["przedzialy"].get(uprawa, kr["przedzialy"].get("*")))


def klasa_zagrozenia(wynik):
    klasa = np.full(wynik.shape, np.nan)
    for k, (_, od, do) in enumerate(KLASY_ZAGROZENIA, start=1):
        klasa[np.isfinite(wynik) & (wynik >= od) & (wynik <= do)] = k
    return klasa

# ANALIZA DLA JEDNEJ UPRAWY:
def analiza_uprawy(uprawa, wartosci, opisy, s):
    suma, maks = S.pusta(s, 0.0), S.pusta(s, 0.0)
    komplet = np.ones((s["wys"], s["szer"]), dtype=bool)
    for kr in KRYTERIA:
        klasa = klasa_kryterium(kr, uprawa, wartosci[kr["warstwa"]], opisy.get(kr["warstwa"], {}))
        punkty = np.array([np.nan] + kr["punkty"])[np.nan_to_num(klasa).astype(int)]
        ok = np.isfinite(punkty)
        suma[ok] += punkty[ok]
        maks[ok] += max(kr["punkty"])
        if kr["wymagane"]:
            komplet &= ok
    with np.errstate(invalid="ignore", divide="ignore"):
        wynik = np.where(komplet, np.floor(suma * MAKS_PUNKTOW / maks + 0.5), np.nan)
    return klasa_zagrozenia(wynik)


def main():
    p = argparse.ArgumentParser(description="Multi-criteria hazard analysis for the Final analysis tab.")
    p.add_argument("--dane", default="_dane", help="katalog z warstwami PNG i plikami meta_*.json")
    a = p.parse_args()
    s = S.siatka()
    opisy, zrodla = wczytaj_opisy(a.dane)
    data = opis_danych(zrodla)

    # WARSTWY WEJŚCIOWE:
    wartosci = {}
    for id_ in ("gleba_klasa", "porowatosc", "t_gleby_era5", "wilg_gleby_era5", "nddi"):
        if id_ in opisy:
            wartosci[id_] = odczytaj(a.dane, opisy[id_], s)
        elif id_ == "nddi":
            print("Brak warstwy NDDI - analiza z pozostałych kryteriów.")
            wartosci[id_] = S.pusta(s)
        else:
            sys.exit(f"Brak warstwy '{id_}' w {a.dane} - najpierw uruchom gleba_mapa.py i era5_mapa.py.")

    # WODA W PORACH GLEBY: wilgotność objętościowa ERA5 / porowatość z gleba_mapa.py
    with np.errstate(invalid="ignore", divide="ignore"):
        woda = 100 * wartosci["wilg_gleby_era5"] / (wartosci["porowatosc"] / 100)
    wartosci["woda_w_porach"] = np.clip(woda, 0, 100)

    warstwy = [S.zapisz_warstwe(a.dane, "woda_w_porach", wartosci["woda_w_porach"], nazwa="Soil water (pore filling)",
                                jednostka="%", vmin=0, vmax=100, paleta="wilgotnosc", grupa=GRUPA, ukryta=True,
                                miejsca=0, data=data,
                                opis="Share of soil pores filled with water: ERA5-Land soil moisture (0–7 cm) "
                                     "divided by total porosity.")]
    nazwy_klas = [n for n, _, _ in KLASY_ZAGROZENIA]
    for uprawa, nazwa in UPRAWY.items():
        klasa = analiza_uprawy(uprawa, wartosci, opisy, s)
        udzialy = [np.nansum(klasa == k) / max(np.isfinite(klasa).sum(), 1) for k in range(1, 5)]
        print(f"{nazwa}: " + ", ".join(f"{n.split(' –')[0]} {100 * u:.0f}%" for n, u in zip(nazwy_klas, udzialy)))
        warstwy.append(S.zapisz_warstwe(a.dane, f"analiza_{uprawa}", klasa, nazwa=f"Hazard – {nazwa}", jednostka="",
                                        vmin=1, vmax=len(KLASY_ZAGROZENIA), paleta="zagrozenie", grupa=GRUPA,
                                        ukryta=True, kategorie=nazwy_klas, opis=OPIS, data=data))

    # OPIS DLA STRONY: kryteria i progi, żeby zakładka pokazała rozbicie punktów
    S.zapisz_meta(a.dane, "analiza", warstwy, opis=OPIS, maks_punktow=MAKS_PUNKTOW,
                  uprawy=[{"id": u, "nazwa": n, "warstwa": f"analiza_{u}"} for u, n in UPRAWY.items()],
                  klasy=[{"nazwa": n, "od": od, "do": do} for n, od, do in KLASY_ZAGROZENIA],
                  kryteria=KRYTERIA)


if __name__ == "__main__":
    main()
