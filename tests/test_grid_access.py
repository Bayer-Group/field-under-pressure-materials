"""Who may read the grid layer and the risk surface (FastAPI TestClient with a stand-in for the database)."""
import datetime
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.api.v1.endpoints import farm  # noqa: E402
from backend.app.core.db import get_db  # noqa: E402
from backend.app.main import app  # noqa: E402

DAY = datetime.date(2026, 11, 21)
LATTICE = [(20.0 + i * 0.044, 52.0 + j * 0.044, 8 + 3 * (i + j)) for j in range(3) for i in range(3)]     # 3 x 3 cells, 8..20 h


class FakeCon:
    queries = 0                                                          # how many times the database was asked

    def execute(self, sql, params=()):
        self.sql = sql
        FakeCon.queries += 1
        return self

    def fetchall(self):
        if "ST_X(ST_Centroid" in self.sql:                               # the surface query
            return [{"lon": lo, "lat": la, "h_low": h, "date": DAY} for lo, la, h in LATTICE]
        return [{"f": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []},      # the grid query
                       "properties": {"grid_id": str(i), "risk_class": "medium", "h_low": h, "h_high": h, "date": DAY.isoformat()}}}
                for i, (_, _, h) in enumerate(LATTICE)]


def as_user(role, owner="u1"):
    app.dependency_overrides[farm.current_user] = lambda: {"sub": owner, "owner_id": owner, "role": role}
    app.dependency_overrides[get_db] = lambda: FakeCon()
    return TestClient(app)


class GridAccess(unittest.TestCase):
    def setUp(self):
        farm._RESPONSES.clear()
        FakeCon.queries = 0

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_a_farmer_reads_the_grid_and_the_surface(self):
        c = as_user("farmer", "visitor-1")
        g = c.get("/api/v1/grid/risk")
        self.assertEqual(g.status_code, 200)
        self.assertEqual(len(g.json()["features"]), 9)
        self.assertIn("risk_index", g.json()["features"][0]["properties"])
        s = c.get("/api/v1/grid/risk/surface")
        self.assertEqual(s.status_code, 200)
        self.assertEqual(s.json()["method"], "interpolate")
        self.assertEqual(c.get("/api/v1/grid/risk/surface", params={"format": "png"}).headers["content-type"], "image/png")
        self.assertEqual(c.get("/api/v1/grid/risk/surface", params={"format": "asc", "value": "hours"}).status_code, 200)

    def test_viewer_role_too(self):
        self.assertEqual(as_user("viewer", "viewer-1").get("/api/v1/grid/risk/surface").status_code, 200)

    def test_smooth_is_for_the_analyst(self):
        self.assertEqual(as_user("farmer", "visitor-2").get("/api/v1/grid/risk/surface", params={"method": "smooth"}).status_code, 403)
        self.assertEqual(as_user("analyst", "analyst-t").get("/api/v1/grid/risk/surface", params={"method": "smooth"}).status_code, 200)

    def test_no_token_and_bad_parameters(self):
        app.dependency_overrides[get_db] = lambda: FakeCon()
        self.assertEqual(TestClient(app).get("/api/v1/grid/risk/surface").status_code, 401)
        self.assertEqual(TestClient(app).get("/api/v1/grid/risk").status_code, 401)
        c = as_user("farmer", "visitor-3")
        self.assertEqual(c.get("/api/v1/grid/risk/surface", params={"resolution": 0.005}).status_code, 422)
        self.assertEqual(c.get("/api/v1/grid/risk/surface", params={"format": "gif"}).status_code, 422)


class ResponseCache(unittest.TestCase):
    def setUp(self):
        farm._RESPONSES.clear()
        FakeCon.queries = 0

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_the_second_identical_request_does_not_ask_the_database(self):
        c = as_user("farmer", "cache-1")
        a = c.get("/api/v1/grid/risk/surface", params={"format": "png", "resolution": 0.03})
        asked = FakeCon.queries
        b = c.get("/api/v1/grid/risk/surface", params={"format": "png", "resolution": 0.03})
        self.assertEqual((a.status_code, b.status_code), (200, 200))
        self.assertEqual(FakeCon.queries, asked)                           # served from the cache
        self.assertEqual(a.content, b.content)
        self.assertEqual(a.headers["x-bounds"], b.headers["x-bounds"])
        c.get("/api/v1/grid/risk/surface", params={"format": "png", "resolution": 0.04})
        self.assertGreater(FakeCon.queries, asked)                         # other parameters are another entry

    def test_every_format_and_the_grid_come_back_identical_from_the_cache(self):
        c = as_user("farmer", "cache-2")
        for path, params in (("/api/v1/grid/risk", {}), ("/api/v1/grid/risk/surface", {}),
                             ("/api/v1/grid/risk/surface", {"format": "asc", "value": "hours"})):
            first, second = c.get(path, params=params), c.get(path, params=params)
            self.assertEqual(first.content, second.content, path)
            self.assertEqual(first.headers["content-type"], second.headers["content-type"], path)

    def test_the_cache_does_not_skip_the_roles(self):
        farmer = as_user("farmer", "cache-3")
        farmer.get("/api/v1/grid/risk/surface", params={"method": "smooth", "resolution": 0.02})
        self.assertEqual(farmer.get("/api/v1/grid/risk/surface", params={"method": "smooth"}).status_code, 403)
        analyst = as_user("analyst", "cache-4")
        self.assertEqual(analyst.get("/api/v1/grid/risk/surface", params={"method": "smooth"}).status_code, 200)
        farmer = as_user("farmer", "cache-3")                              # the override is global: set the farmer again
        self.assertEqual(farmer.get("/api/v1/grid/risk/surface", params={"method": "smooth"}).status_code, 403)   # still 403 after a hit


if __name__ == "__main__":
    unittest.main()
