"""
python manage.py engine_precompute_dates [--from 2024-05-20] [--to 2024-06-30]

Computes ahead what moving the demo date needs (engine.precompute_dates), so that the date control's
arrows copy ready rows instead of computing them. Default range: the Clock's date - 7 ... + 30. Writes only
the engine's cache (engine.RiskSnapshot); Risk itself is not touched. Run it after the seed or a scenario switch.
"""

from datetime import date
from time import perf_counter

from django.core.management.base import BaseCommand

from engine import precompute_dates


class Command(BaseCommand):
    help = "Precompute the risks of a range of demo dates, so moving the date copies instead of computing."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="first", type=date.fromisoformat, default=None)
        parser.add_argument("--to", dest="last", type=date.fromisoformat, default=None)

    def handle(self, *args, first=None, last=None, **opts):
        t = perf_counter()
        n = precompute_dates(first, last)
        self.stdout.write(self.style.SUCCESS(f"{n} snapshot bundles written in {perf_counter() - t:.0f} s."))
