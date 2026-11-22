"""
The engine's own cache (not farm data: nothing outside the engine reads it, and dropping it only makes the
next date move slower).

RiskSnapshot holds ready-made Risk rows so that moving the demo date copies rows instead of computing them:

    issued_on = None    the field's risks on `date`, assessed as of that day (what Risk holds for past days)
    issued_on = D       the field's risks on `date` as a coming day of demo date D (forecast issued on D)

clock_moved(old, new) copies, for every day it has to rewrite, the "as of" bundle or the bundle issued on
`new`; it computes only what is missing. predict() drops a field's bundles from its `start` on (a report or a
crop change makes them stale) and stores what it computed; engine.precompute_dates() fills the rest ahead.
"""

from django.db import models

from core.models import Field


class RiskSnapshot(models.Model):
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="+")
    date = models.DateField(help_text="The day the risks apply to.")
    issued_on = models.DateField(null=True, blank=True,
                                 help_text="Empty: as of that day. Else: a coming day of this demo date (its forecast).")
    season = models.IntegerField(help_text="Season of the demo date when computed (crop and field facts depend on it).")
    rows = models.JSONField(help_text='[{"threat_id", "score", "explanation"}], one per threat; [] = no risks that day.')

    class Meta:
        constraints = [models.UniqueConstraint(fields=["field", "date", "issued_on", "season"], nulls_distinct=False,
                                               name="engine_snapshot_unique")]
        indexes = [models.Index(fields=["season", "date"], name="engine_snapshot_season_date")]

    def __str__(self) -> str:
        return f"{self.field_id} · {self.date} · {self.issued_on or 'as of'}"
