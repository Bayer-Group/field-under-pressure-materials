"""
The demo's current date. The demo replays a past season, so never use date.today():

    from core import clock
    today = clock.today()
    last_day = clock.horizon()      # today + FORECAST_DAYS: nothing later is ever shown
    clock.set_today(new_date)       # moves the demo date and recomputes the risks that change
    clock.date_limits()             # (first, last) demo date that has weather, or (None, None)
"""

from datetime import date, timedelta

# How many days ahead the forecast (and the "coming days" risks) reach.
FORECAST_DAYS = 7


class ClockNotSetError(RuntimeError):
    """The Clock row is missing: set the demo date in /admin/ or run the seed."""


def today() -> date:
    """The demo's current date, from the single Clock row. Raises ClockNotSetError if it is missing."""
    from core.models import Clock  # imported here: core.models imports this module

    try:
        return Clock.objects.values_list("today", flat=True).get(pk=1)
    except Clock.DoesNotExist:
        raise ClockNotSetError(
            "The Clock row is missing. Set the demo date in /admin/ (Platform > Clock) or run the seed."
        ) from None


def horizon(as_of: date | None = None) -> date:
    """The last day anything may be shown for: today + FORECAST_DAYS (the end of the forecast)."""
    return (as_of or today()) + timedelta(days=FORECAST_DAYS)


def date_limits() -> tuple[date | None, date | None]:
    """
    The demo dates that make sense: the days a forecast was issued on (the scenario's window, previous season
    included), else the days with observed weather; (None, None) with no weather at all. PUT /api/clock/
    refuses dates outside them (a far jump recomputes whole seasons; a date without weather has no risks).
    """
    from django.db.models import Max, Min

    from core.models import WeatherDaily, WeatherForecastDaily

    fc = WeatherForecastDaily.objects.aggregate(lo=Min("issued_on"), hi=Max("issued_on"))
    if fc["lo"] is not None:
        return fc["lo"], fc["hi"]
    obs = WeatherDaily.objects.aggregate(lo=Min("date"), hi=Max("date"))
    return obs["lo"], obs["hi"]


def set_today(new: date) -> date:
    """
    Moves the demo date to `new` (creates the Clock row if it is missing) and lets the decision engine
    recompute the days that change (engine.clock_moved). The engine has no signal on Clock, so every
    date change goes through here: PUT /api/clock/ and the admin's clock page. Returns the old date
    (None if there was no row).

    Saving and recomputing happen in one transaction: if the engine fails, the date stays where it was.
    """
    from django.db import transaction

    from core.models import Clock
    from engine import clock_moved

    with transaction.atomic():
        old = Clock.objects.select_for_update().filter(pk=1).values_list("today", flat=True).first()
        Clock(today=new).save()
        if old is not None and old != new:
            clock_moved(old, new)
    return old
