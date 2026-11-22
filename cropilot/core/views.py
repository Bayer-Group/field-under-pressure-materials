"""
The platform API (docs/interfaces.md -> Platform API). No authentication, no CSRF.

    GET  /api/health/                          {status, database, clock, assistant}
    GET  /api/clock/                           {today, forecast_days, min_date, max_date}
    PUT  /api/clock/                           {today} -> moves the demo date
    GET  /api/threats/                         every threat
    GET  /api/fields/                          every field, GeoJSON FeatureCollection
    GET  /api/fields/{id}/                     one field: crop history, soil
    GET  /api/risks/?date=                     every field's risks on one day
    GET  /api/fields/{id}/risks/?from=&to=     one field's risks over time
    GET  /api/fields/{id}/risks/{date}/        one field's risks on one day, with explanations

Nothing dated after today + 7 is ever returned (core.api_dates). A missing Clock row is a 503
(core.api_errors).
"""

from collections import Counter
from datetime import date

from django.db import connection
from django.db.models import Avg
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core import clock
from core.api_dates import InvalidDate, date_range, parse_date, single_date
from core.models import Field, FieldCropYear, Risk, Threat
from core.serializers import (
    ClockSerializer,
    ClockUpdateSerializer,
    DayRisksSerializer,
    ErrorSerializer,
    FieldDayRisksSerializer,
    FieldDetailSerializer,
    FieldFeatureCollectionSerializer,
    FieldRiskSeriesSerializer,
    ThreatSerializer,
    level_of,
)

SOIL_COLUMNS = ["ph", "clay", "sand", "silt", "om", "cec", "bulk_density"]

ERR_400 = {400: ErrorSerializer}
ERR_404 = {404: ErrorSerializer}
ERR_503 = {503: ErrorSerializer}  # the Clock row is missing


def assistant_health() -> dict | None:
    """The chat's state (assistant.status), or None if the assistant app can't tell."""
    try:
        from assistant.status import assistant_status

        return assistant_status()
    except Exception:
        return None


class HealthView(APIView):
    """
    Reports whether the platform is up and can reach the database, whether the demo date is set, and whether
    the chat can answer (assistant.available: an LLM is configured; rag: the guides index is there).
    """

    @extend_schema(
        responses=inline_serializer(
            name="Health",
            fields={
                "status": serializers.CharField(),
                "database": serializers.BooleanField(),
                "clock": serializers.BooleanField(help_text="The demo date is set."),
                "assistant": inline_serializer(
                    name="AssistantHealth",
                    allow_null=True,
                    fields={
                        "available": serializers.BooleanField(),
                        "llm": serializers.BooleanField(),
                        "rag": serializers.BooleanField(),
                        "reason": serializers.CharField(allow_null=True),
                    },
                ),
            },
        )
    )
    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            database_ok = True
        except Exception:
            database_ok = False
        clock_ok = False
        if database_ok:
            try:
                clock.today()
                clock_ok = True
            except clock.ClockNotSetError:
                pass
        return Response(
            {"status": "ok" if database_ok else "degraded", "database": database_ok, "clock": clock_ok,
             "assistant": assistant_health()},
            status=200 if database_ok else 503,
        )


def api_not_found(request, *args, **kwargs):
    """404 for any /api/ path no view matches, in the API's error shape."""
    from django.http import JsonResponse

    return JsonResponse({"detail": "Not found."}, status=404)


def crop_ref(crop) -> dict:
    return {"code": crop.code, "name": crop.name}


def get_field(pk: int) -> Field:
    field = Field.objects.select_related("crop").filter(pk=pk).first()
    if field is None:
        raise NotFound(f"field {pk} not found")
    return field


# --- Clock ------------------------------------------------------------------------------------


def clock_json(today: date) -> dict:
    lo, hi = clock.date_limits()
    return ClockSerializer({"today": today, "forecast_days": clock.FORECAST_DAYS, "min_date": lo, "max_date": hi}).data


