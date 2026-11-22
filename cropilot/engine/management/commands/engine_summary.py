"""python manage.py engine_summary [--date 2025-06-05] [--json]  — fields ranked by urgency (default: today)."""

import json
from datetime import date

from django.core.management.base import BaseCommand

from core import clock
from engine.summary import farm_ranking


class Command(BaseCommand):
    help = "Rank the farm's fields by urgency for one day, with the reasons."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=date.fromisoformat)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, date=None, json=False, **opts):
        day = date or clock.today()
        ranking = farm_ranking(day)
        if json:
            import json as _json
            self.stdout.write(_json.dumps(ranking, ensure_ascii=False, indent=1, default=str))
            return
        self.stdout.write(f"Fields by urgency on {day}:")
        for s in ranking:
            self.stdout.write(f"{s['rank']}. {s['name']} ({s['crop']['name']}): level {s['level']}, max {s['max_score']:.2f}, "
                              f"yield at risk {s['expected_loss_pct']:.1f} % - {s['why']}")
            for a in s["actions"][:2]:
                win = a["spray_window"]["date"] if a.get("spray_window") else None
                self.stdout.write(f"     -> {a['type']}: {a['threat_code']}" + (f" (spraying window {win})" if win else ""))
