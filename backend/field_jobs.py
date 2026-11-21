"""Run one asynchronous Earth Engine and MongoDB analysis per orchard."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import ee
from fastapi import HTTPException
from google.auth.exceptions import GoogleAuthError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from rasterio.errors import RasterioError

from backend.dated_analytics import DAYS_AHEAD
from backend.raster_exports import download_raster, list_rasters
from ML.soil_moisture import ndvi, soil_parameters, tree_pixel_analysis
from ML.soil_moisture.earth_engine import SoilMoistureConfig, create_exports
from ML.soil_moisture.field_geometry import mongo_client, mongo_database
from ML.soil_moisture.open_meteo import DAY, UTC
from ML.soil_moisture.solar_intensity_calc import WARSAW

logger = logging.getLogger(__name__)
ACTIVE = ("preparing", "exporting", "downloading", "saving")
LEASE = timedelta(minutes=15)
EXPORT_TIMEOUT = 6 * 60 * 60
DRIVE_WAIT = 5 * 60
POLL_SECONDS = 10
TOTAL_EXPORTS = 4
DRIVE_FOLDER = "field_analytics"


def public_job(job):
    return {
        **{key: job[key] for key in ("id", "state", "done", "total", "error")},
        "ready_layers": job.get("ready_layers", []),
        "layer_errors": job.get("layer_errors", {}),
        "export_status": job.get("export_status", {}),
    }


def latest_job(database, orchard_id):
    jobs = database.FieldAnalysisJob
    job = jobs.find_one({"_id": orchard_id})
    if job and job["state"] in ACTIVE:
        expired = jobs.find_one_and_update(
            {
                "_id": orchard_id,
                "id": job["id"],
                "state": {"$in": ACTIVE},
                "lease_until": {"$lte": datetime.now(UTC)},
            },
            {
                "$set": {
                    "state": "failed",
                    "error": "Analiza została przerwana. Uruchom ją ponownie.",
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        job = expired or jobs.find_one({"_id": orchard_id})
    return public_job(job) if job else None


def claim_job(database, orchard_id):
    now = datetime.now(UTC)
    job = {
        "id": uuid4().hex,
        "state": "preparing",
        "done": 0,
        "total": TOTAL_EXPORTS,
        "error": None,
        "lease_until": now + LEASE,
        "task_ids": [],
        "analysis": None,
        "ready_layers": [],
        "layer_errors": {},
        "export_status": {},
    }
    try:
        database.FieldAnalysisJob.update_one(
            {
                "_id": orchard_id,
                "$or": [{"state": {"$nin": ACTIVE}}, {"lease_until": {"$lte": now}}],
            },
            {"$set": job},
            upsert=True,
        )
    except DuplicateKeyError:
        return latest_job(database, orchard_id), False
    return public_job(job), True


def progress(database, orchard_id, run_id, state, done=0, **extra):
    updated = database.FieldAnalysisJob.update_one(
        {"_id": orchard_id, "id": run_id, "state": {"$in": ACTIVE}},
        {
            "$set": {
                "state": state,
                "done": done,
                "lease_until": datetime.now(UTC) + LEASE,
                **extra,
            }
        },
    )
    if not updated.matched_count:
        raise RuntimeError("Analiza pola wygasła.")


def prepare_exports(orchard_id, export_tag, now):
    end = now.date() - 14 * DAY
    test_start = end - 45 * DAY
    config = SoilMoistureConfig(
        start=(test_start - 120 * DAY).isoformat(),
        test_start=test_start.isoformat(),
        end=end.isoformat(),
        drive_folder=DRIVE_FOLDER,
        export_tree_raster=True,
        coarse_training_inputs=True,
    )
    exports, errors = {}, {}
    scene_id, acquired_at = None, None
    try:
        radar_tasks, scene = create_exports(
            config, orchard_id=orchard_id, export_tag=export_tag
        )
        if scene is None:
            raise ValueError("Brak rastra wilgotności dla wybranego pola.")
        radar = next(
            task
            for task in radar_tasks
            if task.config["description"] == "sentinel1_tree_pixels"
        )
        acquired_at = tree_pixel_analysis.acquisition_time(scene["acquired_at"])
        scene_id = scene["scene_id"]
        exports["moisture"] = (radar, scene["name"])
    except (ee.EEException, ValueError) as error:
        errors["moisture"] = str(error)[:500]

    ndvi_end = acquired_at.date() + DAY if acquired_at else now.date()
    try:
        vegetation, _ = ndvi.create_task(
            ndvi_end - 45 * DAY,
            ndvi_end,
            60,
            None,
            DRIVE_FOLDER,
            orchard_id=orchard_id,
            export_tag=export_tag,
        )
        exports["ndvi"] = (vegetation, vegetation.config["description"])
    except (ee.EEException, ValueError) as error:
        errors["ndvi"] = str(error)[:500]

    try:
        ph, texture = soil_parameters.create_tasks(
            0, None, DRIVE_FOLDER, orchard_id=orchard_id, export_tag=export_tag
        )
        exports["ph"] = (ph, ph.config["description"])
        exports["texture"] = (texture, texture.config["description"])
    except (ee.EEException, ValueError) as error:
        errors["ph"] = errors["texture"] = str(error)[:500]
    return exports, scene_id, acquired_at, errors


def collect_exports(credentials, exports, destination, lock, analysis, errors, update):
    deadline = monotonic() + EXPORT_TIMEOUT
    pending = dict(exports)
    drive_deadlines = {}
    ready = []
    export_status = {}
    while pending:
        with lock:
            statuses = ee.data.getTaskStatus([task.id for task, _ in pending.values()])
        for (kind, (_, name)), status in zip(
            list(pending.items()), statuses, strict=True
        ):
            export_status[kind] = {
                "state": status["state"],
                "attempt": status.get("attempt"),
            }
            if status["state"] in ("FAILED", "CANCELLED", "CANCEL_REQUESTED"):
                errors[kind] = (
                    status.get("error_message")
                    or "Eksport Earth Engine został przerwany."
                )
            elif status["state"] == "COMPLETED":
                limit = drive_deadlines.setdefault(kind, monotonic() + DRIVE_WAIT)
                update(
                    "downloading",
                    len(ready),
                    layer_errors=errors,
                    export_status=export_status,
                )
                try:
                    files = list_rasters(credentials, name)
                    if len(files) > 1:
                        raise ValueError(
                            "Eksport składa się z kilku GeoTIFF-ów. Użyj mniejszego obszaru pola."
                        )
                    if files:
                        path = download_raster(credentials, files[0], destination)
                        analysis.collect(kind, path)
                    elif monotonic() >= limit:
                        raise ValueError(
                            "GeoTIFF nie pojawił się na Dysku Google w ciągu 5 minut."
                        )
                except (HTTPException, OSError, ValueError, RasterioError) as error:
                    errors[kind] = str(
                        error.detail if isinstance(error, HTTPException) else error
                    )[:500]
                else:
                    if files:
                        analysis.save_trees(datetime.now(UTC), (kind,))
                        ready.append(kind)
                        update(
                            "downloading",
                            len(ready),
                            analysis=analysis.preview(),
                            ready_layers=ready,
                            layer_errors=errors,
                            export_status=export_status,
                        )
                        del pending[kind]
            elif monotonic() >= deadline:
                with lock:
                    cancel_task(pending[kind][0])
                errors[kind] = "Earth Engine nie zakończył eksportu w ciągu 6 godzin."

            if kind in errors:
                del pending[kind]

        state = (
            "downloading"
            if any(kind in drive_deadlines for kind in pending)
            else "exporting"
        )
        update(state, len(ready), layer_errors=errors, export_status=export_status)
        if pending:
            sleep(POLL_SECONDS)
    return ready


def cancel_task(task):
    try:
        task.cancel()
    except (ee.EEException, GoogleAuthError, OSError):
        logger.warning("Could not cancel Earth Engine task %s", task.id)


def run_field_job(orchard_id, run_id, credentials, lock):
    started = {}
    with mongo_client() as client:
        database = mongo_database(client)

        def update(state, done=0, **extra):
            progress(database, orchard_id, run_id, state, done, **extra)

        try:
            now = datetime.now(UTC)
            with lock:
                exports, scene_id, acquired_at, errors = prepare_exports(
                    orchard_id, f"fup_{run_id}", now
                )
                for kind, (task, name) in exports.items():
                    try:
                        task.start()
                    except ee.EEException as error:
                        errors[kind] = str(error)[:500]
                    else:
                        started[kind] = (task, name)
            update(
                "exporting",
                task_ids=[task.id for task, _ in started.values()],
                layer_errors=errors,
            )
            analysis = tree_pixel_analysis.FieldAnalysis(
                database,
                SimpleNamespace(
                    orchard_id=orchard_id,
                    scene_id=scene_id,
                    acquired_at=acquired_at,
                    date=now.astimezone(WARSAW).date() - DAY,
                    soil_depth_cm=0,
                    forecast_days=DAYS_AHEAD
                    if acquired_at and (now.date() - acquired_at.date()).days <= 92
                    else 0,
                ),
                run_id=run_id,
            )
            with TemporaryDirectory(prefix="field-analytics-") as folder:
                ready = collect_exports(
                    credentials, started, Path(folder), lock, analysis, errors, update
                )
            started.clear()
            if not ready:
                update(
                    "failed",
                    error="Nie udało się przetworzyć żadnej warstwy.",
                    layer_errors=errors,
                )
                return
            update("saving", len(ready), layer_errors=errors)
            now = datetime.now(UTC).replace(microsecond=0)
            analysis.context_and_forecast(now)
            analysis.save_trees(now, ())
            analysis.save_orchard()
            update("completed", len(ready), layer_errors=errors)
        except Exception as error:
            logger.exception("Field analysis %s failed", run_id)
            with lock:
                for task, _ in started.values():
                    cancel_task(task)
            if isinstance(error, HTTPException):
                detail = str(error.detail)
            elif isinstance(error, (ee.EEException, ValueError)):
                detail = str(error)
            else:
                detail = "Nie udało się zapisać analizy pola. Sprawdź logi backendu."
            database.FieldAnalysisJob.update_one(
                {"_id": orchard_id, "id": run_id, "state": {"$in": ACTIVE}},
                {"$set": {"state": "failed", "error": detail[:500]}},
            )
