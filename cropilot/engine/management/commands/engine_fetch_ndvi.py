"""python manage.py engine_fetch_ndvi [--season 2025] [--fields 1 2] — cache per-field Sentinel-2 NDVI (needs network)."""

from django.core.management.base import BaseCommand

from core import clock
from core.models import Field
from engine.satellite import fieldndvi
from engine.satellite.season import season_of


class Command(BaseCommand):
    help = "Fetch and cache each field's NDVI series for a season (used for growth stages and the crop check)."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int)
        parser.add_argument("--fields", type=int, nargs="*")

    def handle(self, *args, season=None, fields=None, **opts):
        season = season or season_of(clock.today())
        qs = Field.objects.all() if not fields else Field.objects.filter(id__in=fields)
        for f in qs:
            df = fieldndvi.fetch(f, season)
            n = 0 if df is None else len(df)
            anchors = fieldndvi.phenology_anchors(df, f.crop_id, season)
            self.stdout.write(f"{f.name}: {n} clear scenes; " + ("; ".join(a.what for a in anchors) or "no stage anchors"))
