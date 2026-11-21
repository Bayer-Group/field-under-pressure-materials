"""Unit tests of the pure parts of the field adapter: ids of the client and the validation id (no database)."""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.api.v1.endpoints.fields import external_id, internal_id  # noqa: E402
from backend.app.core.config import AUTH_SECRET  # noqa: E402
from backend.app.core.security import make_token  # noqa: E402
from backend.app.services import geometry_validation as gv  # noqa: E402

SQ = {"type": "Polygon", "coordinates": [[[20.0, 52.0], [20.1, 52.0], [20.1, 52.1], [20.0, 52.0]]]}
AREAS = [{"crop_area_id": "a1", "geometry": SQ}, {"crop_area_id": "a2", "geometry": SQ}]


class Ids(unittest.TestCase):
    def test_roundtrip_and_isolation(self):
        self.assertEqual(internal_id("sbx-1", "field-demo-1"), "sbx-1~field-demo-1")
        self.assertEqual(external_id("sbx-1", "sbx-1~field-demo-1"), "field-demo-1")
        self.assertNotEqual(internal_id("sbx-1", "field-demo-1"), internal_id("sbx-2", "field-demo-1"))

    def test_generated_and_cloned_ids(self):
        self.assertEqual(external_id("farmer-001", "f-farmer-001-1"), "f-farmer-001-1")             # a generated field keeps its id
        self.assertEqual(external_id("sbx-ab12", "sbx-ab12-f-farmer-021-1"), "f-farmer-021-1")       # a sandbox copy loses the prefix


class RequestHash(unittest.TestCase):
    def test_order_does_not_matter_content_does(self):
        h = gv.request_hash(["p2", "p1"], AREAS)
        self.assertEqual(h, gv.request_hash(["p1", "p2"], list(reversed(AREAS))))
        moved = [dict(AREAS[0], geometry={"type": "Polygon", "coordinates": [[[20.0, 52.0], [20.1, 52.0], [20.1, 52.2], [20.0, 52.0]]]}), AREAS[1]]
        self.assertNotEqual(h, gv.request_hash(["p1", "p2"], moved))
        self.assertNotEqual(h, gv.request_hash(["p1"], AREAS))


class ValidationId(unittest.TestCase):
    def token(self, parcels, areas, needed, ttl=600, now=None):
        return make_token({"h": gv.request_hash(parcels, areas), "i": sorted(needed)}, AUTH_SECRET, ttl, now=now)

    def test_accepts_exactly_this_request_and_findings(self):
        t = self.token(["p1"], AREAS, ["gap:g1", "outside:o1"])
        self.assertIsNone(gv.check_validation_id(t, ["p1"], AREAS, ["outside:o1", "gap:g1"]))

    def test_rejects_stale_missing_and_foreign(self):
        t = self.token(["p1"], AREAS, ["gap:g1"])
        self.assertIn("required", gv.check_validation_id(None, ["p1"], AREAS, ["gap:g1"]))
        self.assertIn("another geometry", gv.check_validation_id(t, ["p1", "p2"], AREAS, ["gap:g1"]))   # another selection
        self.assertIn("findings changed", gv.check_validation_id(t, ["p1"], AREAS, ["gap:g1", "gap:g2"]))
        self.assertIn("invalid or expired", gv.check_validation_id("abc.def", ["p1"], AREAS, ["gap:g1"]))
        self.assertIn("invalid or expired", gv.check_validation_id(self.token(["p1"], AREAS, [], ttl=1, now=0), ["p1"], AREAS, []))


if __name__ == "__main__":
    unittest.main()
