"""Initial, inspectable risk score for orchard analytics."""

import math
import re
from datetime import datetime
from statistics import mean

from ML.soil_moisture.open_meteo import DAY, UTC

WEIGHTS = {
    "moisture": 25,
    "ndvi": 20,
    "ph": 15,
    "texture": 10,
    "solar": 10,
    "temperature": 10,
    "forecast": 10,
}
FORECAST_WEIGHTS = {
    name: value for name, value in WEIGHTS.items() if name != "forecast"
}
FORECAST_WEIGHTS["moisture"] += WEIGHTS["forecast"]
MIN_COVERAGE = 55
TEXTURE_GROUPS = (
    ("heavy",) * 3 + ("medium",) * 5 + ("light", "medium", "light", "light")
)
MOISTURE_RANGES = {"light": (0.11, 0.30), "medium": (0.18, 0.38), "heavy": (0.23, 0.45)}
SOLAR_LEVELS = {"poor": 0, "moderate": 1, "good": 2, "excellent": 3}
LIGHT_REQUIREMENTS = {"very bright": 2, "clear skies": 3}


def number(value):
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return float(value)
    return None


def bounded(value, minimum, maximum):
    value = number(value)
    return value if value is not None and minimum <= value <= maximum else None


def outside_range(value, lower, upper, span):
    if value is None or lower is None or upper is None or lower > upper:
        return None
    return min(1.0, max(lower - value, value - upper, 0.0) / span)


def optimal(ecology, key):
    limits = (ecology.get(key) or {}).get("Optimal") or {}
    return number(limits.get("Min")), number(limits.get("Max"))


def texture_group(value):
    code = bounded(value, 1, 12)
    return (
        TEXTURE_GROUPS[int(code) - 1]
        if code is not None and code.is_integer()
        else None
    )


def future_moisture(observation, now, days_ahead):
    if observation.get("status") != "available":
        return []
    issued_at = observation.get("issued_at_utc")
    if isinstance(issued_at, datetime):
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=UTC)
    else:
        issued_at = now
    deadline = min(now, issued_at) + days_ahead * DAY
    result = []
    for item in observation.get("values", []):
        valid_at = item.get("valid_at_utc")
        if isinstance(valid_at, datetime):
            if valid_at.tzinfo is None:
                valid_at = valid_at.replace(tzinfo=UTC)
            value = bounded(item.get("soil_moisture_m3_m3"), 0, 1)
            if value is not None and now <= valid_at <= deadline:
                result.append(value)
    return result


def signals(inputs, ecology):
    texture = texture_group(inputs.get("texture"))
    moisture_limits = MOISTURE_RANGES.get(texture or "medium")
    allowed_textures = set(
        re.findall(
            r"\b(?:light|medium|heavy)\b", str(ecology.get("Soil texture", "")).lower()
        )
    )
    solar_level = SOLAR_LEVELS.get(inputs.get("solar"))
    light = ((ecology.get("Light intensity") or {}).get("Optimal") or {}).get("Min")
    light_required = LIGHT_REQUIREMENTS.get(str(light).lower())
    forecast = inputs.get("forecast") or []
    return {
        "moisture": outside_range(
            bounded(inputs.get("moisture"), 0, 1), *moisture_limits, 0.15
        ),
        "ndvi": outside_range(bounded(inputs.get("ndvi"), -1, 1), 0.45, 1, 0.40),
        "ph": outside_range(
            bounded(inputs.get("ph"), 0, 14), *optimal(ecology, "Soil pH"), 1.5
        ),
        "texture": float(texture not in allowed_textures)
        if texture and allowed_textures
        else None,
        "solar": max(light_required - solar_level, 0) / 3
        if solar_level is not None and light_required is not None
        else None,
        "temperature": outside_range(
            number(inputs.get("temperature")),
            *optimal(ecology, "Temperat. requir."),
            12,
        ),
        "forecast": max(
            outside_range(value, *moisture_limits, 0.15) for value in forecast
        )
        if forecast
        else None,
    }


def assess(inputs, profiles, *, dated=False):
    evaluations = (
        [signals(inputs, profile) for profile in profiles]
        if profiles
        else [signals(inputs, {})]
    )
    factors = []
    for name, weight in (FORECAST_WEIGHTS if dated else WEIGHTS).items():
        available = [result[name] for result in evaluations if result[name] is not None]
        factors.append(
            {
                "id": name,
                "weight": weight,
                "severity": round(100 * mean(available)) if available else None,
            }
        )
    covered = sum(item["weight"] for item in factors if item["severity"] is not None)
    score = (
        round(
            sum(
                item["severity"] * item["weight"]
                for item in factors
                if item["severity"] is not None
            )
            / covered
        )
        if covered >= MIN_COVERAGE
        else None
    )
    status = (
        "insufficient"
        if score is None
        else "high"
        if score >= 60
        else "watch"
        if score >= 30
        else "low"
    )
    return {
        "score": score,
        "status": status,
        "coverage": covered,
        "min_coverage": MIN_COVERAGE,
        "factors": factors,
    }
