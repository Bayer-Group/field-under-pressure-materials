"""Spray window: pure functions, no database and no I/O.

Rules: the team's note "Okno oprysku: jak to wyliczamy" (version 3, sections 4-6), docs/curated_layer_contract.md (section 3,
"Spray windows") and config/spray_window.toml. The result is an assessment of the weather in the next hours: "consider a spray
in this window", never "spray". It does not check the product, its label or its approval.

Input: the septoria assessment of the day (the signal, section 4 of the note) and the hourly weather of the next 72 hours of the
grid cell of a crop area (section 5). Output: a dict with the status, up to three ranked windows and the check of every hour.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

HOUR = timedelta(hours=1)

# Status of a crop area, first match wins: no_signal > no_forecast > window_now > window_later > no_window.
STATUSES = ("no_signal", "no_forecast", "window_now", "window_later", "no_window")


@dataclass(frozen=True)
class Rules:
    """Spray window rules, built from config/spray_window.toml (see Rules.from_config)."""
    model_version: str
    horizon_hours: int
    min_window_hours: int
    max_windows: int
    indicative_after_hours: int
    wind_max_ms: float
    gust_max_ms: float
    temperature_min_c: float
    temperature_max_c: float
    precipitation_max_mm: float
    confident_margin_ms: float
    source_label: str
    origin: dict
    texts: dict

    @classmethod
    def from_config(cls, cfg: dict) -> "Rules":
        """cfg is the whole parsed TOML file (the dict with the key "spray_window")."""
        s, lim = cfg["spray_window"], cfg["spray_window"]["limits"]
        return cls(
            model_version=s["model_version"], horizon_hours=s["horizon_hours"], min_window_hours=s["min_window_hours"],
            max_windows=s["max_windows"], indicative_after_hours=s["indicative_after_hours"],
            wind_max_ms=lim["wind_max_ms"], gust_max_ms=lim["wind_max_ms"] + lim["gust_over_wind_max_ms"],
            temperature_min_c=lim["temperature_min_c"], temperature_max_c=lim["temperature_max_c"],
            precipitation_max_mm=lim["precipitation_max_mm"], confident_margin_ms=lim["confident_margin_ms"],
            source_label=s["source_label"], origin=dict(s.get("origin", {})), texts=dict(s.get("texts", {})),
        )


@dataclass(frozen=True)
class Hour:
    """Weather of one hour (shown local time of the start of the hour). None = missing, never 'fine'."""
    time: datetime
    wind_ms: Optional[float]
    gust_ms: Optional[float]
    temperature_c: Optional[float]
    precipitation_mm: Optional[float]


def check_hour(h: Hour, rules: Rules, work_hours: Optional[tuple[int, int]] = None) -> dict:
    """One hour against every condition (note 5.1). ok is True only when all pass, None when a value is missing (an unknown hour
    breaks a window, it is never counted as good). work_hours (from, to) is the farmer's preference (note 5.2): it can only
    exclude hours, it never relaxes a limit."""
    failed, missing = [], []
    for name, value in (("wind", h.wind_ms), ("gust", h.gust_ms), ("temperature", h.temperature_c),
                        ("precipitation", h.precipitation_mm)):
        if value is None:
            missing.append(name)
    if h.wind_ms is not None and h.wind_ms > rules.wind_max_ms:
        failed.append("wind")
    if h.gust_ms is not None and h.gust_ms > rules.gust_max_ms:
        failed.append("gust")
    if h.temperature_c is not None and h.temperature_c < rules.temperature_min_c:
        failed.append("temperature_low")
    if h.temperature_c is not None and h.temperature_c > rules.temperature_max_c:
        failed.append("temperature_high")
    if h.precipitation_mm is not None and h.precipitation_mm > rules.precipitation_max_mm:
        failed.append("rain")
    if work_hours is not None and not (work_hours[0] <= h.time.hour < work_hours[1]):
        failed.append("outside_work_hours")
    ok = False if failed else (None if missing else True)
    return {"time": h.time, "ok": ok, "failed": failed, "missing": missing, "wind_ms": _round(h.wind_ms, 2),
            "gust_ms": _round(h.gust_ms, 2), "temperature_c": _round(h.temperature_c, 1),
            "precipitation_mm": _round(h.precipitation_mm, 2)}


def _round(v: Optional[float], digits: int) -> Optional[float]:
    return None if v is None else round(v, digits)


def find_windows(checked: Sequence[dict], rules: Rules, now: datetime) -> list[dict]:
    """Runs of consecutive good hours of at least min_window_hours (note 5.3); shorter runs are dropped."""
    out, run = [], []
    for c in list(checked) + [None]:                       # None closes the last run
        if c is not None and c["ok"] is True and (not run or c["time"] - run[-1]["time"] == HOUR):
            run.append(c)
            continue
        if len(run) >= rules.min_window_hours:
            out.append(_window(run, rules, now))
        run = [c] if (c is not None and c["ok"] is True) else []
    return out


def _window(run: Sequence[dict], rules: Rules, now: datetime) -> dict:
    wind = max(c["wind_ms"] for c in run)
    gust = max(c["gust_ms"] for c in run)
    t_min, t_max = min(c["temperature_c"] for c in run), max(c["temperature_c"] for c in run)
    margin = round(rules.wind_max_ms - wind, 1)
    start, end = run[0]["time"], run[-1]["time"] + HOUR
    confident = margin >= rules.confident_margin_ms
    indicative = start - now >= timedelta(hours=rules.indicative_after_hours)
    reason = (f"wind up to {wind:.1f} m/s (gusts {gust:.1f}), {t_min:.1f}-{t_max:.1f} °C, no rain for {len(run)} h, "
              f"margin below the wind limit {margin:.1f} m/s")
    return {"start": start, "end": end, "hours": len(run), "wind_max_ms": round(wind, 1), "gust_max_ms": round(gust, 1),
            "temperature_min_c": round(t_min, 1), "temperature_max_c": round(t_max, 1), "wind_margin_ms": margin,
            "confidence": "confident" if confident else "borderline", "indicative": indicative, "reason": reason}


def rank(windows: Sequence[dict], rules: Rules) -> list[dict]:
    """Up to max_windows (note 6): windows with the wind margin first, then the earlier one (at high risk the earlier window is
    preferred, the infection goes on). The farmer's working hours are already applied in check_hour."""
    ordered = sorted(windows, key=lambda w: (w["confidence"] != "confident", w["start"]))[: rules.max_windows]
    return [dict(w, rank=i + 1) for i, w in enumerate(ordered)]


