"""
Read-only tools over the platform's data (core models), through the team's query helpers.

Reads use the `default` connection: the `readonly` connection/role does not exist yet
(see docs/archive/INTERFACE_PROPOSALS.md). These tools never write and never return data after
today + FORECAST_DAYS (the demo rule "nothing after the forecast").
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from pydantic import BaseModel, Field as PField

from assistant import domain
from .registry import ToolError, register

DEFAULT_WEATHER_VARS = ["avg_temperature", "min_temperature", "max_temperature", "total_precipitation",
                        "avg_relative_humidity"]
SUM_VARS = {"total_precipitation", "imerg_total_precipitation", "eto", "etr"}


# ----------------------------------------------------------------------------- helpers
def season_today() -> dt.date:
    from core import clock
    try:
        return clock.today()
    except clock.ClockNotSetError:
        raise ToolError("Nie ustawiono daty sezonu demo (Clock). Ustaw ją w /admin/ albo uruchom seed.") from None


def horizon() -> tuple[dt.date, dt.date]:
    from core import clock
    today = season_today()
    return today, today + dt.timedelta(days=clock.FORECAST_DAYS)


def _field(field_id: int):
    from core.models import Field
    try:
        return Field.objects.select_related("crop").get(pk=field_id)
    except Field.DoesNotExist:
        raise ToolError(f"Nie ma pola o id {field_id}.") from None


def _range(date_from, date_to, back: int, ahead: int) -> tuple[dt.date, dt.date, bool]:
    today, limit = horizon()
    a = date_from or today - dt.timedelta(days=back)
    b = date_to or min(limit, today + dt.timedelta(days=ahead))
    cut = b > limit
    b = min(b, limit)
    if a > b:
        raise ToolError(f"Pusty zakres dat ({a} – {b}); dane sięgają najdalej do {limit}.")
    return a, b, cut


def _expl(e) -> dict:
    """Read Risk.explanation: the engine's version 1 (summary, drivers, action, growth_stage, confidence),
    or the older {summary, factors} shape. Unknown keys are ignored."""
    if not isinstance(e, dict):
        return {"summary": str(e) if e else ""}
    out = {"summary": e.get("summary", "")}
    if isinstance(e.get("drivers"), list):  # engine v1: why, with each factor's effect on the score
        drivers = sorted(e["drivers"], key=lambda d: -(d.get("effect") or 0))
        out["drivers"] = [{k: d.get(k) for k in ("label", "value", "unit", "threshold", "effect", "kind", "observed_on", "text")
                           if d.get(k) not in (None, "")} for d in drivers[:5]]
    elif isinstance(e.get("factors"), list):
        out["factors"] = e["factors"][:6]
    act = e.get("action")
    if isinstance(act, dict):
        out["action"] = {"type": act.get("type"), "text": act.get("text"), "threshold": act.get("threshold")}
        if isinstance(act.get("spray_window"), dict) and act["spray_window"].get("date"):
            out["action"]["weather_window"] = act["spray_window"]["date"]
    gs = e.get("growth_stage")
    if isinstance(gs, dict) and gs.get("bbch") is not None:
        out["growth_stage"] = {k: gs.get(k) for k in ("bbch", "name", "sowing_assumed", "confidence") if gs.get(k) is not None}
    for k in ("confidence", "source"):
        if e.get(k) is not None:
            out[k] = e[k]
    return out


def _unit(model, name: str) -> str:
    ht = model._meta.get_field(name).help_text or ""
    return ht[1:ht.index("]")] if ht.startswith("[") and "]" in ht else ""


def field_summary(f) -> dict:
    return {"id": f.id, "name": f.name, "crop": domain.crop_pl(f.crop_id), "crop_code": f.crop_id,
            "area_ha": round(f.area_ha, 1)}


# ----------------------------------------------------------------------------- season / fields
class NoArgs(BaseModel):
    pass


@register("get_season_date", """
Data „dziś” w symulowanym sezonie (demo odtwarza przeszły sezon) i horyzont prognozy.
„Wczoraj”, „ten tydzień” itp. liczymy od tej daty, nigdy od zegara systemowego.
""", NoArgs)
def get_season_date() -> dict:
    today, limit = horizon()
    return {"today": today, "forecast_days": (limit - today).days, "forecast_until": limit}


@register("list_fields", """
Lista pól gospodarstwa (demo ma jedno gospodarstwo): id, nazwa, uprawa, powierzchnia [ha].
Użyj, żeby znaleźć id pola po nazwie.
""", NoArgs)
def list_fields() -> dict:
    from core.models import Field
    return {"fields": [field_summary(f) for f in Field.objects.select_related("crop").order_by("name")]}


class FieldIn(BaseModel):
    field_id: int = PField(description="Id pola (z list_fields).")


@register("get_field", """
Szczegóły pola: uprawa, powierzchnia [ha], położenie (środek), historia upraw z ostatnich lat,
gleba (pH, udział iłu/piasku/pyłu w %, materia organiczna; średnia z komórek pola). Bez geometrii.
""", FieldIn)
def get_field(field_id: int) -> dict:
    f = _field(field_id)
    out = field_summary(f) | {"centroid": {"lat": round(f.centroid_lat, 4), "lon": round(f.centroid_lon, 4)},
                              "weather_grid_id": f.weather_grid_id}
    hist = defaultdict(list)
    for cy in f.crop_years.select_related("crop_class").order_by("-year", "-share"):
        hist[cy.year].append({"crop": cy.crop_class.name, "share": round(cy.share, 2)})
    out["crop_history"] = [{"year": y, "classes": c[:2]} for y, c in sorted(hist.items(), reverse=True)[:4]]
    cells = list(f.soil_cells().values("ph", "soil_texture", "clay", "sand", "silt", "om"))
    if cells:
        num = {k: [c[k] for c in cells if c[k] is not None] for k in ("ph", "clay", "sand", "silt", "om")}
        avg = {k: sum(v) / len(v) for k, v in num.items() if v}
        out["soil"] = {"ph": round(avg["ph"], 1)} if "ph" in avg else {}
        for k in ("clay", "sand", "silt"):  # core.SoilCell stores fractions 0-1 (as in the real files)
            if k in avg:
                out["soil"][f"{k}_pct"] = round(avg[k] * 100 if avg[k] <= 1 else avg[k], 1)
        if "om" in avg:
            out["soil"]["om"] = round(avg["om"], 2)
        textures = [c["soil_texture"] for c in cells if c["soil_texture"]]
        if textures:
            out["soil"]["soil_texture"] = max(set(textures), key=textures.count)
    return out


# ----------------------------------------------------------------------------- risks
class FieldRisksIn(BaseModel):
    field_id: int
    date_from: dt.date | None = PField(None, description="Domyślnie dziś − 3 dni.")
    date_to: dt.date | None = PField(None, description="Domyślnie dziś + 7 dni (więcej się nie da).")
    threat: str | None = PField(None, description="Kod lub nazwa zagrożenia (dowolna forma); puste = wszystkie.")


def _risk_series(field, a: dt.date, b: dt.date, threat_code: str | None = None):
    from core.models import Risk
    qs = Risk.objects.filter(field=field, date__gte=a, date__lte=b).select_related("threat").order_by("date")
    if threat_code:
        qs = qs.filter(threat__code=threat_code)
    by = defaultdict(list)
    for r in qs:
        by[r.threat].append(r)
    return by


def summarize_threat(threat, rows, today: dt.date, field_id: int) -> dict:
    past = [r for r in rows if r.date <= today]
    now = next((r for r in reversed(past)), None) or (rows[0] if rows else None)
    peak = max(rows, key=lambda r: r.score)
    lvl_n, lvl = domain.level_from_explanation(now.explanation, now.score) if now else domain.level(None)
    scores_to_today = [r.score for r in past]
    return {
        "threat_code": threat.code, "threat": threat.name, "category": threat.category,
        "today": {"date": now.date if now else None, "score": round(now.score, 2) if now else None,
                  "level": lvl, "level_n": lvl_n},
        "max": {"date": peak.date, "score": round(peak.score, 2), "level": domain.level(peak.score)[1]},
        "trend": domain.trend(scores_to_today),
        "rising_days": domain.rising_days(scores_to_today),
        "explanation": _expl(now.explanation) if now else {},
        "points": [{"date": r.date, "score": round(r.score, 2)} for r in rows],
        "citation": {"type": "risk", "field_id": field_id, "threat_code": threat.code,
                     "date": (now.date if now else today).isoformat()},
    }


@register("get_field_risks", """
Ryzyko zagrożeń pola według silnika decyzyjnego (score 0–1, poziom: niskie/średnie/wysokie —
progi silnika), dziś i w zakresie dat: maksimum, trend (liczony w kodzie), wyjaśnienie silnika
(dlaczego) i punkty dzienne. Bez filtra zwraca szczegóły tylko zagrożeń istotnych (score ≥ 0,33
w zakresie) + nazwy pozostałych. Powody ryzyka bierz tylko z pola `explanation`.
""", FieldRisksIn)
def get_field_risks(field_id: int, date_from=None, date_to=None, threat: str | None = None) -> dict:
    f = _field(field_id)
    today = season_today()
    a, b, cut = _range(date_from, date_to, back=3, ahead=7)
    code = None
    if threat:
        t = domain.threat_by_code_or_name(threat, f.crop_id)
        if t is None:
            raise ToolError(f"Nie znam zagrożenia „{threat}” dla uprawy {domain.crop_pl(f.crop_id)}.")
        code = t.code
    series = _risk_series(f, a, b, code)
    items = [summarize_threat(t, rows, today, f.id) for t, rows in series.items()]
    items.sort(key=lambda x: -(x["today"]["score"] or 0))
    if code:
        relevant, other = items, []
    else:
        relevant = [x for x in items if x["max"]["score"] >= domain.RELEVANT_SCORE]
        other = [x["threat"] for x in items if x["max"]["score"] < domain.RELEVANT_SCORE]
        for x in relevant:  # overview: no daily points (ask for one threat to get them)
            x.pop("points")
            x["explanation"].pop("factors", None) if len(relevant) > 4 else None
    if (b - a).days > 21:  # long ranges: weekly maxima instead of daily points
        for x in (x for x in relevant if "points" in x):
            weeks = defaultdict(list)
            for p in x["points"]:
                weeks[p["date"] - dt.timedelta(days=p["date"].weekday())].append(p["score"])
            x["points"] = [{"week_start": w, "max_score": max(s)} for w, s in sorted(weeks.items())]
    return {"field": field_summary(f), "today": today, "date_from": a, "date_to": b, "cut_at_forecast": cut,
            "levels_note": "poziomy silnika: <0,33 niskie, <0,66 średnie, ≥0,66 wysokie",
            "threats": relevant, "other_threats_low": other}


class FarmSummaryIn(BaseModel):
    date: dt.date | None = PField(None, description="Domyślnie dziś (data sezonu).")


@register("get_farm_risk_summary", """
Przegląd całego gospodarstwa na dany dzień: dla każdego pola 3 najgroźniejsze zagrożenia
(score, poziom, trend z 4 dni) i lista najpilniejszych par pole × zagrożenie (najwyższy score).
""", FarmSummaryIn)
def get_farm_risk_summary(date: dt.date | None = None) -> dict:
    from core.models import Field, Risk
    today, limit = horizon()
    d = date or today
    if d > limit:
        raise ToolError(f"Data {d} jest po horyzoncie prognozy ({limit}).")
    rows = Risk.objects.filter(date__gte=d - dt.timedelta(days=3), date__lte=d).select_related("threat", "field")
    by = defaultdict(list)
    for r in rows.order_by("date"):
        by[(r.field_id, r.threat_id)].append(r)
    fields = {f.id: f for f in Field.objects.select_related("crop")}
    pairs = []
    for (fid, _), rs in by.items():
        last = rs[-1]
        if last.date != d:
            continue
        pairs.append({"field_id": fid, "field": fields[fid].name, "threat_code": last.threat.code,
                      "threat": last.threat.name, "score": round(last.score, 2),
                      "level": domain.level_from_explanation(last.explanation, last.score)[1],
                      "trend": domain.trend([r.score for r in rs]), "explanation": _expl(last.explanation).get("summary", ""),
                      "citation": {"type": "risk", "field_id": fid, "threat_code": last.threat.code,
                                   "date": d.isoformat()}})
    pairs.sort(key=lambda p: -p["score"])
    per_field = []
    for fid, f in fields.items():
        top = [p for p in pairs if p["field_id"] == fid][:3]
        per_field.append(field_summary(f) | {"max_score": top[0]["score"] if top else None,
                                             "max_level": top[0]["level"] if top else "brak danych",
                                             "top_threats": [{k: p[k] for k in ("threat_code", "threat", "score", "level", "trend")}
                                                             for p in top]})
    per_field.sort(key=lambda x: -(x["max_score"] or 0))
    leaders = [next(p for p in pairs if p["field_id"] == f["id"]) for f in per_field if f["max_score"] is not None]
    # leaders: each field's most dangerous pair (with its explanation and citation), most urgent field first
    return {"date": d, "fields": per_field, "most_urgent": pairs[:5], "leaders": leaders}


# ----------------------------------------------------------------------------- weather
class WeatherIn(BaseModel):
    field_id: int
    date_from: dt.date | None = PField(None, description="Domyślnie dziś − 7 dni.")
    date_to: dt.date | None = PField(None, description="Domyślnie dziś + 7 dni (prognoza).")
    variables: list[str] | None = PField(None, description=f"Kolumny pogody; domyślnie {DEFAULT_WEATHER_VARS}.")


@register("get_weather", """
Pogoda dzienna dla pola (punkt siatki pogodowej najbliższy polu): obserwacje do dziś i prognoza
na kolejne dni (oznaczone source=observed/forecast). Jednostki w polu `units` (°C, mm/dzień, %).
Zakresy dłuższe niż 31 dni są agregowane tygodniowo (średnie; opady sumowane).
Opad (total_precipitation): z modelu pogody, a gdy go brak — z satelity IMERG, jak w silniku.
""", WeatherIn)
def get_weather(field_id: int, date_from=None, date_to=None, variables=None) -> dict:
    from core.models import WeatherDaily, WeatherForecastDaily
    f = _field(field_id)
    today = season_today()
    a, b, cut = _range(date_from, date_to, back=7, ahead=7)
    allowed = {fl.name for fl in WeatherDaily._meta.get_fields() if fl.concrete and fl.get_internal_type() == "FloatField"}
    vars_ = variables or DEFAULT_WEATHER_VARS
    bad = [v for v in vars_ if v not in allowed]
    if bad:
        raise ToolError(f"Nieznane zmienne pogody: {bad}. Dostępne m.in.: {sorted(allowed)[:12]}…")
    obs = WeatherDaily.objects.observed().filter(grid_id=f.weather_grid_id, date__gte=a, date__lte=min(b, today))
    rain = "total_precipitation" in vars_ and "imerg_total_precipitation" not in vars_
    cols = [*vars_, "imerg_total_precipitation"] if rain else vars_
    days = []
    for r in obs.order_by("date").values("date", *cols):
        day = {"date": r["date"], "source": "observed"} | {v: r[v] for v in vars_}
        if rain and day["total_precipitation"] is None and r["imerg_total_precipitation"] is not None:
            # the station value is often missing; the engine uses the satellite (IMERG) value then, so do we
            day["total_precipitation"] = r["imerg_total_precipitation"]
            day["precipitation_source"] = "satelita (IMERG)"
        days.append(day)
    if b > today:
        fc = WeatherForecastDaily.objects.current().filter(grid_id=f.weather_grid_id, date__gte=max(a, today + dt.timedelta(days=1)), date__lte=b)
        days += [{"date": r["date"], "source": "forecast"} | {v: r[v] for v in vars_}
                 for r in fc.order_by("date").values("date", *vars_)]
    units = {v: _unit(WeatherDaily, v) for v in vars_}
    if (b - a).days > 31:
        weeks = defaultdict(list)
        for d in days:
            weeks[d["date"] - dt.timedelta(days=d["date"].weekday())].append(d)
        agg = []
        for w, ds in sorted(weeks.items()):
            row = {"week_start": w, "days": len(ds), "source": "forecast" if all(x["source"] == "forecast" for x in ds) else "observed"}
            for v in vars_:
                vals = [x[v] for x in ds if x[v] is not None]
                row[v] = None if not vals else round(sum(vals) if v in SUM_VARS else sum(vals) / len(vals), 1)
            agg.append(row)
        return {"field_id": f.id, "date_from": a, "date_to": b, "cut_at_forecast": cut, "aggregation": "weekly",
                "units": units, "weeks": agg}
    for d in days:
        for v in vars_:
            if isinstance(d[v], float):
                d[v] = round(d[v], 1)
    return {"field_id": f.id, "date_from": a, "date_to": b, "cut_at_forecast": cut, "aggregation": "daily",
            "units": units, "days": days}


# ----------------------------------------------------------------------------- observations (read)
class ObservationsIn(BaseModel):
    field_id: int
    date_from: dt.date | None = None
    date_to: dt.date | None = None


@register("get_observations", """
Zgłoszenia rolnika dla pola (i te dotyczące całego gospodarstwa): data, rodzaj (objawy / czysto /
sąsiad / zabieg / fakt o polu / zdarzenie), kategoria, zagrożenie, nasilenie, jego słowa. Najnowsze
pierwsze, tylko do dzisiejszej daty sezonu.
""", ObservationsIn)
def get_observations(field_id: int, date_from=None, date_to=None) -> dict:
    from django.db.models import Q

    from core.models import Observation

    from .observations import CATEGORY_PL, severity_pl
    f = _field(field_id)
    today = season_today()
    qs = (Observation.objects.observed(min(date_to or today, today))
          .filter(Q(field=f) | Q(field__isnull=True)).select_related("threat"))
    if date_from:
        qs = qs.filter(observed_on__gte=date_from)
    return {"field_id": f.id, "observations": [
        {"id": o.id, "date": o.observed_on, "kind": o.kind, "category": CATEGORY_PL.get(o.category, o.category),
         "threat": o.threat.name if o.threat else None, "threat_code": o.threat.code if o.threat else None,
         "severity": severity_pl(o.severity), "distance_m": o.distance_m, "whole_farm": o.field_id is None,
         "facts": {k: v for k, v in (o.details or {}).items() if k in ("sowing_date", "tillage", "resistant_to", "type")},
         "text": o.text}
        for o in qs[:50]]}
