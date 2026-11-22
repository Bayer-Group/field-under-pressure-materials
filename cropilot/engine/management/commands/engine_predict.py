"""python manage.py engine_predict [--fields 1 2] [--start 2025-03-01] [--end 2025-06-30]"""

from datetime import date

from django.core.management.base import BaseCommand

from engine import precompute_season, predict


class Command(BaseCommand):
    help = ("Compute risks (default: all fields, 1 September up to the later of today + 7 and the last day already stored) "
            "and overwrite them in Risk. --season precomputes the demo season (previous season first).")

    def add_arguments(self, parser):
        parser.add_argument("--fields", type=int, nargs="*", help="Field ids (default: all).")
        parser.add_argument("--start", type=date.fromisoformat, help="First day (default: 1 September of the season).")
        parser.add_argument("--end", type=date.fromisoformat, help="Last day (default: the later of today + 7 and the last stored day).")
        parser.add_argument("--season", action="store_true", help="Precompute the whole demo season (engine.precompute_season).")

    def handle(self, *args, fields=None, start=None, end=None, season=False, **opts):
        n = precompute_season() if season else predict(field_ids=fields, start=start, end=end)
        self.stdout.write(self.style.SUCCESS(f"{int(n)} risk rows written for fields {n.field_ids}."))
