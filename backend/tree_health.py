"""Current environmental condition estimate shared by the 3D scene and analytics.

The current-stress-v1 rule inverts weighted present-day stress factors from ML.
It excludes predicted stress, requires fresh vegetation or SAR input, and reports
coverage. The estimate describes available environmental evidence for a tree's
pixel. Field observations in Tree.healthIndex take precedence. Sparse or stale
data produce null. Only a field observation can classify a tree as dead.
"""

from datetime import datetime, timedelta, timezone
from math import isfinite

from .analysis_state import published_analysis


def health_status(score, *, estimated=False):
    if score is None:
        return None
    if score <= 15 and not estimated:
        return "dead"
    if score <= 45:
        return "poor"
    return "moderate" if score <= 72 else "healthy"


def valid_score(value):
    return value if type(value) in (int, float) and isfinite(value) and 0 <= value <= 100 else None


def tree_health(database, orchard, trees):
    from .field_risk import assess

    analysis = published_analysis(database, orchard)
    run_id = analysis.get("run_id")
    rows = {}
    if run_id:
        rows = {
            row["tree_id"]: row for row in database.TreePixelAnalysis.find({
                "orchard_id": str(orchard["_id"]), "analysis_run_id": run_id,
            })
        }
    profiles = {str(p["_id"]): p.get("Ecology") or {} for p in database.CropPref.find({}, {"Ecology": 1})}
    now = datetime.now(timezone.utc)
    result = {}
    for tree in trees:
        identifier = str(tree["_id"])
        score = valid_score(tree.get("healthIndex"))
        summary = {
            "healthScore": score, "healthStatus": health_status(score),
            "healthSource": "field" if score is not None else None,
            "healthAssessedAt": tree.get("healthUpdatedAt"), "healthCoverage": 100 if score is not None else 0,
            "healthMethod": None, "analysisRunId": run_id,
        }
        if score is None and identifier in rows:
            row = rows[identifier]
            stamp = analysis.get("observed_at")
            if isinstance(stamp, datetime):
                stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
                fresh = timedelta(0) <= now - stamp <= timedelta(days=14)
            else:
                fresh = False
            geo = tree.get("coordinates") or {}
            same_position = row.get("tree_coordinates_lon_lat") == [geo.get("lng"), geo.get("lat")]
            if fresh and same_position:
                layers = row.get("layers") or {}
                soil = layers.get("soil_parameters") or {}
                context = row.get("context") or {}
                inputs = {
                    "moisture": (row.get("pixel") or {}).get("soil_moisture_estimate_m3_m3"),
                    "ndvi": (layers.get("ndvi") or {}).get("value"),
                    "ph": (soil.get("ph") or {}).get("value"),
                    "texture": (soil.get("texture") or {}).get("value"),
                    "solar": (context.get("solar") or {}).get("level"),
                    "temperature": (context.get("weather") or {}).get("mean_temperature_c"),
                }
                # Forecast weight is excluded from the current condition estimate.
                risk = assess(inputs, [profiles.get(str(tree.get("species")), {})], dated=True)
                observed = inputs["ndvi"] is not None or inputs["moisture"] is not None
                if observed and risk["score"] is not None:
                    score = 100 - risk["score"]
                    summary.update(
                        healthScore=score, healthStatus=health_status(score, estimated=True),
                        healthSource="estimate", healthAssessedAt=stamp,
                        healthCoverage=risk["coverage"], healthMethod="current-stress-v1",
                    )
        result[identifier] = summary
    return result
