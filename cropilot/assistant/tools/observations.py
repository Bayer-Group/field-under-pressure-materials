"""
record_observation: write a farmer's report to core.Observation, then ask the engine to reassess.

Only after the user confirmed a draft (orchestrator flow / MCP `confirm=true`). Idempotent by
`idempotency_key`. Columns and meanings: docs/database.md -> Observation. An engine failure does not
undo the report (reassessment.status = "failed" / "unavailable").

The chat speaks Polish (choroba, niskie…); core.Observation stores the contract values
(disease, 0.3…): the mapping is here, in one place.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from pydantic import BaseModel, Field

from assistant import domain
from .platform import _field, season_today
from .registry import ToolError, register

log = logging.getLogger("assistant.tools")

Category = Literal["choroba", "szkodnik", "chwasty", "uszkodzenie", "inne",
                   "disease", "pest", "weeds", "damage", "other"]
Severity = Literal["niskie", "srednie", "wysokie"]
Kind = Literal["symptoms", "absence", "neighbour", "treatment", "field_fact", "event"]

# Polish chat values -> core.Observation contract values
CATEGORY_TO_CORE = {"choroba": "disease", "szkodnik": "pest", "chwasty": "weeds", "uszkodzenie": "damage",
                    "inne": "other", "disease": "disease", "pest": "pest", "weeds": "weeds", "damage": "damage",
                    "other": "other"}
CATEGORY_PL = {"disease": "choroba", "pest": "szkodnik", "weeds": "chwasty", "damage": "uszkodzenie", "other": "inne"}
SEVERITY_TO_CORE = {"niskie": 0.3, "srednie": 0.6, "wysokie": 0.9}
SEVERITY_PL = [(0.45, "niskie"), (0.75, "srednie"), (1.01, "wysokie")]
DEFAULT_KIND = {"disease": "symptoms", "pest": "symptoms", "damage": "event", "weeds": "symptoms", "other": "symptoms"}
DETAIL_KEYS = ("sowing_date", "tillage", "resistant_to", "type", "scope")  # what the engine reads from details


def engine_predict():
    """engine.predict(field_ids=..., start=..., end=...) if the engine exists, else None."""
    for mod, attr in (("engine", "predict"), ("engine.predict", "predict"), ("engine.engine", "predict")):
        try:
            m = __import__(mod, fromlist=[attr])
            fn = getattr(m, attr, None)
            if callable(fn):
                return fn
        except ImportError:
            continue
    return None


def field_levels(field, day: dt.date) -> dict[str, dict]:
    from core.models import Risk
    return {r.threat.code: {"threat": r.threat.name, "score": round(r.score, 2),
                            "level": domain.level_from_explanation(r.explanation, r.score)[1]}
            for r in Risk.objects.filter(field=field, date=day).select_related("threat")}


def severity_pl(value: float | None) -> str | None:
    if value is None:
        return None
    return next(label for upper, label in SEVERITY_PL if value < upper)


class ObservationIn(BaseModel):
    field_id: int
    date: dt.date | None = Field(None, description="Dzień obserwacji (kiedy rolnik to zobaczył/zrobił); domyślnie dziś.")
    category: Category
    threat: str | None = Field(None, description="Kod lub nazwa zagrożenia (opcjonalnie).")
    severity: Severity | None = None
    note: str = Field(description="Opis rolnika jego słowami.")
    idempotency_key: str = Field(min_length=8, max_length=64)
    kind: Kind | None = Field(None, description="symptoms (widzę objawy; domyślnie) | absence (sprawdziłem, czysto) | "
                                                "neighbour (u sąsiada) | treatment (wykonałem zabieg) | field_fact (fakt o polu: "
                                                "data siewu, uprawa) | event (grad, wyleganie, zalanie)")
    facts: dict | None = Field(None, description="Dla silnika: sowing_date (YYYY-MM-DD), tillage (reduced|plough), "
                                                 "distance_m (sąsiad), type (hail|lodging|flood), scope (farm)")


def resolve_draft(field_id, date, category, threat, severity, note) -> dict:
    """Validate an observation draft without saving (also the MCP dry run)."""
    f = _field(field_id)
    today = season_today()
    d = date or today
    if d > today:
        raise ToolError(f"Data obserwacji {d} jest w przyszłości (dziś w sezonie: {today}).")
    t = domain.threat_by_code_or_name(threat, f.crop_id) if threat else None
    return {"field_id": f.id, "field": f.name, "crop": domain.crop_pl(f.crop_id), "date": d,
            "category": CATEGORY_PL.get(CATEGORY_TO_CORE.get(category, ""), category),
            "threat_code": t.code if t else None, "threat": t.name if t else None,
            "threat_unrecognized": bool(threat and not t), "severity": severity, "note": note}


@register("record_observation", """
Zapisuje zgłoszenie rolnika (objawy, „sprawdziłem — czysto”, sąsiad ma, wykonany zabieg, fakt o polu,
grad/wyleganie/zalanie) i uruchamia ponowną ocenę ryzyka pola przez silnik. ZAPIS: wolno wywołać tylko
po tym, jak użytkownik zobaczył szkic i potwierdził. Ten sam idempotency_key nie tworzy duplikatu.
Zwraca id zgłoszenia i zmianę ryzyka (przed/po) dla pola na dziś.
""", ObservationIn, writes=True, agent_visible=False)
def record_observation(field_id, date, category, threat, severity, note, idempotency_key, kind=None, facts=None) -> dict:
    from django.db import transaction

    from core.models import Observation, Threat

    existing = Observation.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return {"observation_id": existing.id, "created": False, "draft": None,
                "reassessment": existing.details.get("reassessment", {"status": "skipped"})}
    draft = resolve_draft(field_id, date, category, threat, severity, note)
    f = _field(field_id)
    today = season_today()
    before = field_levels(f, today)
    core_category = CATEGORY_TO_CORE[category]
    facts = {k: v for k, v in (facts or {}).items() if v not in (None, "")}
    details = {k: v for k, v in facts.items() if k in DETAIL_KEYS}
    details |= {"source": "assistant", "draft": {k: str(v) if isinstance(v, dt.date) else v for k, v in draft.items()}}
    with transaction.atomic():
        obs, created = Observation.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={"field": f, "observed_on": draft["date"], "kind": kind or DEFAULT_KIND[core_category],
                      "category": core_category,
                      "threat": Threat.objects.filter(code=draft["threat_code"]).first() if draft["threat_code"] else None,
                      "severity": SEVERITY_TO_CORE.get(severity or ""),
                      "distance_m": float(facts["distance_m"]) if facts.get("distance_m") is not None else None,
                      "details": details, "text": note})
    if not created:
        return {"observation_id": obs.id, "created": False, "draft": draft,
                "reassessment": obs.details.get("reassessment", {"status": "skipped"})}

    predict = engine_predict()
    if predict is None:
        reassessment = {"status": "unavailable", "message": "Silnik decyzyjny nie jest jeszcze dostępny.",
                        "before": before, "after": before}
    else:
        try:
            from django.utils import timezone

            from core.models import Risk
            t0 = timezone.now()
            # default end = the later of today + 7 and the last stored day (engine contract), so the
            # precomputed rest of the season gets the report too
            rows = predict(field_ids=[f.id], start=draft["date"])
            after = field_levels(f, today)
            changed = {c: {"before": before.get(c), "after": a} for c, a in after.items()
                       if before.get(c, {}).get("score") != a["score"]}
            # PredictResult.field_ids: every field rewritten, incl. nearby fields a symptoms report spread to
            recomputed = sorted(getattr(rows, "field_ids", None) or
                                set(Risk.objects.filter(computed_at__gte=t0).values_list("field_id", flat=True))) or [f.id]
            reassessment = {"status": "ok", "rows_written": int(rows), "before": before, "after": after, "changed": changed,
                            "recomputed_field_ids": recomputed}
        except Exception as e:  # noqa: BLE001 - the report stays saved
            log.exception("engine.predict failed after observation %s", obs.id)
            reassessment = {"status": "failed", "message": f"Ponowna ocena ryzyka nie powiodła się: {e}",
                            "before": before, "after": before}
    obs.details = obs.details | {"reassessment": {k: v for k, v in reassessment.items()
                                                  if k in ("status", "message", "rows_written", "recomputed_field_ids")}}
    obs.save(update_fields=["details"])
    return {"observation_id": obs.id, "created": True, "draft": draft, "reassessment": reassessment}
