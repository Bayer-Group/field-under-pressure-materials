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
    def execute(self, sql, params=()):
        self.sql = sql
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


if __name__ == "__main__":
    unittest.main()
