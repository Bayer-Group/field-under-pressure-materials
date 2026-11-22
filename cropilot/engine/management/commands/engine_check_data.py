"""
python manage.py engine_check_data [--season 2025]

Checks that the database (and DATA_DIR) hold everything the engine needs, field by field, and says
exactly what is missing. The full specification is engine/README.md -> "Data to load".
Exit code 1 when a REQUIRED item is missing.
"""

from __future__ import annotations

import sys
from datetime import timedelta

from django.core.management.base import BaseCommand

from core import clock
from core.models import (Clock, CropClass, Field, FieldCropYear, SoilCell, Threat, WeatherDaily, WeatherForecastDaily,
                         WeatherGrid, WeatherHourly)
from engine.catalog import CROP_NAMES, RULES
from engine.features import LOOKBACK_DAYS
from engine.satellite.season import season_bounds, season_of


class Command(BaseCommand):
    help = "Check the data the decision engine needs and list what is missing."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, help="Season to check (default: the clock's).")

    def handle(self, *args, season=None, **opts):
        self.errors = 0
        ok = lambda m: self.stdout.write(self.style.SUCCESS("  OK       ") + m)
        warn = lambda m: self.stdout.write(self.style.WARNING("  OPTIONAL ") + m)

        def err(m):
            self.errors += 1
            self.stdout.write(self.style.ERROR("  MISSING  ") + m)

        self.stdout.write("Global")
        if not Clock.objects.exists():
            err("Clock: no row. Set the demo date (core.clock).")
            return self._end()
        today = clock.today()
        season = season or season_of(today)
        s0, s1 = season_bounds(season)
        need_from = s0 - timedelta(days=LOOKBACK_DAYS)
        need_to = today + timedelta(days=clock.FORECAST_DAYS)
        ok(f"Clock: today = {today}; season {season} = {s0} .. {s1} (maize to 31 Dec, sugar beet to 30 Nov, potato to 31 Oct); weather needed {need_from} .. {need_to}")
        for code in CROP_NAMES:
            (ok if CropClass.objects.filter(code=code).exists() else err)(f"CropClass {code}")
        codes = set(Threat.objects.values_list("code", flat=True))
        missing_threats = sorted(set(RULES) - codes)
        if missing_threats:
            err(f"Threat: {len(missing_threats)} of {len(RULES)} engine codes missing (run engine_load_threats): {', '.join(missing_threats[:5])}...")
        else:
            ok(f"Threat: all {len(RULES)} engine codes present")
        from engine.cropmodel import model_path
        (ok if model_path().exists() else warn)(f"crop model file {model_path()} (crop check only)")

        fields = list(Field.objects.select_related("weather_grid"))
        if not fields:
            err("Field: no fields.")
            return self._end()
        for f in fields:
            self.stdout.write(f"Field {f.id} '{f.name}' (crop {f.crop_id}, grid {f.weather_grid_id})")
            if f.crop_id not in CROP_NAMES:
                warn(f"crop {f.crop_id} has no engine rules: no risks for this field")
            if not f.geometry or not f.geometry.get("coordinates"):
                err("geometry: empty GeoJSON polygon")
            if not WeatherGrid.objects.filter(grid_id=f.weather_grid_id).exists():
                err("weather_grid: grid row missing")
            # daily weather
            days_needed = (need_to - need_from).days + 1
            dq = WeatherDaily.objects.filter(grid_id=f.weather_grid_id, date__range=(need_from, need_to))
            n = dq.exclude(avg_temperature=None).count()
            (ok if n >= days_needed - 2 else err)(f"WeatherDaily: {n} of {days_needed} days with avg_temperature ({need_from} .. {need_to})")
            rain = dq.exclude(total_precipitation=None).count() + dq.filter(total_precipitation=None).exclude(imerg_total_precipitation=None).count()
            (ok if rain >= 0.9 * days_needed else err)(f"WeatherDaily precipitation (total_precipitation or imerg_total_precipitation): {rain} days")
            for col in ("avg_relative_humidity", "min_temperature", "max_temperature", "eto", "avg_soil_temperature_level_1",
                        "avg_soil_moisture_level_1", "min_soil_temperature_level_1", "avg_snow_depth", "avg_wind_speed"):
                m = dq.exclude(**{col: None}).count()
                (ok if m >= 0.9 * days_needed else err)(f"WeatherDaily.{col}: {m} days")
            # hourly weather
            hq = WeatherHourly.objects.filter(grid_id=f.weather_grid_id, date__range=(need_from, need_to))
            h = hq.exclude(temperature=None).exclude(relative_humidity=None).count()
            (ok if h >= 0.9 * 24 * days_needed else warn)(f"WeatherHourly: {h} of {24 * days_needed} hours with temperature + relative_humidity (else estimated from daily, confidence x0.7)")
            hr = hq.exclude(precipitation=None).count() + hq.filter(precipitation=None).exclude(imerg_precipitation=None).count()
            (ok if hr >= 0.9 * h else warn)(f"WeatherHourly precipitation (precipitation or imerg_precipitation): {hr} hours")
            # forecast
            fc = WeatherForecastDaily.objects.filter(grid_id=f.weather_grid_id, issued_on=today).count()
            (ok if fc == clock.FORECAST_DAYS else err)(f"WeatherForecastDaily issued {today}: {fc} of {clock.FORECAST_DAYS} days")
            issued_days = WeatherForecastDaily.objects.filter(grid_id=f.weather_grid_id, issued_on__range=(s0, need_to)).values("issued_on").distinct().count()
            (ok if issued_days >= 0.9 * (need_to - s0).days else warn)(f"WeatherForecastDaily: issued on {issued_days} days of the season (spraying window / harvest dry days on each day)")
            # crop history
            years = sorted(set(FieldCropYear.objects.filter(field=f).values_list("year", flat=True)))
            (ok if season - 1 in years else err)(f"FieldCropYear: years {years} (needs at least {season - 1}; ideally {season - 5} .. {season - 1})")
            # soil
            cells = SoilCell.objects.filter(h3_index_10__in=f.h3_cells).exclude(clay=None).count()
            (ok if cells else warn)(f"SoilCell: {cells} of {len(f.h3_cells)} h3_cells with clay (heavy-soil multiplier only)")
            # satellite cache
            from engine.satellite import fieldndvi
            ser = fieldndvi.load(f, season)
            (ok if ser is not None else warn)(f"satellite cache {fieldndvi.path_for(f, season).name}: "
                                              + (f"{len(ser)} scenes" if ser is not None else "missing (run engine_fetch_ndvi); stage from degree days only"))
        self._end()

    def _end(self):
        if self.errors:
            self.stdout.write(self.style.ERROR(f"{self.errors} required item(s) missing."))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS("Everything the engine requires is present."))
