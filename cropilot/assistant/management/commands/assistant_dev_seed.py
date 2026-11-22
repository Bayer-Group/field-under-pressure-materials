"""python manage.py assistant_dev_seed [--wipe] [--today 2024-05-15]

Synthetic demo farm for developing the assistant (5 fields, threats from the risk spreadsheet,
weather, toy risks with explanations). Only for local development until the platform's import and
the decision engine exist. Everything created is marked (DEV_ grid, source "dev_seed").
"""
from datetime import date

from django.core.management.base import BaseCommand

from assistant import devdata


class Command(BaseCommand):
    help = "Create (or replace) a synthetic demo farm for developing the assistant. Not the platform seed."

    def add_arguments(self, parser):
        parser.add_argument("--wipe", action="store_true", help="only delete the synthetic data")
        parser.add_argument("--today", type=date.fromisoformat, default=date(2024, 5, 15),
                            help="demo date to set in Clock (default 2024-05-15)")

    def handle(self, *args, **o):
        if o["wipe"]:
            self.stdout.write(f"Deleted {devdata.wipe()} synthetic rows.")
            return
        w = devdata.build(today=o["today"])
        self.stdout.write(self.style.SUCCESS(
            f"Synthetic farm ready: {len(w.fields)} fields, {len(w.threats)} threats, {w.n_risks} risk rows, "
            f"today = {w.today}."))
        for f in w.fields:
            self.stdout.write(f"  id={f.id:<4} {f.name:20} {f.crop.name:6} {f.area_ha} ha")
