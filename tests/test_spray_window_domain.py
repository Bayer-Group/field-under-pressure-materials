"""Unit tests of backend/app/domain/spray_window.py (pure functions, no database).

The weather of the main case is the example of section 7 of the team's note "Okno oprysku: jak to wyliczamy" (v3); the expected
ranking is the one the note gives. Times are fixed (no clock, no time zone)."""
import os
import sys
import tomllib
import unittest
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.domain import spray_window as sw  # noqa: E402

with open(os.path.join(BASE_DIR, "config", "spray_window.toml"), "rb") as fh:
    RULES = sw.Rules.from_config(tomllib.load(fh))

NOW = datetime(2024, 5, 20, 6)                      # "today 06:00" of the example
SIGNAL = {"status": "ok", "risk_class": "high", "conditions_met": True, "growth_stage_zone": "B"}


def example_weather(t: datetime):
    """(wind m/s, gusts m/s, temperature C, precipitation mm) of the note's example; elsewhere too windy."""
    day, h = (t.date() - NOW.date()).days, t.hour
    if day == 0 and 6 <= h <= 9:
        return 2.5, 4.0, 9.5, 0.0
    if day == 0 and 10 <= h <= 13:
        return 4.6, 7.0, 13.5, 0.0                   # wind above 4 m/s
    if day == 0 and 14 <= h <= 18:
        return 3.4, 5.5, 15.0, 0.0                   # close to the limit
    if day == 0 and 19 <= h <= 23:
        return 3.0, 4.5, 12.0, (0.0 if h < 20 else 1.2)   # rain from 20:00
    if day == 1 and h < 5:
        return 1.5, 2.5, 3.0, 0.0                    # night below 5 C
    if day == 1 and 5 <= h <= 10:
        return 1.8, 3.0, 9.5, 0.0
    return 5.5, 8.0, 10.0, 0.0


def hours(weather=example_weather, start=NOW, n=72):
    return [sw.Hour(start + timedelta(hours=i), *weather(start + timedelta(hours=i))) for i in range(n)]


class TestRules(unittest.TestCase):

    def test_limits_from_config(self):
        self.assertEqual(RULES.wind_max_ms, 4.0)
        self.assertEqual(RULES.gust_max_ms, 6.0)                 # wind limit + 2 m/s
        self.assertEqual((RULES.temperature_min_c, RULES.temperature_max_c), (5.0, 25.0))
        self.assertEqual((RULES.min_window_hours, RULES.horizon_hours, RULES.max_windows), (4, 72, 3))
        self.assertEqual(RULES.origin["wind_max_ms"], "regulation")


class TestCheckHour(unittest.TestCase):

    def check(self, wind=2.0, gust=3.0, temp=10.0, rain=0.0, hour=8, work=None):
        return sw.check_hour(sw.Hour(NOW.replace(hour=hour), wind, gust, temp, rain), RULES, work)

    def test_good_hour(self):
        self.assertIs(self.check()["ok"], True)

    def test_each_limit_fails_the_hour(self):
        self.assertEqual(self.check(wind=4.1)["failed"], ["wind"])
        self.assertEqual(self.check(gust=6.1)["failed"], ["gust"])
        self.assertEqual(self.check(temp=4.9)["failed"], ["temperature_low"])
        self.assertEqual(self.check(temp=25.1)["failed"], ["temperature_high"])
        self.assertEqual(self.check(rain=0.3)["failed"], ["rain"])

    def test_limits_are_inclusive(self):
        self.assertIs(self.check(wind=4.0, gust=6.0, temp=25.0, rain=0.2)["ok"], True)

    def test_missing_value_is_unknown_never_good(self):
        c = self.check(wind=None)
        self.assertIsNone(c["ok"])
        self.assertEqual(c["missing"], ["wind"])

    def test_working_hours_only_exclude(self):
        self.assertEqual(self.check(hour=6, work=(7, 22))["failed"], ["outside_work_hours"])
        self.assertEqual(self.check(wind=5.0, hour=8, work=(7, 22))["failed"], ["wind"])


