"""Handing out the example farms one after another, and the example farms being read-only (no database)."""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import HTTPException  # noqa: E402

from backend.app.api.v1.endpoints.farm_write import _require_writes, pick_template, template_pool  # noqa: E402

OWNERS = ["farmer-003", "farmer-001", "farmer-002"]


class Pool(unittest.TestCase):
    def test_only_the_chosen_farms(self):
        self.assertEqual(template_pool(OWNERS, ["farmer-002", "farmer-003"]), ["farmer-003", "farmer-002"])

    def test_a_chosen_farm_missing_from_the_database_is_skipped(self):
        self.assertEqual(template_pool(OWNERS, ["farmer-001", "farmer-099"]), ["farmer-001"])

    def test_every_farm_when_none_is_chosen_or_none_exists(self):
        self.assertEqual(template_pool(OWNERS, []), OWNERS)
        self.assertEqual(template_pool(OWNERS, ["farmer-099"]), OWNERS)


class Rotation(unittest.TestCase):
    def test_one_after_another_and_around(self):
        got = [pick_template(OWNERS, n) for n in range(1, 8)]
        self.assertEqual(got, ["farmer-001", "farmer-002", "farmer-003", "farmer-001", "farmer-002", "farmer-003", "farmer-001"])

    def test_every_example_farm_is_used_before_one_repeats(self):
        n_owners = 100
        owners = [f"farmer-{i:03d}" for i in range(1, n_owners + 1)]
        room = [pick_template(owners, n) for n in range(37, 37 + 90)]          # 90 visitors, wherever the counter is
        self.assertEqual(len(set(room)), 90)

    def test_a_single_farm(self):
        self.assertEqual({pick_template(["farmer-001"], n) for n in range(1, 5)}, {"farmer-001"})


class ReadOnlyExampleFarms(unittest.TestCase):
    def test_a_sandbox_owner_may_write(self):
        _require_writes({"role": "farmer", "owner_id": "sbx-abc123"})

    def test_an_example_farm_may_not(self):
        with self.assertRaises(HTTPException) as e:
            _require_writes({"role": "farmer", "owner_id": "farmer-014"})
        self.assertEqual(e.exception.status_code, 403)
        self.assertIn("sandbox", e.exception.detail)

    def test_other_roles_still_may_not(self):
        for role in ("viewer", "analyst"):
            with self.assertRaises(HTTPException):
                _require_writes({"role": role, "owner_id": "sbx-abc123"})


if __name__ == "__main__":
    unittest.main()
