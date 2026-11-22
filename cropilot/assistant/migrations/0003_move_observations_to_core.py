"""Move the interim assistant.Observation rows to core.Observation (the interim table stays, empty).

docs/interfaces.md -> Writing observations: the engine reads both tables, so rows in both would count
twice; the assistant switches its tool and moves (copies, then deletes) its rows in one change.
"""
from django.db import migrations

CATEGORY = {"choroba": "disease", "szkodnik": "pest", "chwasty": "weeds", "uszkodzenie": "damage", "inne": "other"}
SEVERITY = {"niskie": 0.3, "srednie": 0.6, "wysokie": 0.9}
DEFAULT_KIND = {"choroba": "symptoms", "szkodnik": "symptoms", "uszkodzenie": "event", "chwasty": "symptoms",
                "inne": "symptoms"}
DETAIL_KEYS = ("sowing_date", "tillage", "resistant_to", "type", "scope")


def forward(apps, schema_editor):
    Interim = apps.get_model("assistant", "Observation")
    Core = apps.get_model("core", "Observation")
    for o in Interim.objects.all().order_by("id"):
        raw = o.details or {}
        merged = {**(raw.get("draft") or {}), **{k: v for k, v in raw.items() if k != "draft"}}
        kind = merged.get("kind") or DEFAULT_KIND.get(o.category, "symptoms")
        dist = merged.get("distance_m")
        details = {k: v for k, v in merged.items() if k in DETAIL_KEYS and v not in (None, "")}
        details |= {k: raw[k] for k in ("source", "draft", "reassessment") if k in raw}
        details |= {"moved_from": "assistant.Observation", "interim_id": o.id,
                    **({"conversation_id": o.conversation_id} if o.conversation_id else {})}
        key = o.idempotency_key
        if Core.objects.filter(idempotency_key=key).exists():
            continue  # already moved
        Core.objects.create(field_id=o.field_id, observed_on=o.date, kind=kind, category=CATEGORY.get(o.category, "other"),
                            threat_id=o.threat_id, severity=SEVERITY.get(o.severity or ""),
                            distance_m=float(dist) if dist not in (None, "") else None,
                            details=details, text=o.note, idempotency_key=key)
    Interim.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0002_observation_and_state"),
        ("core", "0002_observation_and_soil_formats"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
