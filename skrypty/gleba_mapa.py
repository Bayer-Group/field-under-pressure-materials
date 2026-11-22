import argparse
import os
import sys

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds

sys.path.insert(0, os.path.dirname(__file__))
import siatka as S
# KONFIGURACJA SOILGRIDS:
DOCELOWY_EPSG = "EPSG:3857"

URL = "/vsicurl/https://files.isric.org/soilgrids/latest/data/{zm}/{zm}_{gl}_mean.vrt"
GLEBOKOSCI = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}
ZMIENNE = {"sand": 0.1, "silt": 0.1, "clay": 0.1, "soc": 0.01}
WEGIEL_NA_PROCHNICE = 1.724
GESTOSC_FAZY_STALEJ = 2.65

KLASY_BN78 = [
    ("pl", "Sand"), ("plp", "Fine sand"), ("ps", "Loamy sand"), ("psp", "Loamy sand"),
    ("pgl", "Sandy loam"), ("pglp", "Sandy loam"), ("pgm", "Sandy loam"), ("pgmp", "Sandy loam"),
    ("gl", "Loam"), ("glp", "Loam"), ("płg", "Loamy very fine sand"), ("płz", "Silt"), ("płp", "Fine sandy loam"),
    ("gs", "Silt loam"), ("gsp", "Silt loam"), ("gc", "Clay loam"), ("gcp", "Clay loam"),
    ("płi", "Clay"), ("i", "Heavy clay"), ("ip", "Silty clay"),
]
KLASY = [f"{nazwa} ({symbol})" for symbol, nazwa in KLASY_BN78]
NR = {symbol: i for i, (symbol, _) in enumerate(KLASY_BN78, start=1)}

PIASEK_0_1 = np.log(2) / np.log(40)

# FRAKCJE BN-78:
def frakcje_bn78(piasek, pyl, il):
    gruby = np.clip(0.65 - 0.5 * il / 100, 0.3, 0.65)
    splawialne = il + (1 - gruby) * pyl
    pyl_bn = gruby * pyl + PIASEK_0_1 * piasek
    return 100 - splawialne - pyl_bn, pyl_bn, splawialne

# GLEBA:
def klasy_bn78(piasek, pyl, spl):
    pylasty = pyl > 25
    ilaste, pylowe = (spl > 50) & (piasek < 10), (pyl > 40) & (spl <= 50)
    warunki_i_klasy = [
        (ilaste & pylasty, "ip"), (ilaste, "i"),
        (pylowe & (spl <= 20) & (piasek >= 25), "płp"), (pylowe & (spl <= 20), "płz"),
        (pylowe & (spl <= 35), "płg"), (pylowe, "płi"),
    ]
    for granica, symbol in [(5, "pl"), (10, "ps"), (15, "pgl"), (20, "pgm"), (35, "gl"), (50, "gs")]:
        warunki_i_klasy += [((spl <= granica) & pylasty, symbol + "p"), ((spl <= granica), symbol)]
    warunki_i_klasy += [(pylasty, "gcp")]
    return np.select([w for w, _ in warunki_i_klasy], [NR[k] for _, k in warunki_i_klasy], default=NR["gc"])

# POROWATOŚĆ I GĘSTOŚĆ GLEBY:
def porowatosc_saxton_rawls(piasek, il, prochnica):
    s, c, om = piasek, np.minimum(il, 0.6), np.clip(prochnica, 0, 8)
    t33t = -0.251 * s + 0.195 * c + 0.011 * om + 0.006 * s * om - 0.027 * c * om + 0.452 * s * c + 0.299
    t33 = t33t + (1.283 * t33t ** 2 - 0.374 * t33t - 0.015)
    ts33t = 0.278 * s + 0.034 * c + 0.022 * om - 0.018 * s * om - 0.027 * c * om - 0.584 * s * c + 0.078
    ts33 = ts33t + (0.636 * ts33t - 0.107)
    theta_s = t33 + ts33 - 0.097 * s + 0.043
    return theta_s, (1 - theta_s) * GESTOSC_FAZY_STALEJ

