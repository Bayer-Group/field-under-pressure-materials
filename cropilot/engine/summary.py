"""
One answer per field and day, from the Risk rows the engine wrote: how bad is it overall, what are the
top threats, what to do first, and which field to inspect first.

    from engine.summary import field_day, farm_ranking
    field_day(field_id, date)   # {"max_score", "level", "expected_loss", "top_threats", "actions", ...}
    farm_ranking(date)          # fields sorted by urgency, with the reason for each

expected_loss = 1 - prod(1 - score_i x severity_i): the share of the yield at risk if every threat
materialises as scored (threats treated as independent). Severities are team assumptions per threat
(engine/catalog.py). Pure read; nothing is stored.
"""

from __future__ import annotations

from datetime import date, timedelta

from core.models import Field, Risk
from engine.scoring import MEDIUM, level_of

LEVEL_WORD = {"high": "wysokie", "medium": "średnie", "low": "niskie"}

TOP_N = 3


def _summarise(field: Field, day: date, rows: list[Risk]) -> dict:
    items = []
    for r in rows:
        e = r.explanation or {}
        sev = float(e.get("severity", 0.1))
        items.append({"threat_code": r.threat.code, "name_pl": r.threat.name, "name_en": (e.get("threat") or {}).get("name_en"),
                      "score": r.score, "level": e.get("level", level_of(r.score)), "expected_loss": round(r.score * sev, 4),
                      "summary": e.get("summary"), "action": e.get("action"), "confidence": e.get("confidence")})
    keep = 1.0
    for it in items:
        keep *= 1 - it["expected_loss"]
    loss = 1 - keep
    items.sort(key=lambda x: (-x["expected_loss"], -x["score"]))
    max_score = max((it["score"] for it in items), default=0.0)
    actions = [{"threat_code": it["threat_code"], "type": it["action"]["type"], "text": it["action"]["text"],
                "threshold": it["action"].get("threshold"), "spray_window": it["action"].get("spray_window"),
                "expected_loss": it["expected_loss"]}
               for it in items if it["action"] and it["action"]["type"] in ("treat", "monitor")]
    top = items[:TOP_N]
    if not items:
        why = "Brak ocen ryzyka na ten dzień."
    elif max_score < MEDIUM:
        why = "Wszystkie zagrożenia niskie."
    else:
        why = "; ".join(f"{it['name_pl']}: {LEVEL_WORD[it['level']]} ({it['score']:.2f})" for it in top if it["score"] >= MEDIUM)
    bbch = next((((r.explanation or {}).get("growth_stage") or {}).get("bbch") for r in rows), None)
    return {
        "harvest": _harvest(field, day, bbch),
        "crop_check": _crop_check(field, day),
        "growth_stage": next(((r.explanation or {}).get("growth_stage") for r in rows), None),
        "field_id": field.id, "name": field.name, "date": day.isoformat(),
        "crop": {"code": field.crop_id, "name": getattr(field.crop, "name", None)},
        "max_score": round(max_score, 3), "level": level_of(max_score),
        "expected_loss": round(loss, 4), "expected_loss_pct": round(100 * loss, 1),
        "top_threats": top, "actions": actions, "why": why,
        "confidence": round(min((it["confidence"] or 1) for it in items), 2) if items else None,
    }


def field_day(field_id: int, day: date) -> dict:
    field = Field.objects.select_related("crop").get(id=field_id)
    rows = list(Risk.objects.filter(field=field, date=day).select_related("threat"))
    return _summarise(field, day, rows)


def farm_ranking(day: date) -> list[dict]:
    """All fields, most urgent first: expected loss, then the highest single score. A field without risk rows
    that day (no crop rules, no weather) is listed last with "Brak ocen ryzyka na ten dzień." instead of missing."""
    rows = list(Risk.objects.filter(date=day).select_related("threat", "field", "field__crop"))
    by_field: dict[int, list[Risk]] = {}
    for r in rows:
        by_field.setdefault(r.field_id, []).append(r)
    out = [_summarise(f, day, by_field.get(f.id, [])) for f in Field.objects.select_related("crop")]
    out.sort(key=lambda s: (-s["expected_loss"], -s["max_score"]))
    for i, s in enumerate(out, 1):
        s["rank"] = i
    return out


def _harvest(field: Field, day: date, bbch) -> dict | None:
    """Harvest / storage outlook once the crop is ripening (engine/harvest.py)."""
    if bbch is None or bbch < 83:
        return None
    import pandas as pd

    from core.models import WeatherForecastDaily
    from engine import features as F
    from engine.harvest import harvest_outlook

    from core import clock
    today = clock.today()
    issued = min(day, today)  # a day after today: the forecast known today, not one issued later
    # weather observed up to `day`, but never after today: a coming day continues with today's forecast
    recent = F.load_daily(field.weather_grid_id, day - timedelta(days=14), issued)
    if day > today:
        fc_days = F.load_forecast(field.weather_grid_id, today)
        if not fc_days.empty:
            fc_days = fc_days[(fc_days.index > pd.Timestamp(today)) & (fc_days.index <= pd.Timestamp(day))]
            recent = pd.concat([recent, fc_days]) if not recent.empty else fc_days
    recent = recent[recent.index >= pd.Timestamp(day - timedelta(days=14))] if not recent.empty else recent
    cols = ["date", "max_temperature", "min_temperature", "total_precipitation", "avg_relative_humidity"]
    fc = pd.DataFrame.from_records(WeatherForecastDaily.objects.current(as_of=issued)
                                   .filter(grid_id=field.weather_grid_id, date__gt=day)
                                   .order_by("date").values(*cols), columns=cols)
    fc = fc.set_index("date") if not fc.empty else None
    return harvest_outlook(field.crop_id, float(bbch), recent, fc)


def _crop_check(field: Field, day: date) -> dict | None:
    """Does the field's satellite curve up to `day` fit its crop? (cached NDVI only, no network)"""
    from engine.satellite import fieldndvi
    from engine.satellite.season import season_of

    from engine.phenology import crop_season
    season = crop_season(field.crop_id, day) if field.crop_id else season_of(day)
    out = fieldndvi.crop_check(fieldndvi.load(field, season), field.crop_id, season, day)
    try:
        from engine.cropmodel import CLASS_CODE, predict_field
        model = predict_field(field, season, day)
    except Exception as exc:  # the model is optional (not trained, no cache)
        model = {"error": str(exc)}
    if model and "crop" in model:
        agrees = model["crop"] == field.crop_id
        if out is None:
            out = {"consistent": agrees, "issues": [], "scenes_used": None, "text": ""}
        out["model"] = model
        name = model.get("label")
        out["text"] = (out["text"] + " " if out["text"] else "") + (
            f"Model upraw: {name} ({model['confidence']:.0%})" + ("." if agrees else " – inna niż uprawa pola; potwierdź uprawę."))
        out["consistent"] = out["consistent"] and (agrees or model["confidence"] < 0.6)
    return out
