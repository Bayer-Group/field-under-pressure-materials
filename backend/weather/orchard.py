"""Interface used by main to submit weather updates for an orchard."""

from concurrent.futures import Executor, Future
from dataclasses import dataclass

from bson import ObjectId

from .jobs import backfill_history, refresh_current, refresh_daily


@dataclass(frozen=True)
class WeatherWorkers:
    current: Executor
    hourly: Executor


@dataclass(frozen=True)
class Orchard:
    """Represents one MongoDB orchard for scheduling weather updates.

    Main constructs the object and supplies the orchard's current coordinates
    when calling a method. Each method submits work to a shared process pool
    and returns a Future. Its result is the number of points processed, and
    any fetch or write error is raised when main reads that result.
    """

    orchard_id: ObjectId | str
    workers: WeatherWorkers

    def update_current(
        self, *, latitude: float, longitude: float, timezone: str = "auto"
    ) -> Future[int]:
        return self.workers.current.submit(
            refresh_current, self.orchard_id, latitude, longitude, timezone
        )

    def update_daily(
        self,
        *,
        latitude: float,
        longitude: float,
        timezone: str = "auto",
        forecast_days: int = 3,
        history_days: int = 2,
    ) -> Future[int]:
        return self.workers.hourly.submit(
            refresh_daily,
            self.orchard_id,
            latitude,
            longitude,
            timezone,
            forecast_days,
            history_days,
        )

    def backfill_history(
        self, *, latitude: float, longitude: float, timezone: str = "auto", days: int = 14
    ) -> Future[int]:
        return self.workers.hourly.submit(
            backfill_history, self.orchard_id, latitude, longitude, timezone, days
        )