class ClockView(APIView):
    """The demo's date. Moving it recomputes the risks of the days that change (engine.clock_moved)."""

    @extend_schema(operation_id="clock_get", responses={200: ClockSerializer, **ERR_503})
    def get(self, request: Request) -> Response:
        return Response(clock_json(clock.today()))

    @extend_schema(operation_id="clock_put", request=ClockUpdateSerializer, responses={200: ClockSerializer, **ERR_400})
    def put(self, request: Request) -> Response:
        body = request.data if isinstance(request.data, dict) else {}
        new = parse_date(body.get("today"), "today")
        lo, hi = clock.date_limits()
        if lo is not None and not lo <= new <= hi:
            raise InvalidDate(f"today must be between {lo.isoformat()} and {hi.isoformat()} (the days with weather)")
        clock.set_today(new)  # saves the row (creates it if missing) and calls engine.clock_moved
        return Response(clock_json(new))


# --- Threats ----------------------------------------------------------------------------------


class ThreatListView(APIView):
    """Every threat, ordered by crop, then code."""

    @extend_schema(operation_id="threats_list", responses=ThreatSerializer(many=True))
    def get(self, request: Request) -> Response:
        threats = Threat.objects.select_related("crop").order_by("crop__code", "code")
        data = [
            {"code": t.code, "name": t.name, "crop": crop_ref(t.crop), "category": t.category} for t in threats
        ]
        return Response(ThreatSerializer(data, many=True).data)


# --- Fields -----------------------------------------------------------------------------------


class FieldListView(APIView):
    """Every field as a GeoJSON FeatureCollection (EPSG:4326, coordinates [lon, lat])."""

    @extend_schema(operation_id="fields_list", responses=FieldFeatureCollectionSerializer)
    def get(self, request: Request) -> Response:
        features = [
            {
                "type": "Feature",
                "id": f.id,
                "geometry": f.geometry,
                "properties": {"id": f.id, "name": f.name, "crop": crop_ref(f.crop), "area_ha": f.area_ha},
            }
            for f in Field.objects.select_related("crop").order_by("id")
        ]
        return Response(FieldFeatureCollectionSerializer({"type": "FeatureCollection", "features": features}).data)


def crop_history(field: Field) -> list[dict]:
    years: dict[int, list[dict]] = {}
    rows = FieldCropYear.objects.filter(field=field).select_related("crop_class").order_by("year", "-share")
    for row in rows:
        years.setdefault(row.year, []).append(
            {"code": row.crop_class.code, "name": row.crop_class.name, "share": row.share}
        )
    return [{"year": year, "classes": classes} for year, classes in years.items()]


def field_soil(field: Field) -> dict | None:
    cells = field.soil_cells()
    if not cells.exists():
        return None
    soil = cells.aggregate(**{column: Avg(column) for column in SOIL_COLUMNS})
    textures = Counter(t for t in cells.values_list("soil_texture", flat=True) if t)
    # the most common class; ties broken alphabetically so the answer never depends on row order
    soil["soil_texture"] = min(textures, key=lambda t: (-textures[t], t)) if textures else None
    return soil


class FieldDetailView(APIView):
    """One field: crop, area, centroid, crop history per year and the average soil."""

    @extend_schema(operation_id="field_get", responses={200: FieldDetailSerializer, **ERR_404})
    def get(self, request: Request, pk: int) -> Response:
        field = get_field(pk)
        data = {
            "id": field.id,
            "name": field.name,
            "crop": crop_ref(field.crop),
            "area_ha": field.area_ha,
            "centroid": {"lat": field.centroid_lat, "lon": field.centroid_lon},
            "weather_grid_id": field.weather_grid_id,
            "crop_history": crop_history(field),
            "soil": field_soil(field),
        }
        return Response(FieldDetailSerializer(data).data)


# --- Risks ------------------------------------------------------------------------------------

