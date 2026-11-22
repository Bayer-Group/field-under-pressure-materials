import argparse
import os
import sys
import time
from datetime import date, timedelta

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.windows import Window

sys.path.insert(0, os.path.dirname(__file__))
import siatka as S
# KONFIGURACJA LANDSAT:
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
KOLEKCJA = "landsat-c2-l2"
SATELITY = ["landsat-8", "landsat-9"]
PASMA = {"blue": "blue", "green": "green", "red": "red", "nir": "nir08", "swir": "swir16",
         "lst": "lwir11", "qa": "qa_pixel"}
PASMA_SR = ("blue", "green", "red", "nir", "swir")

SR_SKALA, SR_OFFSET = 0.0000275, -0.2
ST_SKALA, ST_OFFSET = 0.00341802, 149.0
QA_ODRZUC = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 7)

F = 16
MIN_CZYSTE = 0.8
NDVI_MIN_NDDI = 0.2

OSAVI_Y = 0.16
NNI_A, NNI_B = 1.01, 0.28
NDVI_MIN_NNI = 0.3
# WYSZUKIWANIE SCEN:
WSKAZNIKI = ("ndvi", "gndvi", "osavi", "ndwi", "evi", "lst")


def szukaj_scen(bbox, od, do, chmury, maks):
    import planetary_computer
    import pystac_client

    katalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    wyniki = katalog.search(collections=[KOLEKCJA], bbox=bbox, datetime=f"{od}/{do}",
                            query={"eo:cloud_cover": {"lt": chmury}, "platform": {"in": SATELITY}},
                            max_items=1000)
    sceny = []
    for it in wyniki.items():
        if all(k in it.assets for k in PASMA.values()):
            sceny.append({"id": it.id, "data": it.datetime.date().isoformat(),
                          "satelita": it.properties.get("platform", ""),
                          "chmury": it.properties.get("eo:cloud_cover"),
                          "href": {n: it.assets[k].href for n, k in PASMA.items()}})
    sceny.sort(key=lambda s: s["data"], reverse=True)
    return sceny[:maks]

# WSKAŹNIKI SPEKTRALNE:
def wskazniki(sr):
    """Wskaźniki z odbić powierzchniowych (słownik pasm PASMA_SR, ułamek 0–1)."""
    b, g, r, n, s = (sr[k] for k in PASMA_SR)
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            "ndvi": (n - r) / (n + r),
            "gndvi": (n - g) / (n + g),
            "osavi": (1 + OSAVI_Y) * (n - r) / (n + r + OSAVI_Y),
            "ndwi": (n - s) / (n + s),
            "evi": 2.5 * (n - r) / (n + 6 * r - 7.5 * b + 1),
        }

# ODCZYT SCENY I MASKA CHMUR:
def czytaj_scene(scena):
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES",
               GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="3")
    with rasterio.Env(**env):
        with rasterio.open(scena["href"]["qa"]) as q:
            h, w = q.height // F, q.width // F
            okno = Window(0, 0, w * F, h * F)
            qa = q.read(1, window=okno)
            crs = q.crs
            tr = q.transform * Affine.scale(F)
        bloki = lambda a: a.reshape(h, F, w, F).mean(axis=(1, 3))
        czyste = bloki(((qa & QA_ODRZUC) == 0).astype("float32"))
        wypelnienie = bloki((qa & 1).astype("float32"))
        del qa
        dane = {}
        for nazwa in PASMA_SR + ("lst",):
            with rasterio.open(scena["href"][nazwa]) as src:
                dane[nazwa] = src.read(1, window=okno, out_shape=(h, w),
                                       resampling=Resampling.average).astype("float64")
    # TEMPERATURA POWIERZCHNI (LST):
    dobre = (czyste >= MIN_CZYSTE) & (wypelnienie == 0)
    for k in PASMA_SR + ("lst",):
        dobre &= dane[k] > 0
    wsk = wskazniki({k: dane[k] * SR_SKALA + SR_OFFSET for k in PASMA_SR})
    wsk["lst"] = dane["lst"] * ST_SKALA + ST_OFFSET - 273.15
    for k in ("ndvi", "gndvi", "osavi", "ndwi"):
        dobre &= np.isfinite(wsk[k]) & (np.abs(wsk[k]) <= 1)
    wsk["evi"] = np.where(np.isfinite(wsk["evi"]) & (np.abs(wsk["evi"]) <= 1), wsk["evi"], np.nan)
    wynik = {k: np.where(dobre, wsk[k], np.nan).astype("float32") for k in WSKAZNIKI}
    return wynik, tr, crs


