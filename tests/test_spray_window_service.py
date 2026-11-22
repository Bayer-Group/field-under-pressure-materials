"""Unit tests of backend/app/services/spray_window.py with a fake database connection (no database, no network).

They protect what connects the spray window to the demo clock and to the serve views: which "now" and which day are used,
that the 72 hours of weather are complete (a missing hour is unknown, never good) and that the septoria signal reaches the rules.
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.services import spray_window as service  # noqa: E402

NOW = datetime(2024, 5, 20, 6)
TODAY = date(2024, 5, 20)
AREA = {"crop_area_id": "area-1", "field_id": "f-1", "owner_id": "u-1", "field_name": "Field", "farmer_crop_id": "wheat",
        "geometry": {"type": "Polygon", "coordinates": []}, "risk_class": "high", "status": "ok", "conditions_met": True,
        "growth_stage_zone": "B", "protected_until": None, "h_hours": 24, "grid_id": "G-1"}


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeCon:
    """Answers the three queries of the service by their SQL text and records the parameters they were called with."""

    def __init__(self, areas=(AREA,), weather=None, clock=None):
        self.areas, self.weather = list(areas), weather if weather is not None else {}
        self.clock = clock or {"now": datetime(2024, 5, 20, 6, 37, 12), "today": TODAY}
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql is service.CLOCK_SQL:
            return FakeResult([self.clock])
        if sql is service.AREAS_SQL:
            return FakeResult(self.areas)
        if sql is service.HOURS_SQL:
            return FakeResult([self.weather[t] for t in sorted(self.weather)])
        raise AssertionError("unexpected query")

    def params_of(self, sql):
        return next(p for s, p in self.calls if s is sql)


def good_hour(t, grid="G-1"):
    return {"grid_id": grid, "local_time": t, "wind_speed_ms": 2.0, "wind_gust_ms": 3.0, "temperature": 10.0, "precipitation": 0.0}


class DemoClock(unittest.TestCase):
    """The day of the septoria signal and the hour of the weather come from one clock (the database's, as GET /clock)."""

    def test_default_uses_the_database_clock(self):
        con = FakeCon()
        now, day = service.shown_now(con)
        self.assertEqual((now, day), (NOW, TODAY))                   # truncated to the start of the hour

    def test_at_overrides_the_clock_and_is_not_read_from_the_database(self):
        con = FakeCon()
        now, day = service.shown_now(con, datetime(2024, 6, 2, 14, 45))
        self.assertEqual((now, day), (datetime(2024, 6, 2, 14), date(2024, 6, 2)))
        self.assertEqual(con.calls, [])

    def test_aware_at_is_converted_to_the_shown_local_time(self):
        now, day = service.shown_now(FakeCon(), datetime(2024, 5, 20, 22, 30, tzinfo=timezone.utc))   # 00:30 the next day in Warsaw
        self.assertEqual((now, day), (datetime(2024, 5, 21, 0), date(2024, 5, 21)))

    def test_signal_day_is_the_clock_day_not_the_date_of_the_hour(self):
        # Just after midnight in Warsaw while the database day has not changed yet: the signal is still the one of "today".
        con = FakeCon(clock={"now": datetime(2024, 5, 21, 0, 20), "today": TODAY})
        service.compute(con, "u-1")
        self.assertEqual(con.params_of(service.AREAS_SQL)["day"], TODAY)

    def test_iso_carries_the_warsaw_offset(self):
        self.assertEqual(service.iso(datetime(2024, 1, 15, 8)), "2024-01-15T08:00:00+01:00")
        self.assertEqual(service.iso(datetime(2024, 5, 20, 8)), "2024-05-20T08:00:00+02:00")
        self.assertIsNone(service.iso(None))


class Compute(unittest.TestCase):

    def test_weather_is_completed_to_the_horizon_and_a_gap_is_unknown(self):
        weather = {NOW + timedelta(hours=i): good_hour(NOW + timedelta(hours=i)) for i in range(72) if i != 10}
        con = FakeCon(weather=weather)
        _, rows = service.compute(con, "u-1")
        result = rows[0][1]
        self.assertEqual(len(result["hours"]), 72)
        self.assertIsNone(result["hours"][10]["ok"])                 # the missing hour is unknown, never good
        self.assertAlmostEqual(result["coverage"], 71 / 72, places=3)
        self.assertEqual(result["status"], "window_now")             # the run 06:00-15:59 still holds

    def test_hours_are_read_from_now_for_the_horizon_only(self):
        con = FakeCon(weather={NOW: good_hour(NOW)})
        service.compute(con, "u-1")
        p = con.params_of(service.HOURS_SQL)
        self.assertEqual((p["t0"], p["t1"]), (NOW, NOW + timedelta(hours=72)))
        self.assertEqual(p["cells"], ["G-1"])

    def test_no_weather_for_the_cell_gives_no_forecast(self):
        _, rows = service.compute(FakeCon(weather={}), "u-1")
        self.assertEqual(rows[0][1]["status"], "no_forecast")        # replay data ran out: not an invented window

    def test_signal_comes_from_the_septoria_assessment(self):
        weather = {NOW + timedelta(hours=i): good_hour(NOW + timedelta(hours=i)) for i in range(72)}
        quiet = dict(AREA, conditions_met=False, risk_class="medium")
        _, rows = service.compute(FakeCon(areas=[quiet], weather=weather), "u-1")
        self.assertEqual((rows[0][1]["status"], rows[0][1]["signal_reason"]), ("no_signal", "risk_not_high"))

    def test_area_without_assessment_and_cell_is_not_asked_for_weather(self):
        con = FakeCon(areas=[dict(AREA, grid_id=None, risk_class=None, status=None, conditions_met=None)])
        _, rows = service.compute(con, "u-1")
        self.assertEqual(rows[0][1]["status"], "no_signal")
        self.assertFalse(any(s is service.HOURS_SQL for s, _ in con.calls))


class Notes(unittest.TestCase):

    def test_every_answer_carries_the_disclaimer_and_the_replay_label(self):
        notes = service.notes(service.rules())
        self.assertIn("label", notes["disclaimer"])                  # the tool does not check the product label
        self.assertEqual(notes["source"], "replay")
        self.assertIsNotNone(notes["source_note"])
        self.assertEqual(notes["limits"]["wind_max_ms"], 4.0)


if __name__ == "__main__":
    unittest.main()