DATE_QUERY = OpenApiParameter(
    "date", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Default today; at most today + 7 (else 400)."
)
DATE_PATH = OpenApiParameter("date", OpenApiTypes.DATE, OpenApiParameter.PATH, description="At most today + 7.")
FROM_QUERY = OpenApiParameter(
    "from", OpenApiTypes.DATE, OpenApiParameter.QUERY,
    description="Default 1 September of the year before the demo's year.",
)
TO_QUERY = OpenApiParameter(
    "to", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Default and maximum today + 7 (cut off, not an error)."
)


class DayRisksView(APIView):
    """Every field's risk per threat on one day, for colouring the map."""

    @extend_schema(operation_id="risks_day", parameters=[DATE_QUERY], responses={200: DayRisksSerializer, **ERR_400, **ERR_503})
    def get(self, request: Request) -> Response:
        day = single_date(request.query_params.get("date"))
        rows = (
            Risk.objects.filter(date=day)
            .order_by("field_id", "threat__code")
            .values_list("field_id", "threat__code", "score", "explanation")
        )
        risks = [
            {"field_id": field_id, "threat_code": code, "score": score, "level": level_of(score, explanation)}
            for field_id, code, score, explanation in rows
        ]
        return Response(DayRisksSerializer({"date": day, "risks": risks}).data)


def season_start(today: date) -> date:
    """
    The default `from` of the season chart: 1 September before this season's harvest (covers winter wheat
    sown in autumn). From September to December that is 1 January instead: maize and beet of the season just
    ending are still in the field, and the new winter crop's autumn starts in September.
    """
    return date(today.year, 1, 1) if today.month >= 9 else date(today.year - 1, 9, 1)


def earliest_from(today: date) -> date:
    """`from` is never earlier than the start of the previous season (older risks belong to other demos)."""
    year = today.year + 1 if today.month >= 9 else today.year
    return date(year - 2, 9, 1)


class FieldRiskSeriesView(APIView):
    """One field's risk per threat over time (the season chart). `to` never passes today + 7."""

    @extend_schema(
        operation_id="field_risks_series",
        parameters=[FROM_QUERY, TO_QUERY], responses={200: FieldRiskSeriesSerializer, **ERR_400, **ERR_404, **ERR_503}
    )
    def get(self, request: Request, pk: int) -> Response:
        field = get_field(pk)
        today = clock.today()
        start, end = date_range(request.query_params.get("from"), request.query_params.get("to"), season_start(today))
        start = min(max(start, earliest_from(today)), end)  # reported back in "from"
        rows = (
            Risk.objects.filter(field=field, date__range=(start, end))
            .order_by("threat__code", "date")
            .values_list("threat__code", "date", "score")
        )
        series: dict[str, list[dict]] = {}
        for code, day, score in rows:
            series.setdefault(code, []).append({"date": day, "score": score})
        threats = [{"threat_code": code, "points": points} for code, points in series.items()]
        return Response(
            FieldRiskSeriesSerializer({"field_id": field.id, "from": start, "to": end, "threats": threats}).data
        )


class FieldDayRisksView(APIView):
    """One field's risks on one day, highest first, each with its explanation (the "why" panel)."""

    @extend_schema(operation_id="field_risks_day", parameters=[DATE_PATH], responses={200: FieldDayRisksSerializer, **ERR_400, **ERR_404, **ERR_503})
    def get(self, request: Request, pk: int, date: str) -> Response:
        field = get_field(pk)
        day = single_date(date)
        rows = Risk.objects.filter(field=field, date=day).select_related("threat").order_by("-score", "threat__code")
        risks = [
            {
                "threat": {"code": r.threat.code, "name": r.threat.name, "category": r.threat.category},
                "score": r.score,
                "explanation": r.explanation,
            }
            for r in rows
        ]
        return Response(FieldDayRisksSerializer({"field_id": field.id, "date": day, "risks": risks}).data)
