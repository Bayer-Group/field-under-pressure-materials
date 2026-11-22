"""
Response shapes of the platform API (docs/interfaces.md -> Platform API).

Every response has a named serializer, so /api/schema/ (and the TypeScript types generated from it,
frontend/src/api/schema.d.ts) describes it exactly. The views build plain dicts and render them
through these serializers.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.models import Threat

# Risk levels of explanation version 1 (docs/database.md -> Explanation, version 1).
LEVEL_CHOICES = [("low", "low"), ("medium", "medium"), ("high", "high")]
LOW_MAX, MEDIUM_MAX = 0.33, 0.66  # low < 0.33 <= medium < 0.66 <= high


def level_of(score: float, explanation) -> str:
    """The row's level: explanation.level when it is a known level, otherwise from the score (cut-offs)."""
    level = explanation.get("level") if isinstance(explanation, dict) else None
    if level in {"low", "medium", "high"}:
        return level
    return "low" if score < LOW_MAX else "medium" if score < MEDIUM_MAX else "high"


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


# --- Clock ------------------------------------------------------------------------------------


class ClockSerializer(serializers.Serializer):
    today = serializers.DateField()
    forecast_days = serializers.IntegerField()
    min_date = serializers.DateField(allow_null=True, help_text="First demo date PUT accepts (null: no limit).")
    max_date = serializers.DateField(allow_null=True, help_text="Last demo date PUT accepts (null: no limit).")


class ClockUpdateSerializer(serializers.Serializer):
    today = serializers.DateField()


# --- Threats ----------------------------------------------------------------------------------


class CropRefSerializer(serializers.Serializer):
    code = serializers.IntegerField()
    name = serializers.CharField()


class ThreatSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    crop = CropRefSerializer()
    category = serializers.ChoiceField(choices=Threat.Category.choices)


# --- Fields -----------------------------------------------------------------------------------

POSITION = {"type": "array", "items": {"type": "number"}, "minItems": 2, "description": "[lon, lat]"}
RING = {"type": "array", "items": POSITION}
POLYGON = {"type": "array", "items": RING}


@extend_schema_field(
    {
        "oneOf": [
            {
                "type": "object",
                "properties": {"type": {"type": "string", "enum": ["Polygon"]}, "coordinates": POLYGON},
                "required": ["type", "coordinates"],
            },
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["MultiPolygon"]},
                    "coordinates": {"type": "array", "items": POLYGON},
                },
                "required": ["type", "coordinates"],
            },
        ],
        "description": "GeoJSON Polygon or MultiPolygon, EPSG:4326, coordinates [lon, lat].",
    }
)
class GeometryField(serializers.JSONField):
    pass


class FieldPropertiesSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    crop = CropRefSerializer()
    area_ha = serializers.FloatField()


class FieldFeatureSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["Feature"])
    id = serializers.IntegerField()
    geometry = GeometryField()
    properties = FieldPropertiesSerializer()


class FieldFeatureCollectionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["FeatureCollection"])
    features = FieldFeatureSerializer(many=True)


class LatLonSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class CropShareSerializer(serializers.Serializer):
    code = serializers.IntegerField()
    name = serializers.CharField()
    share = serializers.FloatField(help_text="[fraction 0-1]")


class CropYearSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    classes = CropShareSerializer(many=True, help_text="By share, largest first.")


class SoilSerializer(serializers.Serializer):
    """Root-zone columns of SoilCell, averaged over the field's cells, in the database's units."""

    ph = serializers.FloatField(allow_null=True, help_text="[pH] root zone to 15 cm")
    soil_texture = serializers.CharField(allow_null=True, help_text="USDA texture class: the most common one")
    clay = serializers.FloatField(allow_null=True, help_text="[fraction 0-1]")
    sand = serializers.FloatField(allow_null=True, help_text="[fraction 0-1]")
    silt = serializers.FloatField(allow_null=True, help_text="[fraction 0-1]")
    om = serializers.FloatField(allow_null=True, help_text="[g/kg] organic matter")
    cec = serializers.FloatField(allow_null=True, help_text="[cmol(c)/kg]")
    bulk_density = serializers.FloatField(allow_null=True, help_text="[kg/dm³]")


class FieldDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    crop = CropRefSerializer()
    area_ha = serializers.FloatField()
    centroid = LatLonSerializer()
    weather_grid_id = serializers.CharField()
    crop_history = CropYearSerializer(many=True, help_text="One entry per year, oldest first.")
    soil = SoilSerializer(allow_null=True, help_text="null when the field has no soil cells.")


# --- Risks ------------------------------------------------------------------------------------


class DayRiskSerializer(serializers.Serializer):
    field_id = serializers.IntegerField()
    threat_code = serializers.CharField()
    score = serializers.FloatField(help_text="[0-1] risk index, not a probability")
    level = serializers.ChoiceField(choices=LEVEL_CHOICES, help_text="explanation.level (colour by this)")


class DayRisksSerializer(serializers.Serializer):
    date = serializers.DateField()
    risks = DayRiskSerializer(many=True)


class RiskPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    score = serializers.FloatField()


class ThreatSeriesSerializer(serializers.Serializer):
    threat_code = serializers.CharField()
    points = RiskPointSerializer(many=True, help_text="By date.")


class FieldRiskSeriesSerializer(serializers.Serializer):
    field_id = serializers.IntegerField()
    from_ = serializers.DateField(help_text="The first day actually used.")
    to = serializers.DateField(help_text="The last day actually used (at most today + 7).")
    threats = ThreatSeriesSerializer(many=True, help_text="By threat code.")

    def get_fields(self):
        # `from` is a Python keyword: declared as from_, published (and read from the dict) as "from".
        return {("from" if name == "from_" else name): field for name, field in super().get_fields().items()}


class ThreatRefSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    category = serializers.ChoiceField(choices=Threat.Category.choices)


@extend_schema_field(OpenApiTypes.OBJECT)
class ExplanationField(serializers.JSONField):
    """Explanation version 1 (docs/database.md), passed through unchanged; readers ignore unknown keys."""


class FieldDayRiskSerializer(serializers.Serializer):
    threat = ThreatRefSerializer()
    score = serializers.FloatField()
    explanation = ExplanationField(help_text="Explanation version 1, as the engine wrote it.")


class FieldDayRisksSerializer(serializers.Serializer):
    field_id = serializers.IntegerField()
    date = serializers.DateField()
    risks = FieldDayRiskSerializer(many=True, help_text="Highest score first.")
