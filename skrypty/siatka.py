import argparse
import glob
import json
import math
import os

import numpy as np
from PIL import Image
from rasterio.transform import from_origin
# PARAMETRY SIATKI:
CRS_MAPY = "EPSG:3857"
BBOX_WGS = (14.0, 48.9, 24.3, 55.0)
PIKSEL_M = 800.0
R = 6378137.0

# ODWZOROWANIE MERCATORA:
def _merc(lon, lat):
    return (math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R)


def _wgs(x, y):
    return (math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2))

# DEFINICJA RASTRA:
def siatka():
    x0, y0 = _merc(BBOX_WGS[0], BBOX_WGS[1])
    x1, y1 = _merc(BBOX_WGS[2], BBOX_WGS[3])
    xmin = math.floor(x0 / PIKSEL_M) * PIKSEL_M
    ymin = math.floor(y0 / PIKSEL_M) * PIKSEL_M
    xmax = math.ceil(x1 / PIKSEL_M) * PIKSEL_M
    ymax = math.ceil(y1 / PIKSEL_M) * PIKSEL_M
    szer = int(round((xmax - xmin) / PIKSEL_M))
    wys = int(round((ymax - ymin) / PIKSEL_M))
    (lon_w, lat_s), (lon_e, lat_n) = _wgs(xmin, ymin), _wgs(xmax, ymax)
    return {
        "crs": CRS_MAPY,
        "szer": szer, "wys": wys,
        "transform": from_origin(xmin, ymax, PIKSEL_M, PIKSEL_M),
        "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax, "piksel_m": PIKSEL_M,
        "granice_wgs": [[lat_s, lon_w], [lat_n, lon_e]],
    }


def pusta(s, wartosc=np.nan, dtype="float32"):
    return np.full((s["wys"], s["szer"]), wartosc, dtype=dtype)


def zapisz_warstwe(katalog, id_, dane, *, nazwa, jednostka, vmin, vmax, paleta, grupa,
                   opis="", data="", ukryta=False, kategorie=None, miejsca=2):

    os.makedirs(katalog, exist_ok=True)
    dane = np.asarray(dane, dtype="float64")
    braki = ~np.isfinite(dane)
    if kategorie:
        q = np.where(braki, 0, np.clip(np.nan_to_num(dane), 0, 255)).astype("uint8")
    else:
        skala = (np.clip(np.nan_to_num(dane, nan=vmin), vmin, vmax) - vmin) / (vmax - vmin)
        q = (np.round(skala * 254) + 1).astype("uint8")
        q[braki] = 0
    Image.fromarray(q, mode="L").save(os.path.join(katalog, f"{id_}.png"), optimize=True)
    pokrycie = float((q > 0).mean())
    print(f"  zapisano {id_}.png ({q.shape[1]}x{q.shape[0]}, pokrycie {100 * pokrycie:.1f}%)")
    return {
        "id": id_, "plik": f"{id_}.png", "nazwa": nazwa, "jednostka": jednostka,
        "min": vmin, "max": vmax, "paleta": paleta, "grupa": grupa, "opis": opis,
        "data": data, "ukryta": ukryta, "kategorie": kategorie, "miejsca": miejsca,
        "pokrycie": round(pokrycie, 4),
    }


def zapisz_meta(katalog, zrodlo, warstwy, **dodatkowe):
    os.makedirs(katalog, exist_ok=True)
    with open(os.path.join(katalog, f"meta_{zrodlo}.json"), "w", encoding="utf-8") as f:
        json.dump({"zrodlo": zrodlo, "warstwy": warstwy, **dodatkowe}, f, ensure_ascii=False, indent=1)

# SCALANIE METADANYCH:
def polacz_meta(katalog):
    s = siatka()
    from datetime import datetime, timezone
    wynik = {"wersja": datetime.now(timezone.utc).strftime("%Y%m%d%H%M"),
             "siatka": {k: s[k] for k in ("szer", "wys", "xmin", "ymin", "xmax", "ymax", "piksel_m", "granice_wgs")},
             "zrodla": {}, "warstwy": []}
    for plik in sorted(glob.glob(os.path.join(katalog, "meta_*.json"))):
        with open(plik, encoding="utf-8") as f:
            m = json.load(f)
        wynik["warstwy"].extend(m.pop("warstwy"))
        wynik["zrodla"][m.pop("zrodlo")] = m
    with open(os.path.join(katalog, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(wynik, f, ensure_ascii=False, indent=1)
    print(f"meta.json: {len(wynik['warstwy'])} warstw z {len(wynik['zrodla'])} źródeł")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--polacz", required=True, help="katalog z plikami meta_*.json")
    polacz_meta(p.parse_args().polacz)
