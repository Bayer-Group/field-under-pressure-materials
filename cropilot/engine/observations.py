"""
Farmer reports (from the chat) and how they change a field's risks.

Reports are read from the database: `core.Observation` (the agreed home, columns in engine/README.md)
and, until that exists, the chat's interim `assistant.Observation` (mapped in `_from_assistant`). Tests
and demos can pass reports to predict(observations=[...]) directly.

Every report only affects days on or after the day it was observed (the "as of that day" rule), and
every applied report becomes a driver in the explanation, with its effect on the score.

Kinds:
- symptoms   the farmer sees the threat on this field -> score floor (0.66 + 0.3 x severity: always "high"), fading after 10 days;
             without a threat code: x(1 + 0.3 x severity) for every threat of that group (disease / pest)
- absence    inspected, nothing found -> x0.5, back to normal over 10 days (threat_code empty = all threats)
- neighbour  a neighbour / the area has it -> x(1 + 0.5 x closeness), fading over 21 days and 3 km;
             without a threat code: x(1 + 0.25 x closeness) for every threat of that group (disease / pest)
- treatment  sprayed against it -> x0.3 for 14 days, back to normal by day 21 (threat_code empty = all fungal)
- field_fact details: sowing_date (replaces the assumed one), tillage ("plough" / "reduced"),
             resistant_to ([threat codes] -> x0.6)
- event      details.type (or details.event; else guessed from the text; else "damage": fungal x1.1): hail (fungal x1.3, 14 days), lodging (fungal x1.2, 21 days), flood (crazy top floor 0.7)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

KINDS = ("symptoms", "absence", "neighbour", "treatment", "field_fact", "event")


@dataclass
class Report:
    observed_on: date
    kind: str
    threat_code: str | None = None
    severity: float | None = None     # 0-1
    distance_m: float | None = None   # neighbour reports
    details: dict = field(default_factory=dict)
    text: str = ""
    field_id: int | None = None       # None = whole farm / the area
    id: int | None = None
    group: str | None = None          # "disease" / "pest": threat group of a report without a threat code

    def label(self) -> str:
        """The report in one Polish sentence (shown to the farmer in the explanation)."""
        from engine.catalog import RULES
        d = self.observed_on.isoformat()
        when = f"{d[8:10]}.{d[5:7]}.{d[:4]}"
        rule = RULES.get(self.threat_code or "")
        what = rule.name_pl if rule else (self.threat_code or "wszystkie zagrożenia")
        quote = f": „{self.text}”" if self.text else ""
        if self.kind == "symptoms" and not rule and self.group:
            return f"Rolnik zgłosił {'szkodnika' if self.group == 'pest' else 'chorobę'} na tym polu ({when})" + quote
        if self.kind == "symptoms":
            return f"Rolnik zgłosił na tym polu: {what} ({when})" + (f", nasilenie {self.severity:.0%}" if self.severity is not None else "")
        if self.kind == "absence":
            return f"Rolnik obejrzał pole ({when}) i nie znalazł " + (f"objawów: {what}" if self.threat_code else "objawów")
        if self.kind == "neighbour" and not rule and self.group:
            what = "szkodniki" if self.group == "pest" else "choroby"
        if self.kind == "neighbour":
            where = f" ok. {self.distance_m:.0f} m stąd" if self.distance_m else " w pobliżu"
            return f"Zgłoszono {what}{where} ({when}); zarodniki lub szkodniki mogą przejść na to pole"
        if self.kind == "treatment":
            return f"Zabieg przeciw: {what if rule else 'choroby grzybowe (wszystkie)'} ({when})"
        if self.kind == "event":
            kind = str(self.details.get("type") or self.details.get("event") or "damage")
            name = EVENT_PL.get(kind, kind.capitalize())
            return f"{name} – zgłoszenie z {when}" + quote
        facts = ", ".join(f"{FACT_PL.get(k, k)}: {FACT_VALUE_PL.get(str(v), v)}" for k, v in self.details.items() if k != "source")
        if self.details.get("source") == "field_record":
            return f"Dane z karty pola: {facts}"
        return f"Informacja od rolnika ({when}): {facts}"


EVENT_PL = {"damage": "Uszkodzenie uprawy (rodzaj nieznany)", "hail": "Grad", "lodging": "Wyleganie", "flood": "Zalanie",
            "frost": "Przymrozek", "drought": "Susza"}
FACT_PL = {"sowing_date": "data siewu", "tillage": "uprawa roli", "resistant_to": "odporność na", "kind": "rodzaj"}
FACT_VALUE_PL = {"reduced": "uproszczona", "plough": "orka"}


SEVERITY_WORDS = {"niskie": 0.3, "niska": 0.3, "low": 0.3, "srednie": 0.6, "średnie": 0.6, "srednia": 0.6, "średnia": 0.6,
                  "medium": 0.6, "wysokie": 0.9, "wysoka": 0.9, "high": 0.9}
ASSISTANT_SEVERITY = SEVERITY_WORDS  # kept for compatibility
CATEGORY_KIND = {"choroba": "symptoms", "szkodnik": "symptoms", "uszkodzenie": "event",
                 "disease": "symptoms", "pest": "symptoms", "damage": "event"}
ASSISTANT_GROUP = {"choroba": "disease", "szkodnik": "pest", "disease": "disease", "pest": "pest"}
DISEASE_CATEGORIES = ("fungal", "bacterial", "viral")
DEFAULT_SEVERITY = 0.5  # a symptoms report that does not say how bad
EVENT_WORDS = (("hail", ("grad",)), ("lodging", ("wylegl", "wyległ", "polegl", "położ")),
               ("flood", ("zalan", "zalał", "powód", "podtop", "stoi woda")))
DETAIL_KEYS = ("sowing_date", "tillage", "resistant_to", "type", "event", "scope")


def _severity(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(min(max(v, 0.0), 1.0))
    return SEVERITY_WORDS.get(str(v).strip().lower())


def _to_report(r, date_field: str) -> Report | None:
    """
    One observation row -> Report, whatever the table looks like: the proposed core.Observation columns
    (observed_on, kind, threat_code, severity 0-1, distance_m, details, text) or the chat's interim
    assistant.Observation (date, category, threat FK, severity niskie/srednie/wysokie, note, details).
    A row whose kind cannot be told is skipped (logged), never guessed as "symptoms".
    """
    raw = getattr(r, "details", None) or {}
    d = {**(raw.get("draft") or {}), **{k: v for k, v in raw.items() if k not in ("draft", "reassessment")}}
    category = (getattr(r, "category", "") or "").lower()
    kind = getattr(r, "kind", None) or d.get("kind") or CATEGORY_KIND.get(category)
    if kind not in KINDS:
        log.warning("observation %s skipped: unknown kind %r (category %r); set kind or details.kind", r.pk, kind, category)
        return None
    code = getattr(r, "threat_code", None) or None
    if code is None and getattr(r, "threat_id", None):
        code = r.threat.code
    sev = _severity(getattr(r, "severity", None))
    if kind == "symptoms" and sev is None:
        sev = DEFAULT_SEVERITY
    text = getattr(r, "text", None) or getattr(r, "note", None) or ""
    details = {k: v for k, v in d.items() if k in DETAIL_KEYS}
    if kind == "event" and not (details.get("type") or details.get("event")):
        low = text.lower()
        details["type"] = next((t for t, words in EVENT_WORDS if any(w in low for w in words)), "damage")
    dist = getattr(r, "distance_m", None)
    dist = d.get("distance_m") if dist in (None, "") else dist
    return Report(
        observed_on=getattr(r, date_field), kind=kind, threat_code=code, severity=sev,
        distance_m=float(dist) if dist not in (None, "") else (1000.0 if kind == "neighbour" else None),
        details=details, text=text, field_id=None if d.get("scope") == "farm" else r.field_id, id=r.pk,
        group=ASSISTANT_GROUP.get(category),
    )


def _from_core(r) -> Report | None:
    return _to_report(r, "observed_on" if hasattr(r, "observed_on") else "date")


def _from_assistant(r) -> Report | None:
    return _to_report(r, "date")


def _date_field(model) -> str | None:
    names = {f.name for f in model._meta.get_fields()}
    return next((n for n in ("observed_on", "date") if n in names), None)


def _query(end: date, field_id: int | None = None) -> list[Report]:
    from django.apps import apps

    out: list[Report] = []
    core_keys: set[str] = set()
    for app in ("core", "assistant"):  # core.Observation (agreed home) and the chat's interim table
        try:
            model = apps.get_model(app, "Observation")
        except LookupError:
            continue
        date_field = _date_field(model)
        if date_field is None:
            log.warning("%s.Observation has no observed_on / date column: its reports are ignored", app)
            continue
        names = {f.name for f in model._meta.get_fields()}
        q = model.objects.filter(**{f"{date_field}__lte": end})
        if "threat" in names:
            q = q.select_related("threat")
        rows = list(q)
        if "idempotency_key" in names:
            if app == "core":
                core_keys = {r.idempotency_key for r in rows if r.idempotency_key}
            else:  # an interim row already moved to core.Observation must count once
                rows = [r for r in rows if not (r.idempotency_key and r.idempotency_key in core_keys)]
        reports = [x for x in (_to_report(r, date_field) for r in rows) if x is not None]
        out += for_field(reports, field_id) if field_id is not None else reports
    return out


def load(field_id: int, start: date, end: date) -> list[Report]:
    """Reports for a field (and farm-wide ones) observed up to `end`."""
    return _query(end, field_id)


def load_all(start: date, end: date) -> list[Report]:
    """All reports of the farm observed up to `end`."""
    return _query(end)


FIELD_FACT_COLUMNS = ("sowing_date", "tillage", "resistant_to")
def known_since() -> date:
    """
    A fact stored on the field has no report date: it holds from the start of the current season, so a
    resistant variety or a tillage change sown this season does not rewrite last season's risks.
    """
    from core import clock
    from engine.satellite.season import season_bounds, season_of

    return season_bounds(season_of(clock.today()))[0]


def from_field(field) -> list[Report]:
    """
    Facts stored on the field itself (proposed columns Field.sowing_date, Field.tillage, Field.resistant_to,
    written by the assistant when the farmer confirms them). Read only if the columns exist; each becomes a
    field_fact report, so it is explained like a farmer report. Sowing dates apply only to their own season.
    """
    out = []
    for col in FIELD_FACT_COLUMNS:
        v = getattr(field, col, None)
        if v in (None, "", [], ()):
            continue
        if col == "sowing_date":
            v = v if isinstance(v, date) else date.fromisoformat(str(v))
            out.append(Report(observed_on=v, kind="field_fact", details={"sowing_date": v, "source": "field_record"}, field_id=field.id))
        else:
            out.append(Report(observed_on=known_since(), kind="field_fact", details={col: v, "source": "field_record"}, field_id=field.id))
    return out


def for_field(reports: list[Report] | None, field_id: int) -> list[Report]:
    return [r for r in (reports or []) if r.field_id in (None, field_id)]


def sowing_override(reports: list[Report], window: tuple[date, date] | None = None) -> tuple[date, date] | None:
    """(sowing_date, reported_on) from the latest field_fact with a sowing date (inside `window` if given)."""
    facts = []
    for r in reports:
        sd = r.details.get("sowing_date") if r.kind == "field_fact" else None
        if not sd:
            continue
        sd = sd if isinstance(sd, date) else date.fromisoformat(str(sd))
        if window is None or window[0] <= sd <= window[1]:
            facts.append((sd, r.observed_on))
    return max(facts, key=lambda x: x[1]) if facts else None


def _age(days: pd.DatetimeIndex, on: date) -> np.ndarray:
    """Days since the report (NaN before it: the report is not known yet)."""
    a = (days - pd.Timestamp(on)).days.to_numpy().astype(float)
    a[a < 0] = np.nan
    return a


def _fade(age: np.ndarray, full: float, gone: float) -> np.ndarray:
    """1 for age <= full, linear to 0 at age = gone, 0 before the report (NaN)."""
    w = np.clip(1 - (age - full) / max(gone - full, 1e-9), 0, 1)
    return np.nan_to_num(w, nan=0.0)


@dataclass
class Effect:
    report: Report
    mult: np.ndarray        # multiplier per day (1 = no effect)
    floor: np.ndarray       # minimum score per day (0 = no effect)
    after: np.ndarray       # multiplier applied after the floor (treatments)


def effects(rule, reports: list[Report], days: pd.DatetimeIndex) -> list[Effect]:
    """The effects of the reports on one threat rule, per day."""
    n = len(days)
    one, zero = np.ones(n), np.zeros(n)
    out = []
    for r in reports:
        age = _age(days, r.observed_on)
        known = ~np.isnan(age)
        if not known.any():
            continue
        same = r.threat_code == rule.code
        mult, floor, after = one.copy(), zero.copy(), one.copy()
        if r.kind == "symptoms" and r.threat_code is None and r.group:
            hit = (rule.category == "pest") if r.group == "pest" else (rule.category in DISEASE_CATEGORIES)
            if not hit:
                continue
            sev = 0.5 if r.severity is None else float(r.severity)
            mult = 1 + 0.3 * sev * _fade(age, 10, 21)
        elif r.kind == "symptoms" and same:
            sev = DEFAULT_SEVERITY if r.severity is None else float(r.severity)
            floor = min(1.0, 0.66 + 0.3 * sev) * _fade(age, 10, 21)
        elif r.kind == "absence" and (same or r.threat_code is None):
            mult = 1 - 0.5 * _fade(age, 0, 10)
        elif r.kind == "neighbour" and same:
            close = 1.0 if not r.distance_m else float(np.clip(1 - (r.distance_m - 500) / 2500, 0, 1))
            mult = 1 + 0.5 * close * _fade(age, 7, 21)
        elif r.kind == "neighbour" and r.threat_code is None and r.group:  # "the neighbour has pests", no name
            hit = (rule.category == "pest") if r.group == "pest" else (rule.category in DISEASE_CATEGORIES)
            if not hit:
                continue
            close = 1.0 if not r.distance_m else float(np.clip(1 - (r.distance_m - 500) / 2500, 0, 1))
            mult = 1 + 0.25 * close * _fade(age, 7, 21)  # half of a named threat: we don't know which one
        elif r.kind == "treatment" and (same or (r.threat_code is None and rule.category == "fungal")):
            after = 1 - 0.7 * _fade(age, 14, 21)
        elif r.kind == "field_fact":
            if r.details.get("tillage") == "reduced" and rule.code in ("wheat.fusarium_head_blight", "maize.fusarium_ear_rot",
                                                                      "maize.european_corn_borer", "wheat.tan_spot"):
                mult = np.where(known, 1.3, 1.0)
            if rule.code in (r.details.get("resistant_to") or []):
                mult = mult * np.where(known, 0.6, 1.0)
        elif r.kind == "event":
            t = r.details.get("type") or r.details.get("event")
            if t == "hail" and rule.category in ("fungal", "bacterial"):
                mult = 1 + 0.3 * _fade(age, 7, 14)
            elif t == "lodging" and rule.category == "fungal":
                mult = 1 + 0.2 * _fade(age, 14, 21)
            elif t == "flood" and rule.code == "maize.crazy_top":
                floor = 0.7 * _fade(age, 14, 28)
            elif t == "damage" and rule.category in ("fungal", "bacterial"):  # damage of unknown type: wounds let pathogens in
                mult = 1 + 0.1 * _fade(age, 7, 14)
        if np.allclose(mult, 1) and not floor.any() and np.allclose(after, 1):
            continue
        out.append(Effect(r, mult, floor, after))
    return out


def combine(base: np.ndarray, effs: list[Effect], skip: int | None = None) -> np.ndarray:
    """score = (min(1, base x multipliers) floored by symptom reports) x treatments; `skip` leaves one out."""
    s = np.asarray(base, dtype=float).copy()
    floor = np.zeros_like(s)
    after = np.ones_like(s)
    for i, e in enumerate(effs):
        if i == skip:
            continue
        s = s * e.mult
        floor = np.maximum(floor, e.floor)
        after = after * e.after
    return np.clip(np.maximum(np.minimum(s, 1.0), floor) * after, 0, 1)
