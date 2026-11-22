"""
Date parameters of the platform API (docs/interfaces.md -> No data after the forecast).

Every endpoint that takes a date goes through these helpers, so none of them can return data dated
after today + FORECAST_DAYS:

    single_date(value)                     -> the date, default today; after the horizon: 400
    date_range(from_, to, default_from)    -> (from, to) actually used; `to` cut at the horizon

Errors are 400 {"detail": "..."}, like every other API error.
"""

import re
from datetime import date

from rest_framework import status
from rest_framework.exceptions import APIException

from core import clock


class InvalidDate(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid date."
    default_code = "invalid_date"


def parse_date(value, name: str) -> date:
    """`YYYY-MM-DD` -> date, otherwise 400 {"detail": "<name> must be YYYY-MM-DD"}. Only that form: Python's
    fromisoformat also takes ISO weeks ("2024-W22-1") and "20240601", which are not dates here."""
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidDate(f"{name} must be YYYY-MM-DD") from None


def _after_horizon(name: str) -> InvalidDate:
    return InvalidDate(f"{name} is after today + {clock.FORECAST_DAYS}")


def single_date(value: str | None, name: str = "date") -> date:
    """One day: default today; a day after today + FORECAST_DAYS is a 400."""
    if value in (None, ""):
        return clock.today()
    day = parse_date(value, name)
    if day > clock.horizon():
        raise _after_horizon(name)
    return day


def date_range(from_: str | None, to: str | None, default_from: date) -> tuple[date, date]:
    """
    A range of days. Defaults: `from` = default_from, `to` = today + FORECAST_DAYS. A later `to` is cut
    at today + FORECAST_DAYS (the caller reports the dates actually used). `from` after the horizon or
    after `to` is a 400.
    """
    last = clock.horizon()
    start = default_from if from_ in (None, "") else parse_date(from_, "from")
    end = last if to in (None, "") else min(parse_date(to, "to"), last)
    if start > last:
        raise _after_horizon("from")
    if start > end:
        if from_ in (None, ""):
            raise InvalidDate(f"to is before the default from ({start.isoformat()})")
        raise InvalidDate("from is after to")
    return start, end
