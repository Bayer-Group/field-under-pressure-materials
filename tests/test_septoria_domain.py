"""Unit tests of backend/app/domain/septoria.py (pure functions, no database)."""
import os
import sys
import tomllib
import unittest
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.domain import septoria as sp  # noqa: E402

with open(os.path.join(BASE_DIR, "config", "septoria.toml"), "rb") as fh:
    RULES = sp.Rules.from_config(tomllib.load(fh))

DAY = date(2024, 5, 15)


def window(wet_run: int, at: int = 0, n: int = 72, missing=()):
    """n dry hours with one wet run of `wet_run` hours starting at index `at`; indexes in `missing` are None."""
    f = [False] * n
    for i in range(at, at + wet_run):
        f[i] = True
    for i in missing:
        f[i] = None
    return f


def run(flags, **kw):
    args = dict(gdd=300.0, bbch_override=None, winter_crop=True, spray_date=None, protection_days=None, rules=RULES)
    args.update(kw)
    return sp.assess(DAY, flags, **args)


class WetHour(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(sp.wet_hour(85.0, 0.0, 85.0, 0.2))        # RH at the threshold
        self.assertFalse(sp.wet_hour(84.9, 0.2, 85.0, 0.2))       # precipitation must exceed the threshold
        self.assertTrue(sp.wet_hour(50.0, 0.3, 85.0, 0.2))
        self.assertIsNone(sp.wet_hour(None, None, 85.0, 0.2))
        self.assertIsNone(sp.wet_hour(50.0, None, 85.0, 0.2))     # the missing value could have made it wet
        self.assertTrue(sp.wet_hour(90.0, None, 85.0, 0.2))


class LongestRun(unittest.TestCase):
    def test_run_and_gaps(self):
        f = [True, True, False, True, True, True, None, True]
        self.assertEqual(sp.longest_run(f, False), 3)
        self.assertEqual(sp.longest_run(f, True), 5)
        self.assertEqual(sp.longest_gap([None, None, True, None]), 2)

    def test_classes_at_the_thresholds(self):
        self.assertEqual(sp.classify(9, RULES), "low")
        self.assertEqual(sp.classify(10, RULES), "medium")
        self.assertEqual(sp.classify(19, RULES), "medium")
        self.assertEqual(sp.classify(20, RULES), "high")


class Zones(unittest.TestCase):
    def test_zone_limits(self):
        self.assertEqual(sp.zone(159.9, RULES), "A")
        self.assertEqual(sp.zone(160.0, RULES), "B")
        self.assertEqual(sp.zone(510.0, RULES), "C")
        self.assertIsNone(sp.zone(None, RULES))

    def test_stage_sources(self):
        self.assertEqual(sp.growth_stage(DAY, 300.0, None, RULES), ("B", "estimated", True))
        self.assertEqual(sp.growth_stage(DAY, 100.0, None, RULES), ("A", "estimated", False))
        self.assertEqual(sp.growth_stage(DAY, None, None, RULES), (None, "calendar", True))
        self.assertEqual(sp.growth_stage(date(2024, 7, 1), None, None, RULES), (None, "calendar", False))
        self.assertEqual(sp.growth_stage(DAY, 100.0, 37, RULES), ("A", "override", True))
        self.assertEqual(sp.growth_stage(DAY, 300.0, 65, RULES)[2], False)


class Assess(unittest.TestCase):
    def test_high_sets_conditions(self):
        r = sp.assess(DAY, window(20), gdd=300.0, bbch_override=None, winter_crop=True, spray_date=None,
                      protection_days=None, rules=RULES)
        self.assertEqual((r["risk_class"], r["status"], r["conditions_met"]), ("high", "ok", True))
        self.assertEqual((r["h_low"], r["h_high"], r["coverage"]), (20, 20, 1.0))

    def test_medium_and_low_do_not(self):
        self.assertEqual(run(window(15))["risk_class"], "medium")
        self.assertFalse(run(window(15))["conditions_met"])
        self.assertEqual(run(window(3))["risk_class"], "low")

    def test_run_is_continuous(self):
        f = window(12) + [False] + window(12)[:12] + [False] * 35        # 12 + gap + 12, total 24 but H = 12
        r = run(f)
        self.assertEqual((r["h_hours"], r["risk_class"]), (12, "medium"))

    def test_uncertain_when_a_short_gap_decides(self):
        r = run(window(19, missing=[19, 20]))                            # 19 h wet, 2 missing hours right after
        self.assertEqual((r["status"], r["h_low"], r["h_high"]), ("uncertain", 19, 21))
        self.assertFalse(r["conditions_met"])

    def test_long_gap_is_insufficient_data(self):
        r = run(window(19, missing=range(19, 25)))                       # 6 missing hours (> max_gap_hours = 4)
        self.assertEqual((r["status"], r["risk_class"]), ("insufficient_data", None))

    def test_low_coverage_is_insufficient_data(self):
        r = run(window(0, missing=range(0, 30)))
        self.assertEqual(r["status"], "insufficient_data")
        self.assertLess(r["coverage"], RULES.min_coverage)

    def test_missing_hours_that_cannot_change_the_class_are_ok(self):
        r = run(window(25, at=10, missing=[60, 61]))
        self.assertEqual((r["status"], r["risk_class"]), ("ok", "high"))

    def test_protection(self):
        r = run(window(25), spray_date=date(2024, 5, 10), protection_days=10)
        self.assertEqual((r["status"], r["protected_until"], r["conditions_met"]), ("protected", date(2024, 5, 20), False))
        r = run(window(25), spray_date=date(2024, 5, 5), protection_days=10)           # ended 15 May: still protected
        self.assertEqual(r["status"], "protected")
        r = run(window(25), spray_date=date(2024, 5, 4), protection_days=10)           # ended 14 May
        self.assertEqual((r["status"], r["conditions_met"]), ("ok", True))

    def test_out_of_window_and_other_crops(self):
        self.assertEqual(run(window(25), gdd=100.0)["status"], "out_of_window")
        self.assertIsNone(run(window(25), gdd=100.0)["risk_class"])
        r = run(window(25), winter_crop=False)
        self.assertEqual((r["status"], r["conditions_met"]), ("stage_unknown", False))

    def test_zone_a_never_sets_conditions(self):
        self.assertFalse(run(window(25), gdd=100.0)["conditions_met"])

    def test_hash_changes_with_input(self):
        a, b = run(window(25)), run(window(24))
        self.assertNotEqual(a["input_hash"], b["input_hash"])
        self.assertEqual(a["input_hash"], run(window(25))["input_hash"])


if __name__ == "__main__":
    unittest.main()
