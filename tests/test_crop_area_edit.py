"""Editing one crop area and its sprays: the checks that need no database (bodies, roles, ids) through the API with a stand-in."""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.api.v1.endpoints import farm  # noqa: E402
from backend.app.core.db import get_db, get_db_rw  # noqa: E402
from backend.app.main import app  # noqa: E402


class FakeCon:
    """Finds no rows unless it is given some; remembers what it was asked."""

    def __init__(self, row=None):
        self.row, self.asked = row, []

    def execute(self, sql, params=()):
        self.asked.append((sql, params))
        return self

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []


def as_user(role="farmer", owner="sbx-t1", con=None):
    con = con or FakeCon()
    app.dependency_overrides[farm.current_user] = lambda: {"sub": owner, "owner_id": owner, "role": role}
    app.dependency_overrides[get_db_rw] = lambda: con
    app.dependency_overrides[get_db] = lambda: con
    return TestClient(app)


class Bodies(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_patch_area_rejects_bad_bodies_before_the_database(self):
        c = as_user()
        self.assertEqual(c.patch("/api/v1/crop-areas/a1", json={}).status_code, 422)                           # nothing to change
        self.assertEqual(c.patch("/api/v1/crop-areas/a1", json={"bbch_override": 40}).status_code, 422)          # not a tile of the contract
        self.assertEqual(c.patch("/api/v1/crop-areas/a1", json={"sowing_date": "not a date"}).status_code, 422)
        self.assertEqual(c.patch("/api/v1/crop-areas/a1", json={"sprays_confirmed": False}).status_code, 422)   # only true

    def test_patch_spray_rejects_bad_bodies(self):
        c = as_user()
        for body in ({}, {"protection_duration_days": 0}, {"protection_duration_days": 61}, {"date": None}, {"date": "x"}):
            self.assertEqual(c.patch("/api/v1/crop-areas/a1/sprays/5", json=body).status_code, 422, body)
        self.assertEqual(c.patch("/api/v1/crop-areas/a1/sprays/abc", json={"protection_duration_days": 5}).status_code, 422)   # id is a number

    def test_valid_bodies_reach_the_lookup_and_a_missing_area_is_404(self):
        c = as_user()
        self.assertEqual(c.patch("/api/v1/crop-areas/a1", json={"bbch_override": 37}).status_code, 404)
        self.assertEqual(c.patch("/api/v1/crop-areas/a1", json={"bbch_override": None}).status_code, 404)          # null clears it
        self.assertEqual(c.patch("/api/v1/crop-areas/a1/sprays/5", json={"protection_duration_days": 10}).status_code, 404)
        self.assertEqual(c.delete("/api/v1/crop-areas/a1/sprays/5").status_code, 404)
        self.assertEqual(c.get("/api/v1/crop-areas/a1/sprays").status_code, 404)

    def test_only_a_farmer_writes(self):
        for role in ("viewer", "analyst"):
            c = as_user(role)
            self.assertEqual(c.patch("/api/v1/crop-areas/a1", json={"bbch_override": 37}).status_code, 403, role)
            self.assertEqual(c.delete("/api/v1/crop-areas/a1/sprays/5").status_code, 403, role)
            app.dependency_overrides.clear()

    def test_no_token(self):
        app.dependency_overrides[get_db_rw] = lambda: FakeCon()
        self.assertEqual(TestClient(app).patch("/api/v1/crop-areas/a1", json={"bbch_override": 37}).status_code, 401)
        self.assertEqual(TestClient(app).delete("/api/v1/crop-areas/a1/sprays/5").status_code, 401)


class AreaIds(unittest.TestCase):
    def test_the_id_of_fields_the_api_format_and_an_older_copy_are_all_looked_up(self):
        con = FakeCon({"id": "sbx-t1~a1"})
        stored = farm._require_area(con, {"owner_id": "sbx-t1", "role": "farmer"}, "a1")
        self.assertEqual(stored, "sbx-t1~a1")
        sql, params = con.asked[0]
        self.assertIn("owner_id = %s", sql)                                            # always limited to the owner
        self.assertEqual(params[0], ["a1", "sbx-t1~a1", "sbx-t1-a1"])
        self.assertEqual(params[1:], ("sbx-t1", "a1"))                                 # the owner, then the preference for the exact id

    def test_missing_is_404_and_the_analyst_is_not_limited_to_an_owner(self):
        with self.assertRaises(HTTPException) as e:
            farm._require_area(FakeCon(None), {"owner_id": "sbx-t1", "role": "farmer"}, "zzz")
        self.assertEqual(e.exception.status_code, 404)
        con = FakeCon({"id": "x"})
        farm._require_area(con, {"owner_id": "analyst", "role": "analyst"}, "x")
        self.assertNotIn("owner_id = %s", con.asked[0][0])


if __name__ == "__main__":
    unittest.main()
