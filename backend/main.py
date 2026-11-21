"""Drive orchard weather synchronization and serve the UI's weather API."""

import argparse
import logging
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import asynccontextmanager
from multiprocessing import get_context
from threading import Event, Thread

import uvicorn
from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from .http_api import create_app
from .weather.jobs import initialize_worker
from .weather.migration import migrate_weather
from .weather.orchard import Orchard, WeatherWorkers
from .weather.repository import WeatherRepository

log = logging.getLogger(__name__)


def _read_point(document: dict, field: str) -> tuple[float, float]:
    point = document
    for key in field.split("."):
        point = point.get(key) if isinstance(point, dict) else None

    if not isinstance(point, dict):
        raise ValueError(f"{field} must contain an orchard center")  # noqa: TRY004

    if point.get("type") == "Point":
        coordinates = point.get("coordinates")
    else:
        coordinates = (point.get("long", point.get("lng")), point.get("lat"))
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        raise ValueError(f"{field} must contain longitude and latitude")

    longitude, latitude = coordinates
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) for value in coordinates
    ):
        raise ValueError(f"{field} longitude and latitude must be numeric")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"{field} longitude and latitude are outside the WGS84 range")

    return float(latitude), float(longitude)


def _submit_cycle(
    db: Database, args: argparse.Namespace, workers: WeatherWorkers, mode: str
) -> dict[ObjectId, Future[int]]:
    documents = list(db["Orchard"].find({}, {args.point_field: 1}))
    pending = {}
    for document in documents:
        orchard_id = document["_id"]
        try:
            latitude, longitude = _read_point(document, args.point_field)
        except ValueError as error:
            log.warning("Skipping orchard %s: %s", orchard_id, error)
            continue

        orchard = Orchard(orchard_id=orchard_id, workers=workers)
        point = {"latitude": latitude, "longitude": longitude, "timezone": args.timezone}
        if mode == "current":
            future = orchard.update_current(**point)
        elif mode == "daily":
            future = orchard.update_daily(**point, history_days=args.history_days or 2)
        else:
            future = orchard.backfill_history(**point, days=args.history_days or 14)
        pending[orchard_id] = future

    if not pending:
        log.warning("No orchards with a usable point in %s", args.point_field)
    return pending


def _report(mode: str, pending: dict[ObjectId, Future[int]]) -> bool:
    succeeded = bool(pending)
    for orchard_id, future in pending.items():
        try:
            count = future.result()
            log.info("%s | orchard %s | processed %d points", mode, orchard_id, count)
        except Exception:
            log.exception("%s failed for orchard %s", mode, orchard_id)
            succeeded = False
    return succeeded


def _run_scheduler(
    db: Database, args: argparse.Namespace, workers: WeatherWorkers, stop: Event
) -> None:
    intervals = {"current": 3_600, "daily": 86_400}
    next_run = dict.fromkeys(intervals, time.monotonic())
    batches = {mode: {} for mode in intervals}
    try:
        while not stop.is_set():
            now = time.monotonic()
            for mode, interval in intervals.items():
                pending = batches[mode]
                if any(not future.done() for future in pending.values()):
                    continue
                if pending:
                    _report(mode, pending)
                    batches[mode] = {}
                if now >= next_run[mode]:
                    next_run[mode] = now + interval
                    try:
                        batches[mode] = _submit_cycle(db, args, workers, mode)
                    except PyMongoError:
                        log.exception("Could not read orchards for %s", mode)
                        next_run[mode] = now + 60
            stop.wait(1)
    finally:
        for pending in batches.values():
            for future in pending.values():
                future.cancel()


def _serve(db: Database, args: argparse.Namespace, workers: WeatherWorkers) -> None:
    @asynccontextmanager
    async def lifespan(app):
        stop = Event()
        scheduler = Thread(
            target=_run_scheduler, args=(db, args, workers, stop), name="weather-scheduler"
        )
        scheduler.start()
        try:
            yield
        finally:
            stop.set()
            scheduler.join()

    uvicorn.run(create_app(db, lifespan=lifespan), host=args.host, port=args.port, workers=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("backfill", "current", "daily", "migrate", "run"))
    parser.add_argument("--point-field", default="centroid", help="Path to the orchard center")
    parser.add_argument("--timezone", default="auto", help="Open-Meteo timezone for each request")
    parser.add_argument("--history-days", type=int, help="History window for backfill, daily or run")
    parser.add_argument("--port", type=int, default=8000, help="Local HTTP port for run")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    args = parser.parse_args()
    if args.history_days is not None and not 1 <= args.history_days <= 92:
        parser.error("--history-days must be between 1 and 92")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        from urllib.parse import quote
        host = os.environ.get("MONGO_HOST", "127.0.0.1")
        port = os.environ.get("MONGO_PORT", "27017")
        user = os.environ.get("MONGO_ROOT_USER", "")
        password = os.environ.get("MONGO_ROOT_PASSWORD", "")
        auth = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user else ""
        mongo_uri = f"mongodb://{auth}{host}:{port}/?authSource=admin"
        os.environ["MONGO_URI"] = mongo_uri
    database_name = os.environ.get("MONGO_DB", "field_under_pressure")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    worker_options = {
        "max_workers": 1,
        "mp_context": get_context("spawn"),
        "initializer": initialize_worker,
        "initargs": (mongo_uri, database_name),
    }
    try:
        with MongoClient(mongo_uri, serverSelectionTimeoutMS=5_000, timeoutMS=15_000) as client:
            db = client[database_name]
            repository = WeatherRepository(db)
            repository.ensure_indexes()
            if args.mode == "migrate":
                current_count, forecast_count, history_count = migrate_weather(db, repository)
                log.info(
                    "Migrated %d current snapshots, %d forecast hours and %d history hours",
                    current_count,
                    forecast_count,
                    history_count,
                )
                return 0
            with (
                ProcessPoolExecutor(**worker_options) as current,
                ProcessPoolExecutor(**worker_options) as hourly,
            ):
                workers = WeatherWorkers(current=current, hourly=hourly)
                if args.mode == "run":
                    if db.Orchard.find_one({"environmentalData.history.0": {"$exists": False}}, {"_id": 1}):
                        pending = _submit_cycle(db, args, workers, "backfill")
                        if not _report("backfill", pending):
                            log.warning("Some histories are unavailable; scheduled updates will retry")
                    _serve(db, args, workers)
                else:
                    pending = _submit_cycle(db, args, workers, args.mode)
                    return 0 if _report(args.mode, pending) else 1
    except KeyboardInterrupt:
        log.info("Weather synchronization stopped")
        return 0
    except PyMongoError:
        log.exception("Could not initialize MongoDB or read orchards")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