def na_siatke(arr, tr, crs, s):
    out = S.pusta(s)
    reproject(arr, out, src_transform=tr, src_crs=crs, src_nodata=np.nan,
              dst_transform=s["transform"], dst_crs=s["crs"], dst_nodata=np.nan,
              resampling=Resampling.average)
    return out

# NNI (ODŻYWIENIE AZOTEM):
def nni_z_evi(evi, ndvi):
    """NNI = 1,01 · EVI + 0,28 (Zhao i in. 2021), tylko na pikselach z roślinnością."""
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(evi) & np.isfinite(ndvi) & (ndvi >= NDVI_MIN_NNI)
        return np.where(ok, NNI_A * np.clip(evi, 0, 1) + NNI_B, np.nan)


def main():
    p = argparse.ArgumentParser(description="Kompozyt Landsat 8/9 dla Polski: NDVI, GNDVI, OSAVI, NDWI, NDDI, NNI, LST.")
    p.add_argument("--wyjscie", required=True, help="katalog na warstwy PNG i meta")
    p.add_argument("--chmury", type=float, default=10, help="maks. zachmurzenie sceny w %% (domyślnie 10)")
    p.add_argument("--dni", type=int, default=90, help="ile dni wstecz (domyślnie 90)")
    p.add_argument("--maks-scen", type=int, default=250)
    a = p.parse_args()

    s = S.siatka()
    dzis = date.today()
    od = dzis - timedelta(days=a.dni)
    sceny = szukaj_scen(list(S.BBOX_WGS), od.isoformat(), dzis.isoformat(), a.chmury, a.maks_scen)
    print(f"Sceny L8/L9 z zachmurzeniem < {a.chmury}% z ostatnich {a.dni} dni: {len(sceny)}")

    kompozyt = {k: S.pusta(s) for k in WSKAZNIKI}
    wiek = S.pusta(s)
    t0 = time.time()
    for i, sc in enumerate(sceny, 1):
        puste = ~np.isfinite(kompozyt["ndvi"])
        if not puste.any():
            break
        try:
            dane, tr, crs = czytaj_scene(sc)
        except Exception as e:
            print(f"  [{i}/{len(sceny)}] pomijam {sc['id']}: {e}")
            continue
        nowe = {k: na_siatke(v, tr, crs, s) for k, v in dane.items()}
        wstaw = puste & np.isfinite(nowe["ndvi"]) & np.isfinite(nowe["ndwi"])
        for k in kompozyt:
            kompozyt[k][wstaw] = nowe[k][wstaw]
        wiek[wstaw] = (dzis - date.fromisoformat(sc["data"])).days
        print(f"  [{i}/{len(sceny)}] {sc['data']} {sc['satelita']} chmury {sc['chmury']}%: "
              f"+{int(wstaw.sum())} px ({time.time() - t0:.0f} s)")

    ndvi, ndwi = kompozyt["ndvi"], kompozyt["ndwi"]
    with np.errstate(divide="ignore", invalid="ignore"):
        suma = ndvi + ndwi
        # NDDI (SUSZA):
        nddi = np.where((ndvi >= NDVI_MIN_NDDI) & (suma > 0.05), (ndvi - ndwi) / suma, np.nan)
    nni = nni_z_evi(kompozyt["evi"], ndvi)

    zakres = f"images from {od.isoformat()} – {dzis.isoformat()}, scene cloud cover < {a.chmury:g}%"
    W, G = a.wyjscie, "Landsat"

    POLSA = "Scale after the Polish Space Agency (POLSA)."
    warstwy = [
        S.zapisz_warstwe(W, "ndvi", ndvi, nazwa="NDVI", jednostka="", vmin=-1.0, vmax=1.0,
                         paleta="ndvi", grupa=G, data=zakres,
                         opis="Crop condition. Below 0: water, built-up areas; about 0: bare soil; below 0.2: sparse "
                              "or poor vegetation; 0.2–1: vegetation in varying condition; above 0.6: vegetation in "
                              "very good condition. " + POLSA),
        S.zapisz_warstwe(W, "gndvi", kompozyt["gndvi"], nazwa="GNDVI (chlorophyll)", jednostka="",
                         vmin=-1.0, vmax=1.0, paleta="ndvi", grupa=G, data=zakres,
                         opis="Green NDVI (NIR vs green, Gitelson et al. 1996), sensitive to leaf chlorophyll; used "
                              "to assess nitrogen needs. Normalized index from −1 to 1, read like NDVI. " + POLSA),
        S.zapisz_warstwe(W, "osavi", kompozyt["osavi"], nazwa="OSAVI (soil-adjusted)", jednostka="",
                         vmin=-1.0, vmax=1.0, paleta="ndvi", grupa=G, data=zakres,
                         opis="Optimized Soil-Adjusted Vegetation Index (SAVI with soil factor 0.16, Rondeaux et al. "
                              "1996). Reduces the soil effect, useful for young crops. Values from −1 to 1: about 0 "
                              "bare soil, the higher the value the denser the plant cover. " + POLSA),
        S.zapisz_warstwe(W, "ndwi", ndwi, nazwa="NDWI (plant water)", jednostka="", vmin=-1.0, vmax=1.0,
                         paleta="ndwi", grupa=G, data=zakres,
                         opis="Water content of plants and soil (NIR vs SWIR, Gao 1996). Normalized index from −1 to 1; "
                              "lower = drier."),
        S.zapisz_warstwe(W, "nddi", nddi, nazwa="NDDI (drought)", jednostka="", vmin=-1.0, vmax=1.0,
                         paleta="nddi", grupa=G, data=zakres,
                         opis="Drought index (Gu et al. 2007): (NDVI − NDWI) / (NDVI + NDWI). Higher = stronger water stress. "
                              "Scale −1 to 1; values above 1 (plant water index already negative) are shown in the end colour. "
                              "Not computed on bare soil."),
        S.zapisz_warstwe(W, "nni", nni, nazwa="NNI (nitrogen status)", jednostka="", vmin=0.7, vmax=1.3,
                         paleta="nni", grupa=G, data=zakres, miejsca=2,
                         opis="Nitrogen Nutrition Index estimated from EVI with the empirical model of Zhao et al. "
                              "(2021): NNI = 1.01 × EVI + 0.28. Classes: ≤ 0.7, 0.7–0.9, 0.9–1.1, 1.1–1.3, ≥ 1.3; "
                              "1.0 = optimal nitrogen supply, lower = deficiency, higher = surplus. Calibrated for "
                              "winter wheat (China) and valid only during vegetative growth; indicative, needs local "
                              "calibration. Meaningless outside cereal fields. " + POLSA),
        S.zapisz_warstwe(W, "lst", kompozyt["lst"], nazwa="Land surface temperature (Landsat)", jednostka="°C",
                         vmin=0, vmax=30, paleta="temperatura", grupa=G, data=zakres, miejsca=1,
                         opis="Surface temperature at the time of the satellite overpass (about 10:30 local time). "
                              "Values below 0 °C and above 30 °C are shown in the end colours. " + POLSA),
        S.zapisz_warstwe(W, "landsat_wiek", wiek, nazwa="Image age", jednostka="days", vmin=0, vmax=254,
                         paleta="szara", grupa=G, ukryta=True, miejsca=0),
    ]
    S.zapisz_meta(W, "landsat", warstwy, data_odniesienia=dzis.isoformat(), liczba_scen=len(sceny),
                  opis=zakres)


if __name__ == "__main__":
    main()