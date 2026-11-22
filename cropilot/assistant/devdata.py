"""
Synthetic demo data for developing and testing the assistant. NOT the platform's seed.

Used by `python manage.py assistant_dev_seed` (local development, until the platform's import and
the decision engine exist) and by the assistant's tests (a small window). Everything it creates is
marked as synthetic: weather grids start with "DEV_", threats have source "dev_seed", risk
explanations say "dev_seed (syntetyczne)".

Risks are written here only because the engine (Bartek) does not exist yet; in the real system
only the engine writes the Risk table.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction

DEV_GRID_PREFIX = "DEV_"
DEV_SOURCE = "dev_seed"

CROP_WHEAT, CROP_MAIZE = 1110, 1130

DEV_FIELDS = [
    # name, crop, area_ha, (lon, lat) of the south-west corner
    ("Pole Północne", CROP_WHEAT, 20.4, (19.950, 50.040)),
    ("Pole przy Lesie", CROP_WHEAT, 12.4, (19.962, 50.036)),
    ("Pole Długie", CROP_WHEAT, 8.7, (19.944, 50.031)),
    ("Kukurydza Zachód", CROP_MAIZE, 15.2, (19.935, 50.025)),
    ("Kukurydza Wschód", CROP_MAIZE, 10.9, (19.970, 50.027)),
]

@dataclass
class DevWorld:
    today: date
    fields: list
    threats: list
    n_risks: int


def _weather_for(day: date, rnd: random.Random) -> dict:
    doy = day.timetuple().tm_yday
    base = 10 + 9 * math.sin((doy - 100) / 365 * 2 * math.pi)  # ~10 °C in April -> ~19 °C in July
    avg = base + rnd.uniform(-3.5, 3.5)
    rain = rnd.choice([0, 0, 0, 0, 0.4, 1.5, 4, 9, 16])
    rh = min(99.0, 62 + rain * 2.2 + rnd.uniform(-8, 10))
    return {
        "avg_temperature": round(avg, 1), "min_temperature": round(avg - rnd.uniform(4, 8), 1),
        "max_temperature": round(avg + rnd.uniform(4, 9), 1), "total_precipitation": float(rain),
        "avg_relative_humidity": round(rh, 1), "max_relative_humidity": round(min(100.0, rh + 12), 1),
        "min_relative_humidity": round(max(20.0, rh - 25), 1), "avg_wind_speed": round(rnd.uniform(5, 22), 1),
    }


def _risk(threat, weather: list[dict], day_idx: int) -> tuple[float, dict]:
    """Toy rule: temperature inside the favourable range x wetness of the last 3 days."""
    w = weather[day_idx]
    last3 = weather[max(0, day_idx - 2): day_idx + 1]
    rain3 = sum(x["total_precipitation"] for x in last3)
    rh3 = sum(x["avg_relative_humidity"] for x in last3) / len(last3)
    t = w["avg_temperature"]
    tmin, tmax = threat.temp_min_c, threat.temp_max_c
    if tmin is not None and tmax is not None:
        temp_fit = 1.0 if tmin <= t <= tmax else max(0.0, 1 - min(abs(t - tmin), abs(t - tmax)) / 6)
        thr = f"{tmin:g}–{tmax:g} °C"
    else:
        temp_fit = 0.6 + 0.4 * max(0.0, min(1.0, (t - 8) / 10))  # no range in the source: mild effect
        thr = "brak zakresu w źródle"
    if threat.category == "pest":
        score = 0.55 * temp_fit * max(0.0, min(1.0, (t - 10) / 10)) + 0.15 * (1 - min(rain3, 20) / 20)
    else:
        wet = 0.6 * max(0.0, min(1.0, (rh3 - 60) / 35)) + 0.4 * min(rain3, 20) / 20
        score = temp_fit * (0.08 + 0.95 * wet)
    score = round(max(0.0, min(1.0, score)), 3)
    factors = [
        {"variable": "avg_temperature", "value": t, "unit": "°C", "threshold": thr},
        {"variable": "avg_relative_humidity", "value": round(rh3, 1), "unit": "%", "threshold": "≥ 80 (średnia 3 dni)"},
        {"variable": "total_precipitation", "value": round(rain3, 1), "unit": "mm", "threshold": "suma 3 dni"},
    ]
    in_range = "w zakresie sprzyjającym" if temp_fit >= 1 else "poza zakresem sprzyjającym"
    summary = (f"Średnia temperatura {t:.1f} °C {in_range} ({thr}); wilgotność względna {rh3:.0f}% "
               f"i opady {rain3:.1f} mm w ostatnich 3 dniach.")
    return score, {"summary": summary, "factors": factors, "source": "dev_seed (syntetyczne)"}


def build(start: date = date(2024, 4, 1), end: date = date(2024, 8, 31), today: date | None = date(2024, 5, 15),
          fields=DEV_FIELDS, seed: int = 7, max_threats_per_crop: int | None = None) -> DevWorld:
    """Create (or replace) the synthetic world. Returns what was created."""
    from core.models import (Clock, CropClass, Field, Risk, Threat, WeatherDaily, WeatherForecastDaily,
                             WeatherGrid)

    wipe()
    rnd = random.Random(seed)
    crops = {
        CROP_WHEAT: CropClass.objects.get_or_create(code=CROP_WHEAT, defaults={"name": "Wheat"})[0],
        CROP_MAIZE: CropClass.objects.get_or_create(code=CROP_MAIZE, defaults={"name": "Maize"})[0],
    }
    # The engine's threats (engine/catalog.py, by code): the dev farm never invents codes of its own. It used to
    # create one per spreadsheet row ("wheat.czern_zboz", "maize.fusarium_ear_rot_2", "maize.eyespot_maize"), which
    # stayed next to the engine's 76 after a scenario switch (104 threats, a "bakterie" filter, duplicate names).
    import io

    from django.core.management import call_command
    call_command("engine_load_threats", stdout=io.StringIO())
    threats = {code: list(Threat.objects.filter(crop=crops[code]).order_by("code")[: max_threats_per_crop or None])
               for code in (CROP_WHEAT, CROP_MAIZE)}

    grid = WeatherGrid.objects.create(grid_id=f"{DEV_GRID_PREFIX}G1", lat=50.03, lon=19.95, time_zone="Europe/Warsaw")
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    weather = [_weather_for(d, rnd) for d in days]
    WeatherDaily.objects.bulk_create([WeatherDaily(grid=grid, date=d, **w) for d, w in zip(days, weather)])
    fc = []
    for i, issued in enumerate(days):
        for k in range(1, 8):
            if i + k < len(days):
                fc.append(WeatherForecastDaily(grid=grid, issued_on=issued, date=days[i + k], **weather[i + k]))
    WeatherForecastDaily.objects.bulk_create(fc, batch_size=2000)

    created_fields = []
    for name, crop_code, area, (lon, lat) in fields:
        d = 0.006
        geom = {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d / 1.6],
                                                    [lon, lat + d / 1.6], [lon, lat]]]}
        created_fields.append(Field.objects.create(
            name=name, geometry=geom, area_ha=area, centroid_lat=lat + d / 3.2, centroid_lon=lon + d / 2,
            weather_grid=grid, h3_cells=[], crop=crops[crop_code]))

    risks = []
    for f in created_fields:
        frnd = random.Random(f"{seed}-{f.name}")
        for t in threats[f.crop_id]:
            bias = frnd.uniform(-0.12, 0.12)  # fields differ a little
            for i, d in enumerate(days):
                score, expl = _risk(t, weather, i)
                risks.append(Risk(field=f, threat=t, date=d, score=round(max(0, min(1, score + bias)), 3),
                                  explanation=expl))
    Risk.objects.bulk_create(risks, batch_size=5000)

    if today is not None:
        Clock.objects.update_or_create(pk=1, defaults={"today": today})
    return DevWorld(today=today, fields=created_fields, threats=threats[CROP_WHEAT] + threats[CROP_MAIZE],
                    n_risks=len(risks))


@transaction.atomic
def wipe() -> int:
    """Delete everything the dev seed created (DEV_ grids and their fields/weather/risks, dev threats)."""
    from core.models import Field, Risk, Threat, WeatherDaily, WeatherForecastDaily, WeatherGrid

    grids = WeatherGrid.objects.filter(grid_id__startswith=DEV_GRID_PREFIX)
    fields = Field.objects.filter(weather_grid__in=grids)
    n = Risk.objects.filter(field__in=fields).delete()[0]
    n += fields.delete()[0]
    n += WeatherForecastDaily.objects.filter(grid__in=grids).delete()[0]
    n += WeatherDaily.objects.filter(grid__in=grids).delete()[0]
    n += grids.delete()[0]
    n += Threat.objects.filter(source=DEV_SOURCE, risks__isnull=True).delete()[0]
    return n
