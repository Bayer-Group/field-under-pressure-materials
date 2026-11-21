import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from threading import Lock
from uuid import uuid4

import ee
from fastapi import FastAPI, HTTPException, Path, Request, status
from fastapi.middleware.cors import CORSMiddleware
from google.auth.exceptions import GoogleAuthError
from pydantic import BaseModel, ConfigDict, model_validator

from backend.raster_exports import RASTER_NAME_PATTERN, list_rasters, stream_raster
from ML.soil_moisture.earth_engine import (
    RASTER_TASK_NAME,
    SoilMoistureConfig,
    create_tasks,
)
from ML.soil_moisture.forecast import WeatherError, forecast_fields
from ML.soil_moisture.project_config import earth_engine_project

logger = logging.getLogger(__name__)
gee_lock = Lock()
DEFAULT_ORIGINS = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5173,http://127.0.0.1:5173"
)


class AnalysisDates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    test_start: date
    end: date

    @model_validator(mode="after")
    def check_order(self) -> "AnalysisDates":
        if not self.start < self.test_start < self.end:
            raise ValueError("Daty muszą spełniać warunek start < test_start < end.")
        return self


class SubmittedTask(BaseModel):
    id: str
    name: str


class AnalysisSubmission(BaseModel):
    dates: AnalysisDates
    tasks: list[SubmittedTask]


class AnalysisTaskStatus(BaseModel):
    id: str
    state: str
    error: str | None = None


class RasterFile(BaseModel):
    id: str
    name: str


class RasterFiles(BaseModel):
    files: list[RasterFile]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.gee_error = None
    try:
        project = earth_engine_project()
        credentials = ee.data.get_persistent_credentials()
        ee.Initialize(credentials=credentials, project=project)
        app.state.gee_credentials = credentials
    except ValueError as error:
        app.state.gee_error = str(error)
    except (ee.EEException, GoogleAuthError):
        logger.exception("Earth Engine initialization failed")
        app.state.gee_error = (
            "Brak połączenia z Earth Engine. Sprawdź projekt i logowanie."
        )
    yield


my_app = FastAPI(title="Field Under Pressure API", lifespan=lifespan)
my_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGINS", DEFAULT_ORIGINS).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def require_gee(request: Request):
    if error := request.app.state.gee_error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=error)


@my_app.post("/api/soil-moisture", status_code=status.HTTP_202_ACCEPTED)
def submit_soil_moisture(dates: AnalysisDates, request: Request) -> AnalysisSubmission:
    require_gee(request)
    config = SoilMoistureConfig(
        start=dates.start.isoformat(),
        test_start=dates.test_start.isoformat(),
        end=dates.end.isoformat(),
        raster_export_name=f"{RASTER_TASK_NAME}_{uuid4().hex}",
    )
    submitted = []
    try:
        with gee_lock:
            try:
                tasks = create_tasks(config)
            except ValueError as error:
                raise HTTPException(422, detail=str(error)) from error
            for task in tasks:
                task.start()
                name = task.config["description"]
                if name == config.raster_export_name:
                    name = RASTER_TASK_NAME
                submitted.append(SubmittedTask(id=task.id, name=name))
    except (ee.EEException, GoogleAuthError, OSError, ValueError) as error:
        logger.exception("Earth Engine analysis submission failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Nie udało się wysłać wszystkich zadań do Earth Engine.",
                "submitted_tasks": [task.model_dump() for task in submitted],
            },
        ) from error
    return AnalysisSubmission(dates=dates, tasks=submitted)


def earth_engine_task(request, task_id):
    require_gee(request)
    try:
        with gee_lock:
            task_statuses = ee.data.getTaskStatus(task_id)
    except (ee.EEException, GoogleAuthError, OSError) as error:
        logger.exception("Earth Engine task lookup failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Nie udało się odczytać stanu zadania."
        ) from error
    if not task_statuses or task_statuses[0].get("state") == "UNKNOWN":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie znaleziono zadania.")
    return task_statuses[0]


@my_app.get("/api/soil-moisture/tasks/{task_id}")
def soil_moisture_task_status(
    request: Request, task_id: str = Path(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
) -> AnalysisTaskStatus:
    task = earth_engine_task(request, task_id)
    return AnalysisTaskStatus(
        id=task_id, state=task["state"], error=task.get("error_message")
    )


def raster_export(request, task_id):
    task = earth_engine_task(request, task_id)
    name = task.get("description", "")
    if not RASTER_NAME_PATTERN.fullmatch(name):
        raise HTTPException(404, "Zadanie nie ma rastra dostępnego w aplikacji.")
    return name, task["state"]


@my_app.get("/api/soil-moisture/tasks/{task_id}/rasters")
def soil_moisture_rasters(
    request: Request, task_id: str = Path(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
) -> RasterFiles:
    name, state = raster_export(request, task_id)
    if state in ("FAILED", "CANCELLED"):
        raise HTTPException(409, "Eksport rastra nie został ukończony.")
    if state != "COMPLETED":
        return RasterFiles(files=[])
    files = list_rasters(request.app.state.gee_credentials, name)
    return RasterFiles(files=files)


@my_app.get("/api/soil-moisture/tasks/{task_id}/rasters/{file_id}")
def soil_moisture_raster(
    request: Request,
    task_id: str = Path(pattern=r"^[a-zA-Z0-9_-]{1,128}$"),
    file_id: str = Path(pattern=r"^[a-zA-Z0-9_-]{1,128}$"),
):
    name, state = raster_export(request, task_id)
    if state != "COMPLETED":
        raise HTTPException(409, "Eksport rastra nie został ukończony.")
    return stream_raster(request.app.state.gee_credentials, name, file_id)


@my_app.get("/api/soil-moisture/forecast")
def soil_moisture_forecast(request: Request, relative_orbit: int | None = None):
    require_gee(request)
    model_asset = os.getenv("EARTHENGINE_MODEL_ASSET", "").strip() or None
    try:
        with gee_lock:
            return forecast_fields(
                SoilMoistureConfig(relative_orbit=relative_orbit),
                model_asset=model_asset,
            )
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    except (ee.EEException, GoogleAuthError, OSError, WeatherError) as error:
        logger.exception("Soil moisture forecast failed")
        detail = (
            str(error)
            if isinstance(error, WeatherError)
            else "Nie udało się obliczyć prognozy wilgotności."
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=detail) from error
