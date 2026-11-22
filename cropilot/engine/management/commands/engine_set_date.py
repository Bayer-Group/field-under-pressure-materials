"""python manage.py engine_set_date 2025-06-20

Moves the demo date and recomputes the days that change, through core.clock.set_today() like
PUT /api/clock/ and the admin's clock page: the date and the risks change in one transaction, so if the
engine fails the date stays where it was. Creates the Clock row if it is missing.
"""

import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from core import clock


def _day(value: str) -> date:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise CommandError(f"Date must be YYYY-MM-DD, got {value!r}") from None


class Command(BaseCommand):
    help = "Set the demo date (Clock) and recompute the risks of the days that change."

    def add_arguments(self, parser):
        parser.add_argument("date", type=str)

    def handle(self, *args, date=None, **opts):
        new = _day(date)
        old = clock.set_today(new)
        self.stdout.write(self.style.SUCCESS(f"Clock {old or '(not set)'} -> {new}."))
