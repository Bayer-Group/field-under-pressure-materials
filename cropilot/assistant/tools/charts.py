"""
Chart tools: Vega-Lite v5 specs (proposed format, see docs/archive/INTERFACE_PROPOSALS.md) + a `summary` computed
in code (max, day of max, level today, trend). The model only comments on the summary; it never
computes chart numbers.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field as PField

from assistant import domain
from .platform import _field, _range, _risk_series, _unit, get_farm_risk_summary, season_today
from .registry import ToolError, register

VEGA = "https://vega.github.io/schema/vega-lite/v5.json"
WEATHER_LABELS = {
    "total_precipitation": "Opady", "avg_temperature": "Średnia temperatura",
    "min_temperature": "Temperatura minimalna", "max_temperature": "Temperatura maksymalna",
    "avg_relative_humidity": "Wilgotność względna", "max_relative_humidity": "Maks. wilgotność względna",
}
LEVEL_COLORS = {"niskie": "#4caf50", "średnie": "#ff9800", "wysokie": "#e53935", "brak danych": "#9e9e9e"}


def _today_rule(today: dt.date) -> list[dict]:
    # A DateTime, not an ISO string: Vega-Lite does not parse a string datum, so the line got no x and
    # was not drawn. utc: the data's "YYYY-MM-DD" strings are read as UTC midnight. One row of data,
    # otherwise the layer inherits every data row and draws the same line and label once per row.
    x = {"datum": {"year": today.year, "month": today.month, "date": today.day, "utc": True}, "type": "temporal"}
    one_row = {"values": [{}]}
    return [
        {"data": one_row, "mark": {"type": "rule", "color": "#555", "strokeDash": [4, 3]}, "encoding": {"x": x}},
        {"data": one_row, "mark": {"type": "text", "align": "left", "dx": 3, "dy": -6, "color": "#555"},
         "encoding": {"x": x, "y": {"value": 0}, "text": {"value": f"dziś ({today:%d.%m})"}}},
    ]


def _level_rules() -> list[dict]:
    return [{"mark": {"type": "rule", "color": "#bbb", "strokeDash": [2, 2]},
             "encoding": {"y": {"datum": upper}}} for upper, _, _ in domain.LEVELS[:-1]]


def _series_summary(rows, today: dt.date) -> dict:
    past = [r for r in rows if r.date <= today]
    now = past[-1] if past else None
    peak = max(rows, key=lambda r: r.score)
    return {"max": round(peak.score, 2), "max_date": peak.date, "max_level": domain.level(peak.score)[1],
            "today_score": round(now.score, 2) if now else None,
            "today_level": domain.level(now.score)[1] if now else "brak danych",
            "trend": domain.trend([r.score for r in past]), "in_forecast": peak.date > today}


class RiskTimelineIn(BaseModel):
    field_ids: list[int] = PField(min_length=1, max_length=6)
    threat: str = PField(description="Kod lub nazwa zagrożenia.")
    date_from: dt.date | None = PField(None, description="Domyślnie dziś − 14 dni.")
    date_to: dt.date | None = PField(None, description="Domyślnie dziś + 7 dni.")


@register("chart_risk_timeline", """
Wykres przebiegu ryzyka jednego zagrożenia na wybranych polach (linia ciągła: dotychczas,
przerywana: prognoza; pionowa linia „dziś”). Zwraca specyfikację Vega-Lite i `summary` per pole
(maksimum, dzień maksimum, poziom dziś, trend) — komentuj tylko liczby z `summary`.
""", RiskTimelineIn)
def chart_risk_timeline(field_ids: list[int], threat: str, date_from=None, date_to=None) -> dict:
    today = season_today()
    a, b, _ = _range(date_from, date_to, back=14, ahead=7)
    fields = [_field(i) for i in field_ids]
    t = domain.threat_by_code_or_name(threat, fields[0].crop_id)
    if t is None:
        raise ToolError(f"Nie znam zagrożenia „{threat}” dla uprawy {domain.crop_pl(fields[0].crop_id)}.")
    values, summary = [], {}
    for f in fields:
        rows = _risk_series(f, a, b, t.code).get(t, [])
        if not rows:
            continue
        for r in rows:
            values.append({"date": r.date.isoformat(), "pole": f.name, "ryzyko": round(r.score, 3),
                           "okres": "prognoza" if r.date > today else "dotychczas"})
        summary[f.name] = _series_summary(rows, today)
    if not values:
        raise ToolError(f"Brak danych ryzyka „{t.name}” dla wybranych pól w zakresie {a} – {b}.")
    spec = {
        "$schema": VEGA, "width": "container", "height": 260,
        # two lines, from the chart's left edge: in one centred line it was cut off in the chat's width
        "title": {"text": f"Ryzyko: {t.name}", "anchor": "start", "frame": "bounds",
                  "subtitle": [f"{a:%d.%m} – {b:%d.%m.%Y}", "poziomy: niskie < 0,33 ≤ średnie < 0,66 ≤ wysokie"]},
        "data": {"values": values},
        "layer": [
            {"mark": {"type": "line", "point": True},
             "encoding": {"x": {"field": "date", "type": "temporal", "title": "Data"},
                          "y": {"field": "ryzyko", "type": "quantitative", "title": "Ryzyko (0–1)",
                                "scale": {"domain": [0, 1]}},
                          "color": {"field": "pole", "type": "nominal", "title": "Pole"},
                          "strokeDash": {"field": "okres", "type": "nominal", "title": "",
                                         "scale": {"domain": ["dotychczas", "prognoza"], "range": [[1, 0], [5, 4]]}},
                          "tooltip": [{"field": "pole"}, {"field": "date", "type": "temporal", "title": "Data"},
                                      {"field": "ryzyko", "format": ".2f"}]}},
            *_level_rules(), *_today_rule(today),
        ],
    }
    return {"chart": spec, "summary": {"threat": t.name, "threat_code": t.code, "date_from": a, "date_to": b,
                                       "today": today, "fields": summary},
            "citations": [{"type": "risk", "field_id": f.id, "threat_code": t.code, "date": today.isoformat()}
                          for f in fields if f.name in summary]}


class WeatherVsRiskIn(BaseModel):
    field_id: int
    variable: str = PField("total_precipitation", description="total_precipitation | avg_temperature | avg_relative_humidity …")
    threat: str
    date_from: dt.date | None = None
    date_to: dt.date | None = None


@register("chart_weather_vs_risk", """
Wykres jednej zmiennej pogody (np. opady, temperatura, wilgotność) razem z ryzykiem zagrożenia
na polu, dwie osie. Zwraca Vega-Lite i `summary` (suma/średnia pogody, maksimum ryzyka, trend).
""", WeatherVsRiskIn)
def chart_weather_vs_risk(field_id: int, variable: str, threat: str, date_from=None, date_to=None) -> dict:
    from core.models import WeatherDaily
    from .platform import get_weather
    today = season_today()
    a, b, _ = _range(date_from, date_to, back=14, ahead=7)
    f = _field(field_id)
    t = domain.threat_by_code_or_name(threat, f.crop_id)
    if t is None:
        raise ToolError(f"Nie znam zagrożenia „{threat}”.")
    w = get_weather(field_id, a, b, [variable])
    rows = _risk_series(f, a, b, t.code).get(t, [])
    if not rows or not w.get("days"):
        raise ToolError("Brak danych pogody lub ryzyka w tym zakresie.")
    unit = _unit(WeatherDaily, variable)
    label = f"{WEATHER_LABELS.get(variable, variable)} [{unit}]"
    values = [{"date": d["date"].isoformat(), "wartosc": d[variable], "seria": "pogoda", "okres": d["source"]}
              for d in w["days"]]
    values += [{"date": r.date.isoformat(), "ryzyko": round(r.score, 3), "seria": "ryzyko"} for r in rows]
    weather_mark = "bar" if "precipitation" in variable else "line"
    spec = {
        "$schema": VEGA, "width": "container", "height": 260,
        "title": {"text": [f"{f.name}: {WEATHER_LABELS.get(variable, variable).lower()} a ryzyko", t.name],
                  "subtitle": f"{a:%d.%m} – {b:%d.%m.%Y}", "anchor": "start", "frame": "bounds"},
        "data": {"values": values},
        "layer": [
            {"transform": [{"filter": "datum.seria == 'pogoda'"}],
             "mark": {"type": weather_mark, "opacity": 0.55, "color": "#4f81bd"},
             "encoding": {"x": {"field": "date", "type": "temporal", "title": "Data"},
                          "y": {"field": "wartosc", "type": "quantitative", "title": label}}},
            {"transform": [{"filter": "datum.seria == 'ryzyko'"}],
             "mark": {"type": "line", "color": "#e53935", "point": True},
             "encoding": {"x": {"field": "date", "type": "temporal"},
                          "y": {"field": "ryzyko", "type": "quantitative", "title": "Ryzyko (0–1)",
                                "scale": {"domain": [0, 1]}}}},
            *_today_rule(today),
        ],
        "resolve": {"scale": {"y": "independent"}},
    }
    vals = [d[variable] for d in w["days"] if d[variable] is not None]
    agg = round(sum(vals), 1) if "precipitation" in variable else round(sum(vals) / len(vals), 1) if vals else None
    return {"chart": spec, "summary": {"field": f.name, "threat": t.name, "variable": variable, "unit": unit,
                                       "weather_" + ("sum" if "precipitation" in variable else "mean"): agg,
                                       "risk": _series_summary(rows, today), "date_from": a, "date_to": b},
            "citations": [{"type": "risk", "field_id": f.id, "threat_code": t.code, "date": today.isoformat()}]}


class FarmOverviewIn(BaseModel):
    date: dt.date | None = PField(None, description="Domyślnie dziś.")


@register("chart_farm_overview", """
Wykres słupkowy: najwyższe ryzyko na każdym polu w danym dniu (kolor = poziom), z nazwą
najgroźniejszego zagrożenia. Zwraca Vega-Lite i `summary` (liczba pól na poziom, najpilniejsze).
""", FarmOverviewIn)
def chart_farm_overview(date: dt.date | None = None) -> dict:
    s = get_farm_risk_summary(date)
    values = [{"pole": f["name"], "ryzyko": f["max_score"] or 0, "poziom": f["max_level"],
               "zagrozenie": f["top_threats"][0]["threat"] if f["top_threats"] else "—"} for f in s["fields"]]
    spec = {
        "$schema": VEGA, "width": "container", "height": 40 + 28 * len(values),
        "title": {"text": f"Najwyższe ryzyko na polach — {s['date']:%d.%m.%Y}", "anchor": "start", "frame": "bounds"},
        "data": {"values": values},
        "mark": "bar",
        "encoding": {"y": {"field": "pole", "type": "nominal", "sort": "-x", "title": "Pole"},
                     "x": {"field": "ryzyko", "type": "quantitative", "title": "Ryzyko (0–1)", "scale": {"domain": [0, 1]}},
                     "color": {"field": "poziom", "type": "nominal", "title": "Poziom",
                               "scale": {"domain": list(LEVEL_COLORS), "range": list(LEVEL_COLORS.values())}},
                     "tooltip": [{"field": "pole"}, {"field": "zagrozenie", "title": "Zagrożenie"},
                                 {"field": "ryzyko", "format": ".2f"}]},
    }
    counts = {}
    for v in values:
        counts[v["poziom"]] = counts.get(v["poziom"], 0) + 1
    return {"chart": spec, "summary": {"date": s["date"], "fields_per_level": counts,
                                       "most_urgent": s["most_urgent"][:3]},
            "citations": [p["citation"] for p in s["most_urgent"][:3]]}
