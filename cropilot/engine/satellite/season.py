"""
The agricultural season and its calendar grid.

A season is named after its harvest year and runs 1 September (year - 1) to 31 August (year): winter
crops are sown in autumn, so their whole life fits in one season. The grid splits it into 24
half-month slots (1st-15th, 16th-end). A slot holds the median NDVI of the clear observations in it;
slots after "today" are left empty (NaN), so one model serves every day of the season.
"""

from __future__ import annotations

from datetime import date

import numpy as np

N_SLOTS = 24
SLOT_NAMES = [f"{m:02d}{'a' if half == 0 else 'b'}" for m in (9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8) for half in (0, 1)]


def season_of(day: date) -> int:
    """The season (harvest year) a day belongs to."""
    return day.year + 1 if day.month >= 9 else day.year


def season_bounds(season: int) -> tuple[date, date]:
    return date(season - 1, 9, 1), date(season, 8, 31)


def slot_of(day: date) -> int:
    """0..23: index of the half-month slot of the day within its season."""
    month_idx = (day.month - 9) % 12
    return month_idx * 2 + (0 if day.day <= 15 else 1)


def slot_end(season: int, slot: int) -> date:
    """Last day of a slot (a slot counts as known once today >= its last day)."""
    month_idx, half = divmod(slot, 2)
    month = (9 + month_idx - 1) % 12 + 1
    year = season - 1 if month >= 9 else season
    if half == 0:
        return date(year, month, 15)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def known_slots(season: int, today: date) -> np.ndarray:
    """Boolean [24]: which slots are complete as of today."""
    return np.array([slot_end(season, s) <= today for s in range(N_SLOTS)])


def composite(dates, ndvi: np.ndarray, season: int) -> np.ndarray:
    """
    Per-pixel half-month medians. dates: ISO strings or dates of the scenes; ndvi: [n, ...].
    Returns [24, ...] float32, NaN where a slot has no clear observation.
    """
    days = [d if isinstance(d, date) else date.fromisoformat(str(d)) for d in dates]
    start, end = season_bounds(season)
    out = np.full((N_SLOTS,) + ndvi.shape[1:], np.nan, dtype="float32")
    slots = np.array([slot_of(d) if start <= d <= end else -1 for d in days])
    for s in range(N_SLOTS):
        sel = slots == s
        if sel.any():
            with np.errstate(all="ignore"), _quiet():
                out[s] = np.nanmedian(ndvi[sel], axis=0)
    return out


class _quiet:
    """Silence numpy's 'All-NaN slice' RuntimeWarning for fully cloudy pixels."""

    def __enter__(self):
        import warnings
        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore", RuntimeWarning)

    def __exit__(self, *exc):
        self._w.__exit__(*exc)