class TestNoteExample(unittest.TestCase):
    """Section 7 of the note: today 06-09 first, tomorrow 05-10 second, today 14-18 borderline third."""

    def setUp(self):
        self.result = sw.assess(SIGNAL, hours(), NOW, RULES)

    def test_status_and_signal(self):
        self.assertEqual(self.result["status"], "window_now")
        self.assertTrue(self.result["signal"])
        self.assertTrue(self.result["weather_ok_now"])
        self.assertEqual(self.result["coverage"], 1.0)

    def test_ranking_as_in_the_note(self):
        w = self.result["windows"]
        self.assertEqual([x["start"] for x in w],
                         [NOW, NOW + timedelta(hours=23), NOW.replace(hour=14)])
        self.assertEqual([x["confidence"] for x in w], ["confident", "confident", "borderline"])
        self.assertEqual([x["wind_margin_ms"] for x in w], [1.5, 2.2, 0.6])
        self.assertEqual([x["rank"] for x in w], [1, 2, 3])

    def test_window_fields(self):
        first = self.result["windows"][0]
        self.assertEqual((first["hours"], first["end"]), (4, NOW + timedelta(hours=4)))
        self.assertEqual(first["latest_start"], first["end"] - timedelta(hours=2))
        self.assertFalse(first["open_end"])
        self.assertFalse(first["indicative"])
        self.assertIn("margin below the wind limit 1.5 m/s", first["reason"])

    def test_rain_ends_the_afternoon_window(self):
        afternoon = self.result["windows"][2]
        self.assertEqual(afternoon["end"], NOW.replace(hour=20))   # 19:00 is dry, rain from 20:00


class TestWindows(unittest.TestCase):

    def test_short_runs_are_dropped(self):
        def three_good_hours(t):
            return (2.0, 3.0, 10.0, 0.0) if 8 <= t.hour < 11 and t.date() == NOW.date() else (5.5, 8.0, 10.0, 0.0)
        r = sw.assess(SIGNAL, hours(three_good_hours), NOW, RULES)
        self.assertEqual((r["status"], r["windows"]), ("no_window", []))

    def test_missing_hour_breaks_a_window(self):
        hs = hours()
        hs[2] = sw.Hour(hs[2].time, None, 4.0, 9.5, 0.0)          # 08:00 unknown: 06-07 is too short
        starts = [w["start"] for w in sw.assess(SIGNAL, hs, NOW, RULES)["windows"]]
        self.assertNotIn(NOW, starts)

    def test_open_end_and_indicative(self):
        r = sw.assess(SIGNAL, hours(lambda t: (2.0, 3.0, 10.0, 0.0) if t >= NOW + timedelta(hours=60) else (5.5, 8.0, 10.0, 0.0)),
                      NOW, RULES)
        w = r["windows"][0]
        self.assertTrue(w["open_end"])                             # good weather until the end of the 72 h
        self.assertTrue(w["indicative"])                           # starts 48 h or more ahead
        self.assertEqual(r["status"], "window_later")

    def test_at_most_three_windows(self):
        def every_other_six_hours(t):
            return (2.0, 3.0, 10.0, 0.0) if (t - NOW).total_seconds() // 3600 % 12 < 6 else (5.5, 8.0, 10.0, 0.0)
        self.assertEqual(len(sw.assess(SIGNAL, hours(every_other_six_hours), NOW, RULES)["windows"]), 3)


class TestSignal(unittest.TestCase):

    def test_reasons(self):
        self.assertEqual(sw.signal(SIGNAL), (True, "conditions_met"))
        self.assertEqual(sw.signal(None), (False, "no_assessment"))
        for status in ("stage_unknown", "out_of_window", "insufficient_data", "protected", "uncertain"):
            self.assertEqual(sw.signal({"status": status, "risk_class": "high", "conditions_met": False}), (False, status))
        self.assertEqual(sw.signal({"status": "ok", "risk_class": "medium", "conditions_met": False}), (False, "risk_not_high"))
        self.assertEqual(sw.signal({"status": "ok", "risk_class": "high", "conditions_met": False}), (False, "zone_not_b_or_c"))

    def test_no_window_without_signal(self):
        r = sw.assess({"status": "protected", "risk_class": "high", "conditions_met": False}, hours(), NOW, RULES)
        self.assertEqual((r["status"], r["windows"]), ("no_signal", []))
        self.assertEqual(len(r["hours"]), 72)                      # the weather is still described

    def test_no_forecast(self):
        empty = [sw.Hour(NOW + timedelta(hours=i), None, None, None, None) for i in range(72)]
        self.assertEqual(sw.assess(SIGNAL, empty, NOW, RULES)["status"], "no_forecast")


if __name__ == "__main__":
    unittest.main()
