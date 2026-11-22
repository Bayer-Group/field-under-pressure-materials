import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

sys.path.insert(0, os.path.dirname(__file__))
import siatka as S
# KONFIGURACJA API I SIATKI:
ARCHIWUM_URL = "https://archive-api.open-meteo.com/v1/archive"
STREFA = "Europe/Warsaw"
KROK = 0.25
PACZKA = 100
PRZERWA_S = 15
OPOZNIENIE_DNI = 5
DNI = 7

# POBIERANIE JSON:
def pobierz_json(url, parametry, proby=4):
    pelny = url + "?" + urllib.parse.urlencode(parametry, safe=",")
    for proba in range(1, proby + 1):
        try:
            with urllib.request.urlopen(pelny, timeout=120) as odp:
                dane = json.load(odp)
            return dane if isinstance(dane, list) else [dane]
        except urllib.error.HTTPError as e:
            tresc = e.read().decode("utf-8", "replace")
            if e.code == 429 and proba < proby:
                time.sleep(65)
                continue
            if e.code < 500 or proba == proby:
                raise RuntimeError(f"Błąd API {e.code}: {tresc}") from e
        except urllib.error.URLError as e:
            if proba == proby:
                raise RuntimeError(f"Brak połączenia z API: {e}") from e
        time.sleep(10 * proba)

# ŚREDNIA DOBOWA:
def srednia_ostatnich_dni(godziny, wartosci, n=3):
    dni = {}
    for t, v in zip(godziny, wartosci or []):
        if v is not None:
            dni.setdefault(t[:10], []).append(v)
    pelne = [(d, sum(w) / len(w)) for d, w in sorted(dni.items()) if len(w) >= 20]
    ostatnie = pelne[-n:]
    if not ostatnie:
        return None, None
    return sum(v for _, v in ostatnie) / len(ostatnie), ostatnie[-1][0]

# SIATKA PUNKTÓW I DATY:
def main():
    p = argparse.ArgumentParser(description="Mapa ERA5-Land dla Polski.")
    p.add_argument("--wyjscie", required=True)
    a = p.parse_args()
    s = S.siatka()

    lon0, lat0, lon1, lat1 = S.BBOX_WGS
    lons = np.arange(lon0 - KROK, lon1 + KROK + 1e-9, KROK)
    lats = np.arange(lat1 + KROK, lat0 - KROK - 1e-9, -KROK)
    punkty = [(la, lo) for la in lats for lo in lons]
    dzis = datetime.now(ZoneInfo(STREFA)).date()
    koniec = dzis - timedelta(days=OPOZNIENIE_DNI)
    start = koniec - timedelta(days=DNI - 1)
    print(f"ERA5-Land: {len(punkty)} punktów siatki {KROK}°, dni {start} – {koniec}")

    # TEMPERATURA I WILGOTNOŚĆ GLEBY (0-7 cm) ORAZ OPADY:
    t = np.full(len(punkty), np.nan)
    w = np.full(len(punkty), np.nan)
    o = np.full(len(punkty), np.nan)
    daty = []
    for i in range(0, len(punkty), PACZKA):
        paczka = punkty[i:i + PACZKA]
        wyniki = pobierz_json(ARCHIWUM_URL, {
            "latitude": ",".join(f"{la:.3f}" for la, _ in paczka),
            "longitude": ",".join(f"{lo:.3f}" for _, lo in paczka),
            "start_date": start.isoformat(), "end_date": koniec.isoformat(),
            "hourly": "soil_temperature_0_to_7cm,soil_moisture_0_to_7cm",
            "daily": "precipitation_sum",

            "models": "era5_land,era5",
            "timezone": ",".join([STREFA] * len(paczka)),
        })
        for j, r in enumerate(wyniki):
            h = r.get("hourly", {})
            tv, d = srednia_ostatnich_dni(h.get("time", []), h.get("soil_temperature_0_to_7cm_era5_land"))
            wv, _ = srednia_ostatnich_dni(h.get("time", []), h.get("soil_moisture_0_to_7cm_era5_land"))
            op = [v for v in r.get("daily", {}).get("precipitation_sum_era5", []) if v is not None]
            t[i + j] = np.nan if tv is None else tv
            w[i + j] = np.nan if wv is None else wv
            o[i + j] = sum(op) if op else np.nan
            if d:
                daty.append(d)
        print(f"  {min(i + PACZKA, len(punkty))}/{len(punkty)}")
        if i + PACZKA < len(punkty):
            time.sleep(PRZERWA_S)

    tr_src = from_origin(lons[0] - KROK / 2, lats[0] + KROK / 2, KROK, KROK)
    ksztalt = (len(lats), len(lons))

    def na_siatke(v):
        out = S.pusta(s)
        reproject(v.reshape(ksztalt).astype("float32"), out, src_transform=tr_src, src_crs="EPSG:4326",
                  src_nodata=np.nan, dst_transform=s["transform"], dst_crs="EPSG:3857", dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
        return out

    # ZAPIS WARSTW:
    ostatni = max(daty) if daty else koniec.isoformat()
    opis = f"ERA5-Land (Copernicus) przez Open-Meteo, średnia 3 dni do {ostatni}"
    W = a.wyjscie
    warstwy = [
        S.zapisz_warstwe(W, "t_gleby_era5", na_siatke(t), nazwa="Soil temperature 0–7 cm (ERA5-Land)",
                         jednostka="°C", vmin=-10, vmax=30, paleta="temperatura", grupa="ERA5-Land",
                         data=opis, miejsca=1, opis="Daily average for the last 3 available days."),
        S.zapisz_warstwe(W, "wilg_gleby_era5", na_siatke(w), nazwa="Soil moisture 0–7 cm (ERA5-Land)",
                         jednostka="m³/m³", vmin=0.05, vmax=0.50, paleta="wilgotnosc", grupa="ERA5-Land",
                         data=opis, miejsca=2, opis="Volumetric water content in the topsoil layer."),
        S.zapisz_warstwe(W, "opady_7d_era5", na_siatke(o), nazwa="Downfall – sum from last 7 days (ERA5)",
                         jednostka="mm", vmin=0, vmax=60, paleta="opady", grupa="ERA5-Land",
                         data=f"ERA5, {start} – {koniec}", miejsca=1),
    ]
    S.zapisz_meta(W, "era5", warstwy, opis=opis, ostatni_dzien=ostatni)


if __name__ == "__main__":
    main()
