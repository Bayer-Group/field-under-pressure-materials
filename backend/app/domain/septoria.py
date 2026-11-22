"""Septoria (wheat) condition class: pure functions, no database and no I/O.

Rules: docs/curated_layer_contract.md (sections 1-4) and config/septoria.toml. The result states that conditions are favourable
to the disease in a susceptible growth stage; it is not an instruction to spray.

Input per crop area and local day: the wet flags of the window (72 hours ending at the last hour of the day, oldest first,
None = hour missing), the growth stage inputs and the date of the last spray. Output: a dict with the columns of
curated.risk_assessment (without keys and timestamps).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Sequence

Wet = Optional[bool]


@dataclass(frozen=True)
class Rules:
    """Septoria rules, built from the [septoria] table of config/septoria.toml (see Rules.from_config)."""
    model_version: str
    window_hours: int
    threshold_medium: int
    threshold_high: int
    min_coverage: float
    max_gap_hours: int
    bbch_min: int
    bbch_max: int
    calendar_from: str            # "MM-DD"
    calendar_to: str
    zone_b_from: float
    zone_c_from: float

    @classmethod
    def from_config(cls, cfg: dict) -> "Rules":
        """cfg is the whole parsed TOML file (the dict with the key "septoria")."""
        s, g = cfg["septoria"], cfg["septoria"]["growth_stage"]
        return cls(
            model_version=s["model_version"], window_hours=s["window_hours"],
            threshold_medium=s["thresholds"]["medium"], threshold_high=s["thresholds"]["high"],
            min_coverage=s["min_coverage"], max_gap_hours=s["max_gap_hours"],
            bbch_min=g["bbch_window"][0], bbch_max=g["bbch_window"][1],
            calendar_from=g["calendar_window"][0], calendar_to=g["calendar_window"][1],
            zone_b_from=g["zone_b_from"], zone_c_from=g["zone_c_from"],
        )


def wet_hour(rh: Optional[float], precipitation: Optional[float], rh_min: float, precipitation_min: float) -> Wet:
    """Wet hour: relative humidity >= rh_min or precipitation > precipitation_min. None when both values are missing.
    One missing value does not hide a wet hour proven by the other one."""
    if (rh is not None and rh >= rh_min) or (precipitation is not None and precipitation > precipitation_min):
        return True
    if rh is None and precipitation is None:
        return None
    if rh is None or precipitation is None:
        return None            # the missing value could have made the hour wet
    return False


def longest_run(flags: Sequence[Wet], missing_as: bool) -> int:
    """Longest run of consecutive True hours; a missing hour (None) counts as `missing_as`."""
    best = cur = 0
    for f in flags:
        if (missing_as if f is None else f):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def longest_gap(flags: Sequence[Wet]) -> int:
    """Longest run of consecutive missing hours."""
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f is None else 0
        best = max(best, cur)
    return best


def classify(h: int, rules: Rules) -> str:
    if h >= rules.threshold_high:
        return "high"
    if h >= rules.threshold_medium:
        return "medium"
    return "low"


def risk_index(h: Optional[float], rules: Rules) -> Optional[float]:
    """H on a continuous 0-1 scale aligned with the classes (issue #49): 0 at 0 h, 0.5 at the medium threshold, 1 at the high
    threshold and above, linear in between. So index < 0.5 is low, 0.5 to < 1 is medium and 1 is high, the same as classify(h)
    for every whole H. It adds no rule: it only keeps the information the three classes round away (for a smooth map). H may be a
    fraction of an hour (a pixel of the interpolated surface). The index is capped at the high threshold: to see how far above it
    the hours are, use the hours themselves."""
    if h is None:
        return None
    lo, hi = rules.threshold_medium, rules.threshold_high
    if h >= hi:
        return 1.0
    if h >= lo:
        return round(0.5 + 0.5 * (h - lo) / (hi - lo), 4) if hi > lo else 1.0
    return round(0.5 * max(h, 0) / lo, 4) if lo > 0 else 0.0


def zone(gdd: Optional[float], rules: Rules) -> Optional[str]:
    """A / B / C from the degree-days since the vegetation resumed; None when unknown."""
    if gdd is None:
        return None
    return "A" if gdd < rules.zone_b_from else ("B" if gdd < rules.zone_c_from else "C")


def growth_stage(day: date, gdd: Optional[float], bbch_override: Optional[int], rules: Rules):
    """(zone, source, in_window). Source: override (farmer's BBCH), estimated (degree-days), calendar (fallback), None (unknown).
    in_window is None when the stage cannot be judged."""
    if bbch_override is not None:
        return zone(gdd, rules), "override", rules.bbch_min <= bbch_override <= rules.bbch_max
    z = zone(gdd, rules)
    if z is not None:
        return z, "estimated", z in ("B", "C")
    md = f"{day.month:02d}-{day.day:02d}"
    return None, "calendar", rules.calendar_from <= md <= rules.calendar_to


def protected_until(spray_date: Optional[date], protection_days: Optional[int]) -> Optional[date]:
    if spray_date is None or protection_days is None:
        return None
    return spray_date + timedelta(days=protection_days)


def assess(day: date, flags: Sequence[Wet], *, gdd: Optional[float], bbch_override: Optional[int],
           winter_crop: bool, spray_date: Optional[date], protection_days: Optional[int], rules: Rules) -> dict:
    """The row of curated.risk_assessment for one crop area and one local day.

    Status, first match wins: stage_unknown (not winter wheat) > out_of_window > protected > insufficient_data
    (coverage below min_coverage, or an ambiguous class with a gap longer than max_gap_hours) > uncertain (the class
    depends on missing hours) > ok."""
    n = rules.window_hours
    window = list(flags)[-n:]
    valid = sum(f is not None for f in window)
    coverage = valid / n
    h_low, h_high = longest_run(window, False), longest_run(window, True)
    c_low, c_high = classify(h_low, rules), classify(h_high, rules)
    zn, source, in_window = growth_stage(day, gdd, bbch_override, rules) if winter_crop else (None, None, None)
    until = protected_until(spray_date, protection_days)
    is_protected = until is not None and day <= until
    gap = longest_gap(window)

    reasons = {"h_hours": h_low, "window_hours": n, "coverage": round(coverage, 3), "longest_gap_hours": gap}
    if not winter_crop:
        status = "stage_unknown"
    elif in_window is False:
        status = "out_of_window"
    elif in_window is None:
        status = "stage_unknown"
    elif is_protected:
        status = "protected"
    elif coverage < rules.min_coverage:
        status = "insufficient_data"
    elif c_low != c_high:
        status = "uncertain" if gap <= rules.max_gap_hours else "insufficient_data"
    else:
        status = "ok"
    reasons["status"] = status

    risk_class = None if status in ("stage_unknown", "out_of_window", "insufficient_data") else c_low
    conditions = status == "ok" and risk_class == "high" and zn in ("B", "C")
    return {
        "h_hours": h_low, "h_low": h_low, "h_high": h_high, "risk_class": risk_class, "status": status,
        "threshold_medium": rules.threshold_medium, "threshold_high": rules.threshold_high,
        "coverage": coverage, "protected_until": until, "growth_stage_zone": zn, "growth_stage_source": source,
        "gdd_since_resumption": gdd, "conditions_met": conditions, "reasons": reasons,
        "model_version": rules.model_version,
        "input_hash": input_hash(day, window, gdd, bbch_override, winter_crop, until, rules),
    }


def input_hash(day, window, gdd, bbch_override, winter_crop, until, rules: Rules) -> str:
    """Stable fingerprint of everything the result depends on (to detect stale rows)."""
    payload = [day.isoformat(), [None if f is None else int(f) for f in window], gdd, bbch_override, winter_crop,
               until.isoformat() if until else None, rules.__dict__]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