# POBIERANIE RASTRA:
def czytaj_na_siatke(url, s):
    with rasterio.open(url) as src:
        b = transform_bounds(DOCELOWY_EPSG, src.crs, s["xmin"], s["ymin"], s["xmax"], s["ymax"], densify_pts=50)
        okno = from_bounds(*b, transform=src.transform).round_offsets(op="floor").round_lengths(op="ceil")
        dane = src.read(1, window=okno, boundless=True, fill_value=src.nodata if src.nodata is not None else 0)
        dane = dane.astype("float32")
        if src.nodata is not None:
            dane[dane == src.nodata] = np.nan
        out = S.pusta(s)
        reproject(dane, out, src_transform=src.window_transform(okno), src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=s["transform"], dst_crs=DOCELOWY_EPSG, dst_nodata=np.nan,
                  resampling=Resampling.average)
    return out


def main():
    p = argparse.ArgumentParser(description="Soil map of Poland from SoilGrids 2.0.")
    p.add_argument("--wyjscie", required=True)
    a = p.parse_args()
    s = S.siatka()
    if s["crs"] != DOCELOWY_EPSG:
        sys.exit(f"Siatka w siatka.py jest w {s['crs']}, a ten skrypt liczy w {DOCELOWY_EPSG}.")
    # ŚREDNIA WAŻONA 0-30 CM:
    wart = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="5"):
        for zm, mnoznik in ZMIENNE.items():
            suma, wagi = S.pusta(s, 0.0), S.pusta(s, 0.0)
            for gl, waga in GLEBOKOSCI.items():
                print(f"SoilGrids {zm} {gl} ...")
                v = czytaj_na_siatke(URL.format(zm=zm, gl=gl), s) * mnoznik
                ok = np.isfinite(v)
                suma[ok] += v[ok] * waga
                wagi[ok] += waga
            wart[zm] = np.where(wagi > 0, suma / np.where(wagi > 0, wagi, 1), np.nan)
    # PRÓCHNICA I POROWATOŚĆ:
    razem = wart["sand"] + wart["silt"] + wart["clay"]
    ok = np.isfinite(razem) & (razem > 0) & np.isfinite(wart["soc"])
    with np.errstate(invalid="ignore", divide="ignore"):
        piasek, pyl, il = (np.where(ok, 100 * wart[k] / razem, np.nan) for k in ("sand", "silt", "clay"))
    klasa = np.where(ok, klasy_bn78(*frakcje_bn78(np.nan_to_num(piasek), np.nan_to_num(pyl), np.nan_to_num(il))),
                     np.nan)
    prochnica = wart["soc"] * WEGIEL_NA_PROCHNICE
    theta_s, bd = porowatosc_saxton_rawls(piasek / 100, il / 100, prochnica)
    porowatosc = np.where(ok, 100 * theta_s, np.nan)
    bd = np.where(ok, bd, np.nan)

    W, opis = a.wyjscie, "SoilGrids 2.0 (ISRIC), mean 0–30 cm"
    warstwy = [
        S.zapisz_warstwe(W, "gleba_klasa", klasa, nazwa="Soil type", jednostka="",
                         vmin=1, vmax=len(KLASY), paleta="kategorie_gleba", grupa="Soil", kategorie=KLASY,
                         data=opis, opis="Polish soil texture groups (BN-78/9180-11, Feret triangle) estimated from "
                                         "SoilGrids sand, silt and clay converted to the Polish fraction limits."),
        S.zapisz_warstwe(W, "porowatosc", porowatosc, nazwa="Soil porosity", jednostka="%", vmin=35, vmax=55,
                         paleta="porowatosc", grupa="Soil", data=opis, miejsca=1,
                         opis="Total porosity from texture and organic matter "
                              "(Saxton & Rawls 2006 pedotransfer function)."),
        S.zapisz_warstwe(W, "piasek", piasek, nazwa="Sand", jednostka="%", vmin=0, vmax=100, paleta="szara",
                         grupa="Soil", ukryta=True, miejsca=0),
        S.zapisz_warstwe(W, "il", il, nazwa="Clay", jednostka="%", vmin=0, vmax=100, paleta="szara",
                         grupa="Soil", ukryta=True, miejsca=0),
        S.zapisz_warstwe(W, "gestosc", bd, nazwa="Bulk density", jednostka="g/cm³", vmin=0.5, vmax=2.0,
                         paleta="szara", grupa="Soil", ukryta=True, miejsca=2),
    ]
    S.zapisz_meta(W, "gleba", warstwy, opis=opis)


if __name__ == "__main__":
    main()