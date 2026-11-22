"""
python manage.py engine_load_threats [--overwrite]

Creates the Threat rows the engine has rules for (engine/catalog.py), by code, and the CropClass rows
of the engine's crops if they are missing. Safe on top of the platform's own Threat fixture:
- a row with an engine code that already exists is left as it is (name, texts, source are the
  platform's); only a wrong crop or category is reported, not changed. --overwrite rewrites them.
- rows with other codes are untouched; they get no risks (listed as a warning).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import CropClass, Threat
from engine.catalog import CROP_NAMES, RULES


def _defaults(rule) -> dict:
    temp_text = f"{rule.temp_min:g}-{rule.temp_max:g}" if rule.temp_min is not None else ""
    return {"crop_id": rule.crop, "name": rule.name_pl, "category": rule.category,
            "temperature_text": temp_text, "temp_min_c": rule.temp_min, "temp_max_c": rule.temp_max,
            "humidity_text": "", "other_factors": " ".join(rule.notes),
            "growth_stage_text": f"BBCH {rule.stage_min}-{rule.stage_max}", "source": "engine rules"}


class Command(BaseCommand):
    help = "Create the Threat rows for every rule in engine/catalog.py (existing rows kept unless --overwrite)."

    def add_arguments(self, parser):
        parser.add_argument("--overwrite", action="store_true", help="Rewrite existing rows with the engine's texts.")

    @transaction.atomic
    def handle(self, *args, overwrite=False, **opts):
        for code, name in CROP_NAMES.items():
            CropClass.objects.get_or_create(code=code, defaults={"name": name})
        created = kept = updated = 0
        for rule in RULES.values():
            row = Threat.objects.filter(code=rule.code).first()
            if row is None:
                Threat.objects.create(code=rule.code, **_defaults(rule))
                created += 1
            elif overwrite:
                for k, v in _defaults(rule).items():
                    setattr(row, k, v)
                row.save()
                updated += 1
            else:
                kept += 1
                if row.crop_id != rule.crop or row.category != rule.category:
                    self.stdout.write(self.style.WARNING(
                        f"{rule.code}: platform row has crop {row.crop_id} / {row.category}, the rule {rule.crop} / {rule.category} (kept)"))
        others = Threat.objects.exclude(code__in=list(RULES)).values_list("code", flat=True)
        if others:
            self.stdout.write(self.style.WARNING(f"{len(others)} Threat rows have no engine rule (no risks): {', '.join(sorted(others)[:8])}"))
        self.stdout.write(self.style.SUCCESS(f"Threats: {created} created, {updated} overwritten, {kept} kept."))