def signal(assessment: Optional[dict]) -> tuple[bool, str]:
    """Is there a signal to consider a spray (note 4)? It is the conditions_met flag of the septoria assessment of the day:
    class high, growth zone B or C and not protected. Returns (signal, reason); the reason says why not."""
    if not assessment or assessment.get("status") is None:
        return False, "no_assessment"
    if assessment.get("conditions_met"):
        return True, "conditions_met"
    status = assessment.get("status")
    if status in ("stage_unknown", "out_of_window", "insufficient_data", "protected"):
        return False, status
    if assessment.get("risk_class") != "high":
        return False, "risk_not_high"
    return False, "zone_not_b_or_c"                       # high and ok, but the growth zone is A or unknown


def assess(assessment: Optional[dict], hours: Sequence[Hour], now: datetime, rules: Rules,
           work_hours: Optional[tuple[int, int]] = None) -> dict:
    """The spray window of one crop area at `now` (shown local time, the start of the current hour).

    Without a signal no window is proposed (note 4); the checked hours are still returned (they describe the weather)."""
    has_signal, why = signal(assessment)
    checked = [check_hour(h, rules, work_hours) for h in hours]
    known = sum(c["ok"] is not None for c in checked)
    if not has_signal:
        status, windows = "no_signal", []
    elif known == 0:
        status, windows = "no_forecast", []
    else:
        windows = rank(find_windows(checked, rules, now), rules)
        if any(w["start"] <= now < w["end"] for w in windows):
            status = "window_now"
        elif windows:
            status = "window_later"
        else:
            status = "no_window"
    good_now = bool(checked) and checked[0]["time"] == now and checked[0]["ok"] is True
    first = min(windows, key=lambda w: w["start"]) if windows else None
    return {
        "status": status,
        "signal": has_signal,
        "signal_reason": why,
        "weather_ok_now": good_now,
        "next_window_start": first["start"] if first else None,
        "next_window_end": first["end"] if first else None,
        "windows": windows,
        "hours": checked,
        "coverage": round(known / rules.horizon_hours, 3),
        "model_version": rules.model_version,
    }
