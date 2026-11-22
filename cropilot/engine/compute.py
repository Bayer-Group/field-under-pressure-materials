"""
The engine's entry points, as agreed in docs/interfaces.md and docs/archive/engine-predict-review.md:

    predict(field_ids=None, start=None, end=None) -> PredictResult   (an int: rows written, + .field_ids)
    clock_moved(old, new) -> PredictResult                            (the platform calls it when the demo date moves)
    precompute_season(season=None) -> PredictResult                   (the demo seed calls it once)
    precompute_dates(first=None, last=None) -> int                    (optional: makes date moves copies, not computes)

Computes the risk of every threat of each field's crop, for every day from `start` to `end`, and
overwrites them in Risk in one transaction. Which weather a day is assessed with:

    day <= today                 weather observed up to that day ("as of that day")
    today < day <= today + 7     weather observed up to today, then the forecast issued today (coming days)
    day > today + 7              weather observed up to that day; only the demo precompute writes these, and
                                 clock_moved() recomputes them as coming days once the date gets within 7 days

Features are trailing windows (engine/features.py), so a day never reads weather after itself.

Every computed day is also kept in engine.RiskSnapshot (engine/models.py): clock_moved() copies the rows it
needs from there and computes only what is missing; precompute_dates() fills it ahead for a range of dates.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import date, timedelta

import pandas as pd
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from core import clock
from core.models import Field, Risk, Threat, WeatherDaily, WeatherForecastDaily
from engine.models import RiskSnapshot
from engine import features as F
from engine import observations as OBS
from engine.catalog import CARRYOVER, MAIZE, RULES, rules_for_crop
from engine.phenology import PROFILES, bbch_series, calibrate, degree_days_base10, season_end
from engine.satellite.season import season_bounds, season_of
from engine.scoring import FieldContext, score_rule, spray_window

log = logging.getLogger(__name__)


SPREAD_RADIUS_M = 3000  # symptoms on one field raise the risk on fields of the same crop within this distance

# The "today" that splits assessed-as-of days from coming days in _season_rows. Only precompute_dates() sets it
# (to compute the coming days of other demo dates); the season, crop and field facts still follow the Clock.
_AS_OF: ContextVar[date | None] = ContextVar("engine_as_of", default=None)


class PredictResult(int):
    """
    The number of Risk rows written (an int, so callers that only count keep working), plus
    `.field_ids`: every field whose rows were rewritten, including nearby fields that a symptoms report
    spread to (the assistant returns them in updated_field_ids so the map reloads them).
    """

    def __new__(cls, rows: int = 0, field_ids=()):
        obj = super().__new__(cls, rows)
        obj.field_ids = sorted(set(field_ids))
        return obj

    def __add__(self, other):
        return PredictResult(int(self) + int(other), list(self.field_ids) + list(getattr(other, "field_ids", [])))

    def __repr__(self):
        return f"PredictResult({int(self)}, field_ids={self.field_ids})"


def last_computable_day(today: date | None = None) -> date | None:
    """The last day that has weather: observed (demo) or in the forecast issued today (live)."""
    today = today or clock.today()
    obs = WeatherDaily.objects.aggregate(m=Max("date"))["m"]
    fc = WeatherForecastDaily.objects.current(as_of=today).aggregate(m=Max("date"))["m"]
    days = [d for d in (obs, fc) if d is not None]
    return max(days) if days else None


def predict(field_ids: list[int] | None = None, start: date | None = None, end: date | None = None,
            observations: list | None = None) -> PredictResult:
    """
    start: default the season start (1 September).
    end:   default the later of today + 7 and the last day already stored for these fields, so a
           recompute after a farmer report or a crop change also replaces the precomputed days.
    `observations`: optional farmer reports (engine.observations.Report) to use instead of the
    Observation table, e.g. in tests or a scripted demo. Each report affects days >= its date only.
    Symptoms reported on a field also raise the risk on nearby fields of the same crop, so those
    fields are recomputed too (and listed in the result's .field_ids).
    """
    return _write(field_ids, start, end, observations, invalidate=True)


def _write(field_ids, start, end, observations=None, invalidate=True) -> PredictResult:
    """predict()'s body. invalidate=False: the inputs did not change (clock_moved filling a gap), so the
    precomputed snapshots of these fields stay valid."""
    today = clock.today()
    start = start or season_bounds(season_of(today))[0]
    if end is None:
        stored = Risk.objects.filter(**({"field_id__in": field_ids} if field_ids is not None else {}))
        last = stored.aggregate(m=Max("date"))["m"]
        end = max(today + timedelta(days=clock.FORECAST_DAYS), last or today)
    last_day = last_computable_day(today)
    if last_day is None:
        log.warning("predict: no weather at all, nothing computed")
        return PredictResult(0)
    end = min(end, last_day)  # days without any weather can't be recomputed: leave their rows alone
    if start > end:
        return PredictResult(0)
    rows, n_fields, field_list = compute_rows(field_ids, start, end, observations, with_fields=True)
    with transaction.atomic():
        # replace the whole range for these fields: rows of threats that no longer apply (the crop changed,
        # a season not computable yet) must not linger
        Risk.objects.filter(field_id__in=[f.id for f in field_list], date__range=(start, end)).delete()
        Risk.objects.bulk_create(
            rows, batch_size=2000, update_conflicts=True,
            unique_fields=["field", "threat", "date"], update_fields=["score", "explanation", "computed_at"],
        )
        ids = [f.id for f in field_list]
        if invalidate:  # a report, a crop change or new data: what was precomputed for these fields is stale
            RiskSnapshot.objects.filter(field_id__in=ids, date__gte=start).delete()
        if observations is None:  # rows from scripted reports (tests, what-if) are not the database's state
            _store(rows, ids, start, end, today)
    log.info("predict: %d risk rows for %d fields, %s..%s", len(rows), n_fields, start, end)
    return PredictResult(len(rows), [f.id for f in field_list])


def clock_moved(old: date, new: date | None = None) -> PredictResult:
    """
    The demo date moved from `old` to `new` (default: the Clock's current date). Recomputes exactly the
    days whose inputs changed, (min(old, new), max(old, new) + 7], for every field: days that were
    coming days and are now past go back to "as of that day", and the new coming days are computed
    from the forecast issued on `new`. Nothing else is rewritten.

    Called by core.clock.set_today() (PUT /api/clock/, the admin's clock page, engine_set_date), which saves
    the Clock and calls this in one transaction; there is no signal. Never move the date any other way.

    A move into another season recomputes season by season, oldest first (a season's carry-over reads the
    previous season's peaks from Risk), from the start of the season before the later date at the earliest.
    """
    new = new or clock.today()
    if old == new:
        return PredictResult(0)
    lo, hi = min(old, new), max(old, new)
    start, end = lo + timedelta(days=1), hi + timedelta(days=clock.FORECAST_DAYS)
    if season_of(old) != season_of(new):  # another season: other crops and facts, nothing reusable
        return _by_season(max(start, season_bounds(season_of(hi) - 1)[0]), end)
    last_day = last_computable_day(new)
    if last_day is None:
        return PredictResult(0)
    end = min(end, last_day)
    if start > end:
        return PredictResult(0)

    # copy what is precomputed: "as of" bundles for past days, bundles issued on `new` for its coming days
    horizon = new + timedelta(days=clock.FORECAST_DAYS)
    days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    want = {d: (new if new < d <= horizon else None) for d in days}
    field_ids = list(Field.objects.values_list("id", flat=True))
    have: dict[tuple[int, date], list] = {}
    for f, d, issued, rows in (RiskSnapshot.objects.filter(field_id__in=field_ids, date__range=(start, end),
                                                           season=season_of(new))
                               .filter(Q(issued_on__isnull=True) | Q(issued_on=new))
                               .values_list("field_id", "date", "issued_on", "rows")):
        if want[d] == issued:
            have[(f, d)] = rows
    ready = [f for f in field_ids if all((f, d) in have for d in days)]
    missing = [f for f in field_ids if f not in ready]
    now = timezone.now()
    out = [Risk(field_id=f, threat_id=r["threat_id"], date=d, score=r["score"], explanation=r["explanation"], computed_at=now)
           for f in ready for d in days for r in have[(f, d)]]
    with transaction.atomic():
        Risk.objects.filter(field_id__in=ready, date__range=(start, end)).delete()
        Risk.objects.bulk_create(out, batch_size=2000, update_conflicts=True, unique_fields=["field", "threat", "date"],
                                 update_fields=["score", "explanation", "computed_at"])  # a concurrent predict() wrote them
    result = PredictResult(len(out), ready)
    if missing:  # computed now and kept, so the next move to this date is a copy too
        result = result + _write(missing, start, end, invalidate=False)
    log.info("clock_moved %s -> %s: %d fields copied, %d computed", old, new, len(ready), len(missing))
    return result


def _by_season(start: date, end: date) -> PredictResult:
    """predict() over [start, end] one season at a time, oldest first, so each season's carry-over reads the
    peaks the previous one has just written."""
    result = PredictResult(0)
    s = start
    while s <= end:
        s_end = min(end, season_bounds(season_of(s))[1])
        result = result + predict(start=s, end=s_end)
        s = s_end + timedelta(days=1)
    return result


def precompute_dates(first: date | None = None, last: date | None = None) -> int:
    """
    Computes ahead what clock_moved() needs for any demo date in [first, last] (default: the Clock's date - 7
    ... + 30, within its season): the coming days of each date (from the forecast issued that day) and every
    day assessed as of itself. Writes only engine.RiskSnapshot, never Risk. Returns the bundles written.
    Run it after the seed (python manage.py engine_precompute_dates); predict() drops the bundles a report makes
    stale, and clock_moved() recomputes those fields only.
    """
    today = clock.today()
    season = season_of(today)
    s0, s1 = season_bounds(season)
    first = max(first or today - timedelta(days=7), s0)
    # a date after the season's end is another season: clock_moved() recomputes it, so bundles for it are never read
    last = min(last or today + timedelta(days=30), s1)
    obs_last = WeatherDaily.objects.aggregate(m=Max("date"))["m"]
    if obs_last is None or first > last:
        return 0
    field_ids = list(Field.objects.values_list("id", flat=True))
    n = 0
    # 1. every day assessed as of itself, from first + 1 to last + 7 (as if the Clock stood after them all)
    a0, a1 = first + timedelta(days=1), min(last + timedelta(days=clock.FORECAST_DAYS), obs_last)
    if a0 <= a1:
        token = _AS_OF.set(a1)
        try:
            rows, _ = compute_rows(None, a0, a1)
        finally:
            _AS_OF.reset(token)
        n += _store(rows, field_ids, a0, a1, a1)
    # 2. the coming days of each date, each from the forecast issued that day
    d = first
    while d <= last:
        h = d + timedelta(days=clock.FORECAST_DAYS)
        fc_last = WeatherForecastDaily.objects.current(as_of=d).aggregate(m=Max("date"))["m"]
        h = min(h, fc_last) if fc_last else d
        done = RiskSnapshot.objects.filter(issued_on=d, season=season, field_id__in=field_ids).count()
        if h > d and done < len(field_ids) * (h - d).days:
            token = _AS_OF.set(d)
            try:
                rows, _ = compute_rows(None, d + timedelta(days=1), h)
            finally:
                _AS_OF.reset(token)
            n += _store(rows, field_ids, d + timedelta(days=1), h, d)
        d += timedelta(days=1)
    log.info("precompute_dates %s..%s: %d snapshot bundles", first, last, n)
    return n


def _store(rows: list[Risk], field_ids, start: date, end: date, today: date) -> int:
    """Keeps computed rows as snapshot bundles: one per field and day (also when it has no rows)."""
    season = season_of(clock.today())
    horizon = today + timedelta(days=clock.FORECAST_DAYS)
    by_key: dict[tuple[int, date], list] = {}
    for r in rows:
        by_key.setdefault((r.field_id, r.date), []).append({"threat_id": r.threat_id, "score": r.score, "explanation": r.explanation})
    days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    issued = {d: (today if today < d <= horizon else None) for d in days}
    bundles = [RiskSnapshot(field_id=f, date=d, issued_on=issued[d], season=season, rows=by_key.get((f, d), []))
               for f in field_ids for d in days]
    with transaction.atomic():
        for value in set(issued.values()):
            ds = [d for d in days if issued[d] == value]
            q = RiskSnapshot.objects.filter(field_id__in=field_ids, date__in=ds, season=season)
            (q.filter(issued_on__isnull=True) if value is None else q.filter(issued_on=value)).delete()
        RiskSnapshot.objects.bulk_create(bundles, batch_size=1000)
    return len(bundles)


def precompute_season(season: int | None = None) -> PredictResult:
    """
    For the demo seed: computes the previous season (this season's carry-over reads its peaks from
    Risk), then this season to its end (maize to 31 December), in that order. Days after today + 7
    are assessed as of that day and recomputed by clock_moved() when the date comes within 7 days.
    """
    season = season or season_of(clock.today())
    p0, p1 = season_bounds(season - 1)
    first = predict(start=p0, end=p1)
    s0, _ = season_bounds(season)
    return first + predict(start=s0, end=date(season, 12, 31))


def compute_rows(field_ids, start: date, end: date, observations=None, with_fields: bool = False):
    """Computes (does not save) the Risk rows. Shared by predict() and what_if()."""
    all_fields = list(Field.objects.select_related("crop", "weather_grid"))
    reports = list(observations) if observations is not None else OBS.load_all(start, end)
    reports += [r for f in all_fields for r in OBS.from_field(f)]  # facts stored on the field (if those columns exist)
    reports += farm_spread(reports, all_fields)
    if field_ids is not None:
        wanted = set(field_ids)
        # fields that get a derived "nearby symptoms" report from the requested fields are recomputed too
        wanted |= {r.field_id for r in reports if r.details.get("derived_from_field") in field_ids}
        fields = [f for f in all_fields if f.id in wanted]
    else:
        fields = all_fields
    threats = {t.code: t for t in Threat.objects.all()}
    now = timezone.now()
    rows: list[Risk] = []
    for field in fields:
        rows += _field_rows(field, threats, start, end, now, OBS.for_field(reports, field.id))
    if with_fields:
        return rows, len(fields), fields
    return rows, len(fields)


def farm_spread(reports, fields) -> list:
    """Symptoms on one field -> a 'neighbour' report for every other field of the same crop within 3 km."""
    import math

    by_id = {f.id: f for f in fields}
    out = []
    for r in reports:
        if r.kind != "symptoms" or r.field_id not in by_id or not r.threat_code:
            continue
        src = by_id[r.field_id]
        for f in fields:
            if f.id == src.id or f.crop_id != src.crop_id:
                continue
            dy = (f.centroid_lat - src.centroid_lat) * 111_320
            dx = (f.centroid_lon - src.centroid_lon) * 111_320 * math.cos(math.radians(src.centroid_lat))
            d = math.hypot(dx, dy)
            if d <= SPREAD_RADIUS_M:
                out.append(OBS.Report(observed_on=r.observed_on, kind="neighbour", threat_code=r.threat_code, distance_m=round(d),
                                      field_id=f.id, text=f"Objawy zgłoszone na polu {src.name}",
                                      details={"derived_from_field": src.id, "derived_from_report": r.id}))
    return out


def what_if(field_id: int, day: date, hypothetical: list, start: date | None = None) -> list[dict]:
    """
    Dry run for the assistant: how would this field's risks on `day` change with these extra reports
    (e.g. "if I spray tomorrow", "if I sowed on 10 October")? Nothing is written.
    Returns one entry per threat: code, score now, score with the reports, level, summary.
    """
    start = start or day - timedelta(days=30)
    existing = OBS.load_all(start, day)
    base, _ = compute_rows([field_id], start, day, existing)
    alt, _ = compute_rows([field_id], start, day, existing + list(hypothetical))
    pick = lambda rows: {r.threat.code: r for r in rows if r.date == day and r.field_id == field_id}
    b, a = pick(base), pick(alt)
    out = []
    for code in sorted(a, key=lambda c: -a[c].score):
        out.append({"threat_code": code, "score_now": b[code].score if code in b else None, "score_if": a[code].score,
                    "change": round(a[code].score - (b[code].score if code in b else 0), 3),
                    "level_if": a[code].explanation["level"], "summary_if": a[code].explanation["summary"]})
    return out


def field_context(field: Field, season: int, crop_code: int | None = None, crop_source: str = "field") -> FieldContext:
    crop = crop_code or field.crop_id
    history = {}
    names = {}
    for fcy in field.crop_years.select_related("crop_class").all():
        best = history.get(fcy.year)
        if best is None or fcy.share > best[1]:
            history[fcy.year] = (fcy.crop_class_id, fcy.share)
            names[fcy.year] = fcy.crop_class.name
    prev = history.get(season - 1)
    in_row = 1 if crop == MAIZE else 0
    if crop == MAIZE:
        y = season - 1
        while history.get(y, (None,))[0] == MAIZE:
            in_row += 1
            y -= 1
    soil = {}
    cells = list(field.soil_cells().values("clay", "sand", "ph"))
    for key in ("clay", "sand", "ph"):
        vals = [c[key] for c in cells if c[key] is not None]
        if vals:
            soil[key] = sum(vals) / len(vals)
    for key in ("clay", "sand"):  # the soil package stores fractions (0.18), the doc says % (18): accept both
        if key in soil and soil[key] <= 1.0:
            soil[key] *= 100
    return FieldContext(crop=crop, crop_source=crop_source, previous_crop=prev[0] if prev else None,
                        previous_crop_name=names.get(season - 1), maize_years_in_row=in_row, soil=soil,
                        history={y: c for y, (c, _) in history.items()}, season=season)


def season_crop(field: Field, season: int) -> tuple[int | None, str]:
    """
    The crop of a field in a season. Field.crop is the crop of the current season (the clock's); for
    earlier seasons the crop map says what grew there (largest share), so last season is scored with
    last season's crop.
    """
    if season >= season_of(clock.today()):
        return field.crop_id, "field"
    best = field.crop_years.filter(year=season).order_by("-share").values_list("crop_class_id", flat=True).first()
    return best, "crop map"


def crop_season_segments(field: Field, start: date, end: date) -> list[tuple[int, date, date, int | None, str]]:
    """
    Splits [start, end] into (season, from, to, crop, crop source) pieces.

    Seasons are named by harvest year and run 1 Sep - 31 Aug (winter crops). Spring crops harvested
    after 1 September stay open longer (maize to 31 Dec, sugar beet to 30 Nov, potato to 31 Oct;
    engine.phenology.PROFILES): from 1 September such a crop of the previous season is still in the field
    until its harvest (or until the next crop's sowing, if that is a winter crop sown earlier), whichever
    season the Clock is in. Seasons after the current one are skipped: their crop is not known yet.
    """
    current = season_of(clock.today())
    out = []
    s = start
    while s <= end:
        season = season_of(s)
        s_end = min(end, season_bounds(season)[1])
        late_end = _late_crop_end(field, season, current) if s.month >= 9 else None
        if late_end and s <= late_end:  # last season's spring crop, not harvested yet
            seg_end = min(end, late_end)
            crop, source = season_crop(field, season - 1)
            out.append((season - 1, s, seg_end, crop, source))
            s = seg_end + timedelta(days=1)
            continue
        if season <= current:
            crop, source = season_crop(field, season)
            out.append((season, s, s_end, crop, source))
        s = s_end + timedelta(days=1)
    return out


def _late_crop_end(field: Field, season: int, current: int) -> date | None:
    """The last day last season's crop stays in the field after 1 September (None: it was harvested by then)."""
    prev, _ = season_crop(field, season - 1)
    if not prev or prev not in PROFILES or PROFILES[prev].winter:
        return None
    late = season_end(prev, season - 1)
    if late.month < 9:
        return None
    if season <= current:  # the next crop is known: a winter crop sown before that harvest takes the field from its sowing
        nxt, _ = season_crop(field, season)
        if nxt in PROFILES and PROFILES[nxt].winter and nxt != prev:
            m, d = PROFILES[nxt].sowing
            sow = date(season - 1, m, d)
            if sow <= late:
                late = sow - timedelta(days=1)
    return late if late >= date(season - 1, 9, 1) else None


def _field_rows(field: Field, threats: dict, start: date, end: date, now, reports=()) -> list[Risk]:
    out: list[Risk] = []
    for season, s, s_end, crop, source in crop_season_segments(field, start, end):
        rules = [r for r in rules_for_crop(crop) if r.code in threats] if crop else []
        missing = [r.code for r in rules_for_crop(crop) if r.code not in threats] if crop else []
        if missing:
            log.warning("predict: %d engine threat codes have no Threat row and are skipped (run engine_load_threats): %s",
                        len(missing), ", ".join(missing[:5]))
        if rules:
            out += _season_rows(field, threats, rules, season, s, s_end, now, reports, crop, source)
    return out


def _season_rows(field, threats, rules, season, start, end, now, reports=(), crop=None, crop_source="field") -> list[Risk]:
    grid = field.weather_grid_id
    today = _AS_OF.get() or clock.today()
    horizon = today + timedelta(days=clock.FORECAST_DAYS)
    load_start = min(start, season_bounds(season)[0])
    ctx = field_context(field, season, crop_code=crop, crop_source=crop_source)
    ctx.last_season = last_season_peaks(field, season)
    from engine.satellite import fieldndvi
    anchors = fieldndvi.phenology_anchors(fieldndvi.load(field, season), ctx.crop, season)
    s0, s1 = season_bounds(season)
    sow = OBS.sowing_override([r for r in reports if r.observed_on <= end], window=(s0 - timedelta(days=60), s1))

    out: list[Risk] = []
    # 1. days assessed "as of that day": up to today, and (demo precompute only) after today + 7
    any_as_of = start <= today or end > horizon
    daily = F.load_daily(grid, load_start, end) if any_as_of else pd.DataFrame()
    if not daily.empty:
        hourly = F.load_hourly(grid, load_start, end)
        span = pd.date_range(max(pd.Timestamp(start), daily.index.min()), min(pd.Timestamp(end), daily.index.max()), freq="D")
        days = span[(span <= pd.Timestamp(today)) | (span > pd.Timestamp(horizon))]
        if len(days):
            stages = _stages(ctx, daily, season, anchors, sow)
            out += _score(field, threats, rules, ctx, daily, hourly, stages, season, days, reports, now, today, forecast_from=None)

    # 2. coming days: weather observed up to today, then the forecast issued today
    c0, c1 = max(start, today + timedelta(days=1)), min(end, horizon)
    if c0 <= c1:
        obs = F.load_daily(grid, load_start, today)
        fc = F.load_forecast(grid, today)
        fc = fc[fc.index > pd.Timestamp(today)] if not fc.empty else fc
        if fc.empty:
            log.warning("predict: no forecast issued on %s for grid %s: no coming-day risks", today, grid)
        elif not obs.empty:
            daily_c = pd.concat([obs, fc])
            hourly_c = F.load_hourly(grid, load_start, today)  # the forecast is daily only: infection hours fall back to daily estimates
            days = pd.date_range(pd.Timestamp(c0), min(pd.Timestamp(c1), daily_c.index.max()), freq="D")
            if len(days):
                known = [a for a in anchors if a.detected_on <= today]  # no satellite scene after today
                stages = _stages(ctx, daily_c, season, known, sow)
                out += _score(field, threats, rules, ctx, daily_c, hourly_c, stages, season, days, reports, now, today, forecast_from=today)
    if not out and daily.empty and any_as_of:
        log.warning("predict: no daily weather for grid %s, %s..%s", grid, load_start, end)
    return out


def _stages(ctx, daily, season, anchors, sow):
    stages = calibrate(bbch_series(ctx.crop, daily["avg_temperature"], season), ctx.crop, anchors)
    if sow:  # the farmer's sowing date replaces the assumed one from the day it was reported
        told = bbch_series(ctx.crop, daily["avg_temperature"], season, sowing=sow[0])
        use = told.index >= pd.Timestamp(sow[1])
        stages = stages.copy()
        stages.loc[use] = told.loc[use]
    return stages


def _score(field, threats, rules, ctx, daily, hourly, stages, season, days, reports, now, today, forecast_from) -> list[Risk]:
    """Scores the rules on `days`. forecast_from: the forecast's issue day when these are coming days."""
    dd10 = degree_days_base10(daily["avg_temperature"], season)
    grid = field.weather_grid_id
    out = []
    forecast_cache: dict[date, pd.DataFrame] = {}
    for rule in rules:
        for res in score_rule(rule, ctx, daily, hourly, stages, dd10, days, reports):
            lead = (res.day - today).days
            if forecast_from is not None:  # a coming day: its weather is the forecast, less certain the further ahead
                adjust_for_lead(res.explanation, lead, forecast_from)
            if res.explanation["action"]["type"] == "treat":
                fc = forecast_cache.get(res.day)
                if fc is None:
                    fc = _forecast(grid, res.day, forecast_from)  # as-of days: the forecast known that day
                    forecast_cache[res.day] = fc
                res.explanation["action"]["spray_window"] = spray_window(fc)
            out.append(Risk(field=field, threat=threats[rule.code], date=res.day, score=res.score,
                            explanation=res.explanation, computed_at=now))
    return out


LEAD_NOTE = "Dzień +"  # prefix of the forecast note on coming days
FORECAST_CONFIDENCE_DROP = 0.06  # per day ahead (team assumption): day +7 keeps 58 % of the confidence


def adjust_for_lead(expl: dict, lead: int, issued_on: date | None = None) -> dict:
    """Confidence of a day `lead` days after today (weather from the forecast issued today). Idempotent."""
    base = expl.get("confidence_observed", expl["confidence"])
    expl["confidence_observed"] = base
    expl["forecast_lead_days"] = lead
    if issued_on is not None:
        expl["forecast_issued_on"] = issued_on.isoformat()
    expl["confidence"] = round(base * max(0.4, 1 - FORECAST_CONFIDENCE_DROP * lead), 2)
    note = (f"{LEAD_NOTE}{lead}: pogoda po dzisiejszym dniu pochodzi z prognozy wydanej dziś (wartości dobowe), "
            "więc ryzyko to projekcja i jest mniej pewne.")
    expl["notes"] = [n for n in expl.get("notes", []) if not n.startswith(LEAD_NOTE)] + [note]
    return expl


def last_season_peaks(field: Field, season: int) -> dict:
    """Peak risk per threat on this field in the previous season (from earlier predict() runs)."""
    from django.db.models import Max

    s0, s1 = season_bounds(season - 1)
    peaks = {}
    rows = (Risk.objects.filter(field=field, date__range=(s0, s1)).values("threat__code", "threat__name")
            .annotate(peak=Max("score")))
    by_code = {r["threat__code"]: r for r in rows}
    for code, sources in CARRYOVER.items():
        best = max((by_code[c] for c in sources if c in by_code), key=lambda r: r["peak"], default=None)
        if best:
            day = Risk.objects.filter(field=field, threat__code=best["threat__code"], date__range=(s0, s1),
                                      score=best["peak"]).values_list("date", flat=True).first()
            peaks[code] = {"peak": best["peak"], "date": day.isoformat() if day else None, "threat": best["threat__name"]}
    return peaks


def _forecast(grid: str, day: date, today: date | None = None) -> pd.DataFrame:
    """
    The forecast for the days after `day`, as known on `day`; for a coming day (after today) that is the
    forecast issued today, never one issued in the future.
    """
    issued = min(day, today) if today else day  # today = the issue day of a coming day; None = as of `day`
    cols = ["date", "max_temperature", "min_temperature", "total_precipitation", "avg_wind_speed", "avg_relative_humidity"]
    qs = (WeatherForecastDaily.objects.current(as_of=issued).filter(grid_id=grid, date__gt=day)
          .order_by("date").values(*cols))
    df = pd.DataFrame.from_records(qs, columns=cols)
    return df.set_index("date") if not df.empty else df


__all__ = ["predict", "clock_moved", "precompute_season", "precompute_dates", "PredictResult", "compute_rows", "what_if", "farm_spread", "adjust_for_lead", "field_context", "RULES"]
