"""Read field data and compute risk for the analyst workspace."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pymongo.errors import PyMongoError

from backend.analysis_state import published_analysis
from backend.dated_analytics import (
    DAYS_AHEAD,
    evaluate_day,
    forecast_pixels,
    issue_hour,
    value_at_pixel,
)
from backend.field_jobs import claim_job, latest_job, run_field_job
from backend.field_risk import assess, future_moisture
from backend.orchard_layout import trees_in_layout
from backend.raster_exports import stream_local_raster, stream_saved_raster
from backend.tree_health import tree_health
from ML.soil_moisture.field_geometry import (
    geojson_features,
    orchard_ids,
)
from ML.soil_moisture.open_meteo import UTC
from ML.soil_moisture.tree_pixel_analysis import tree_coordinates

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
UNASSIGNED = "unassigned"
USER_FIELDS = {"name": 1, "orchardIds": 1}


def field_refs(user):
    return {str(value) for value in user.get("orchardIds") or []}


def get_orchard(database, orchard_id, user_id=None):
    orchard = database.Orchard.find_one({"_id": {"$in": orchard_ids(orchard_id)}})
    if user_id is None:
        if orchard is None:
            raise HTTPException(404, "Nie znaleziono pola.")
        return orchard
    if orchard is not None:
        orchard_id = str(orchard["_id"])
        if user_id == UNASSIGNED:
            assigned = database.User.find_one(
                {"orchardIds": {"$in": orchard_ids(orchard_id)}}, {"_id": 1}
            )
            if assigned is None:
                return orchard
        else:
            user = database.User.find_one(
                {"_id": {"$in": orchard_ids(user_id)}}, USER_FIELDS
            )
            if user is not None and orchard_id in field_refs(user):
                return orchard
    raise HTTPException(404, "Nie znaleziono pola dla wybranego użytkownika.")


def list_orchards(database):
    return [
        {
            "id": str(doc["_id"]),
            "name": doc.get("name") or str(doc["_id"]),
            "tree_count": len(trees_in_layout(database, doc)),
        }
        for doc in database.Orchard.find({}, {"environmentalData": 0}).sort([("name", 1), ("_id", 1)])
    ]


@router.get("/orchards")
def analytics_orchards(request: Request):
    try:
        database = request.app.state.database
        return list_orchards(database)
    except PyMongoError as error:
        raise HTTPException(503, "Nie udało się odczytać MongoDB.") from error


@router.get("/users")
def analytics_users(request: Request):
    try:
        database = request.app.state.database
        fields = {field["id"]: field for field in list_orchards(database)}
        users, claimed = [], set()
        for user in database.User.find({}, USER_FIELDS).sort("name", 1):
            refs = field_refs(user)
            claimed.update(refs)
            users.append(
                {
                    "id": str(user["_id"]),
                    "name": user.get("name") or str(user["_id"]),
                    "orchards": [
                        field
                        for identity, field in fields.items()
                        if identity in refs
                    ],
                }
            )
        unassigned = [
            field for identity, field in fields.items() if identity not in claimed
        ]
        if unassigned:
            users.append({"id": UNASSIGNED, "name": None, "orchards": unassigned})
        return users
    except PyMongoError as error:
        raise HTTPException(503, "Nie udało się odczytać MongoDB.") from error


def public_metric(item, *keys):
    return {key: item.get(key) for key in keys} if item else None


def latest_observations(database, identity, scene_id, run_id):
    query = {"orchard_id": identity, "analysis_run_id": run_id}
    if scene_id:
        query["scene_id"] = scene_id
    observations = {}
    for row in database.TreePixelAnalysis.find(query).sort(
        [("acquired_at_utc", -1), ("context.date_local", -1)]
    ):
        observations.setdefault(str(row.get("tree_id")), row)
    return observations


def visible_analysis(database, orchard):
    return published_analysis(database, orchard)


def field_details(database, orchard, *, analysis=None, dated=None):
    identity = str(orchard["_id"])
    if analysis is None:
        analysis = visible_analysis(database, orchard)
    moisture = analysis.get("soil_moisture") or {}
    ndvi = analysis.get("ndvi") or {}
    soil = analysis.get("soil_parameters") or {}
    ph, texture = soil.get("ph") or {}, soil.get("texture") or {}
    sun = analysis.get("solar_intensity") or {}
    weather = analysis.get("weather") or {}
    run_id = analysis.get("run_id")
    observations = latest_observations(
        database, identity, moisture.get("scene_id"), run_id
    )
    if not weather and run_id is None:
        weather = next(
            (
                row["context"]["weather"]
                for row in observations.values()
                if (row.get("context") or {}).get("weather")
                and row["context"].get("date_local") == sun.get("date_local")
            ),
            {},
        )
    values = None
    if dated is not None:
        weather, sun = dated["weather"], dated["solar"]
        values = forecast_pixels(dated["raster_bytes"])
    common = {
        "solar": sun.get("level"),
        "temperature": weather.get("mean_temperature_c"),
    }
    species = {}
    for crop in database.CropPref.find({}, {"species": 1, "Ecology": 1}):
        species[str(crop["_id"])] = crop
        if isinstance(crop.get("species"), str):
            species[crop["species"].casefold()] = crop
    now = datetime.now(UTC)
    trees, profiles, forecasts_by_pixel = [], [], {}
    active_trees = trees_in_layout(database, orchard)
    health = tree_health(database, orchard, active_trees)
    placements = {
        str(identifier): (row.get("label") or row.get("id"), index)
        for row in orchard.get("rows") or []
        for index, identifier in enumerate(row.get("treeIds") or [], start=1)
    }
    for tree in active_trees:
        tree_id = str(tree["_id"])
        row_label, index_in_row = placements.get(tree_id, (None, None))
        row = observations.get(tree_id, {})
        pixel = (row.get("pixel") or {}) if moisture else {}
        layers = row.get("layers") or {}
        soil_points = layers.get("soil_parameters") or {}
        crop = species.get(str(tree.get("species")).casefold(), {})
        profile = crop.get("Ecology") or {}
        profiles.append(profile)
        prediction = row.get("soil_moisture_forecast") or {}
        forecast = (
            future_moisture(prediction, now, DAYS_AHEAD)
            if dated is None
            and (run_id is None or weather)
            and pixel
            and prediction.get("anchor_pixel_id") == row.get("pixel_id")
            else []
        )
        if forecast and row.get("pixel_id"):
            forecasts_by_pixel.setdefault(row["pixel_id"], forecast)
        moisture_value = (
            value_at_pixel(values, pixel)
            if dated is not None
            else pixel.get("soil_moisture_estimate_m3_m3")
        )
        status = row.get("sample_status")
        if dated is not None and status in ("sampled", "no_soil_data"):
            status = "forecasted" if moisture_value is not None else "no_forecast"
        inputs = {
            **common,
            "moisture": moisture_value,
            "ndvi": (layers.get("ndvi") or {}).get("value") if ndvi else None,
            "ph": (soil_points.get("ph") or {}).get("value") if ph else None,
            "texture": (soil_points.get("texture") or {}).get("value")
            if texture
            else None,
            "forecast": forecast,
        }
        trees.append(
            {
                "id": tree_id,
                "rowLabel": row_label,
                "indexInRow": index_in_row,
                "species": crop.get("species")
                or (
                    tree.get("species")
                    if isinstance(tree.get("species"), str)
                    else None
                ),
                "coordinates": tree_coordinates(tree),
                "pixel_analysis": {
                    "status": status
                    if moisture or status in ("outside_orchard", "invalid_coordinates")
                    else None,
                    "pixel": public_metric(pixel, "row", "column", "crs"),
                    "moisture_m3_m3": inputs["moisture"],
                    "ndvi": inputs["ndvi"],
                    "ph": inputs["ph"],
                    "texture": inputs["texture"],
                    "solar": inputs["solar"],
                },
                "risk": assess(inputs, [profile], dated=dated is not None),
                **health[tree_id],
            }
        )

    forecasts = [value for series in forecasts_by_pixel.values() for value in series]
    if dated is not None:
        moisture = dated["moisture"]
    field_inputs = {
        **common,
        "moisture": moisture.get("mean_m3_m3"),
        "ndvi": ndvi.get("mean"),
        "ph": ph.get("mean"),
        "texture": texture.get("dominant_class"),
        "forecast": forecasts,
    }
    if not any(profiles):
        crop = species.get(str(orchard.get("cropID")).casefold(), {})
        profiles = [crop["Ecology"]] if crop.get("Ecology") else []
    features = [
        {"type": "Feature", "geometry": feature["geometry"], "properties": {}}
        for feature in geojson_features(orchard.get("geometry"), "Orchard.geometry")
    ]
    acquired_at = moisture.get("acquired_at_utc")
    if isinstance(acquired_at, datetime) and acquired_at.tzinfo is None:
        acquired_at = acquired_at.replace(tzinfo=UTC)
    return {
        "id": identity,
        "name": orchard.get("name") or identity,
        "geometry": {"type": "FeatureCollection", "features": features},
        "risk": assess(field_inputs, profiles, dated=dated is not None),
        "trees": trees,
        "metrics": {
            "moisture": public_metric(
                {**moisture, "acquired_at_utc": acquired_at} if moisture else {},
                "mean_m3_m3",
                "valid_pixels",
                "acquired_at_utc",
                "raster",
                "valid_at_utc",
            ),
            "ndvi": public_metric(ndvi, "mean", "valid_pixels", "raster"),
            "ph": public_metric(ph, "mean", "depth_cm", "valid_pixels", "raster"),
            "texture": public_metric(
                texture, "dominant_class", "depth_cm", "valid_pixels", "raster"
            ),
            "solar": public_metric(
                sun,
                "level",
                "date_local",
                "energy_kwh_m2",
                "clear_sky_kwh_m2",
                "clear_sky_fraction",
            ),
            "weather": public_metric(
                weather,
                "mean_temperature_c",
                "precipitation_mm",
                "reference_et0_mm",
                "mean_humidity_percent",
                "mean_wind_km_h",
                "mean_cloud_percent",
                "date_local",
            ),
            "forecast_min_m3_m3": min(forecasts) if forecasts else None,
        },
        "forecast_day": public_metric(
            dated, "date_local", "issued_at_utc", "anchor_at_utc", "moisture_status"
        ),
    }


def field_response(request, orchard_id, user_id=None):
    try:
        database = request.app.state.database
        return field_details(database, get_orchard(database, orchard_id, user_id))
    except PyMongoError as error:
        raise HTTPException(503, "Nie udało się odczytać MongoDB.") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/orchards/{orchard_id}")
def analytics_field(request: Request, orchard_id: str):
    return field_response(request, orchard_id)


def dated_field_response(request, orchard_id, day, *, issued=None, name=None):
    issued = issue_hour(day, issued)
    try:
        database = request.app.state.database
        orchard = get_orchard(database, orchard_id)
        analysis = visible_analysis(database, orchard)
        dated = evaluate_day(
            orchard, analysis, day, issued, request.app.state.gee_credentials, database
        )
        if name is None:
            return field_details(database, orchard, analysis=analysis, dated=dated)
    except PyMongoError as error:
        raise HTTPException(503, "Nie udało się odczytać MongoDB.") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if dated["raster_bytes"] is None:
        raise HTTPException(404, "Prognozowany raster wilgotności jest niedostępny.")
    if name != dated["moisture"]["raster"]:
        raise HTTPException(409, "Odśwież analizę, aby wczytać aktualny raster.")
    return Response(
        dated["raster_bytes"],
        media_type="image/tiff",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/orchards/{orchard_id}/forecast/{day}")
def analytics_forecast(request: Request, orchard_id: str, day: date):
    return dated_field_response(request, orchard_id, day)


@router.get("/orchards/{orchard_id}/forecast/{day}/raster")
def analytics_forecast_raster(
    request: Request, orchard_id: str, day: date, issued: datetime, name: str
):
    return dated_field_response(request, orchard_id, day, issued=issued, name=name)


@router.get("/orchards/{orchard_id}/jobs/latest")
def field_job_status(request: Request, orchard_id: str):
    try:
        database = request.app.state.database
        orchard = get_orchard(database, orchard_id)
        return latest_job(database, str(orchard["_id"]))
    except PyMongoError as error:
        raise HTTPException(503, "Nie udało się odczytać MongoDB.") from error


@router.post("/orchards/{orchard_id}/jobs", status_code=202)
def start_field_job(request: Request, background: BackgroundTasks, orchard_id: str):
    try:
        database = request.app.state.database
        orchard = get_orchard(database, orchard_id)
        if error := request.app.state.gee_error:
            raise HTTPException(503, error)
        identity = str(orchard["_id"])
        job, started = claim_job(database, identity)
    except PyMongoError as error:
        raise HTTPException(503, "Nie udało się odczytać MongoDB.") from error
    if started:
        background.add_task(
            run_field_job,
            identity,
            job["id"],
            request.app.state.gee_credentials,
            request.app.state.gee_lock,
        )
    return job


@router.get("/users/{user_id}/orchards/{orchard_id}")
def analytics_user_field(request: Request, user_id: str, orchard_id: str):
    return field_response(request, orchard_id, user_id)


def raster_response(request, orchard_id, kind, user_id=None):
    try:
        database = request.app.state.database
        orchard = get_orchard(database, orchard_id, user_id)
        analysis = visible_analysis(database, orchard)
    except PyMongoError as error:
        raise HTTPException(503, "Nie udało się odczytać MongoDB.") from error
    group = (
        analysis.get("soil_parameters") or {} if kind in ("ph", "texture") else analysis
    )
    key = "soil_moisture" if kind == "moisture" else kind
    filename = (group.get(key) or {}).get("raster")
    if not isinstance(filename, str) or not filename:
        raise HTTPException(404, "Pole nie ma zapisanego rastra tej warstwy.")
    if response := stream_local_raster(database, filename):
        return response
    if error := request.app.state.gee_error:
        raise HTTPException(503, error)
    return stream_saved_raster(request.app.state.gee_credentials, filename)


@router.get("/orchards/{orchard_id}/rasters/{kind}")
def analytics_raster(
    request: Request,
    orchard_id: str,
    kind: Literal["moisture", "ndvi", "ph", "texture"],
):
    return raster_response(request, orchard_id, kind)


@router.get("/users/{user_id}/orchards/{orchard_id}/rasters/{kind}")
def analytics_user_raster(
    request: Request,
    user_id: str,
    orchard_id: str,
    kind: Literal["moisture", "ndvi", "ph", "texture"],
):
    return raster_response(request, orchard_id, kind, user_id)
