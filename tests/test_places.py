"""Unit tests of the place search: the parsing and ordering of the GUGiK answer (offline)."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.services import places  # noqa: E402


def rec(city, voiv, county, commune, x, y):
    return {"city": city, "voivodeship": voiv, "county": county, "commune": commune, "x": str(x), "y": str(y)}


UUG = {"type": "city", "found objects": 4, "results": {
    "1": rec("Ostrołęka", "mazowieckie", "grójecki", "Warka", 21.1, 51.8),
    "2": rec("Ostrołęka", "mazowieckie", "Ostrołęka", "Ostrołęka", 21.57, 53.08),
    "3": rec("Ostrołęka", "łódzkie", "łowicki", "Chąśno", 20.1, 52.0),
    "4": rec("Ostrołęka", "mazowieckie", "radomski", "Przytyk", 21.2, 51.5)}}


class Parse(unittest.TestCase):
    def test_only_the_voivodeship_and_labels(self):
        got = places.parse_uug(UUG)
        self.assertEqual(len(got), 3)                                       # the one in the Łódź voivodeship is dropped
        self.assertEqual({p["label"] for p in got},
                         {"Ostrołęka", "Ostrołęka, gm. Warka, pow. grójecki", "Ostrołęka, gm. Przytyk, pow. radomski"})
        self.assertTrue(all(p["zoom"] == places.ZOOM and p["source"] == "gugik" for p in got))

    def test_coordinates_are_lon_lat(self):
        p = next(p for p in places.parse_uug(UUG) if p["label"] == "Ostrołęka")
        self.assertEqual((p["lon"], p["lat"]), (21.57, 53.08))

    def test_bad_records_are_skipped(self):
        self.assertEqual(places.parse_uug({"results": None}), [])
        self.assertEqual(places.parse_uug({"results": {"1": {"voivodeship": "mazowieckie", "city": "X", "x": "a", "y": "b"}}}), [])


class Search(unittest.TestCase):
    def setUp(self):
        places._cache.clear()

    def con(self, rows=()):
        con = MagicMock()
        con.execute.return_value.fetchall.return_value = list(rows)
        return con

    @patch("urllib.request.urlopen")
    def test_towns_first_then_known_names_without_duplicates(self, urlopen):
        resp = MagicMock()
        import json
        resp.read.return_value = json.dumps(UUG).encode()
        urlopen.return_value.__enter__.return_value = resp
        known = [{"region": "Ostrołęka-Wieś", "commune": "Płońsk", "county": "powiat płoński", "lon": 20.4, "lat": 52.6}]
        got = places.search(self.con(known), "Ostrołęka")
        self.assertEqual(got[0]["label"], "Ostrołęka")                      # the town with the rights of a county first
        self.assertEqual(got[-1]["source"], "parcels")
        self.assertEqual(len({(p["name"], p["label"]) for p in got}), len(got))

    @patch("urllib.request.urlopen", side_effect=OSError("down"))
    def test_service_down_gives_known_names_only(self, _):
        known = [{"region": "Krępica", "commune": "Płońsk", "county": "powiat płoński", "lon": 20.5, "lat": 52.6}]
        got = places.search(self.con(known), "Krę")
        self.assertEqual([p["label"] for p in got], ["Krępica, gm. Płońsk, pow. płoński"])

    def test_short_query_is_empty_and_the_cache_is_used(self):
        self.assertEqual(places.search(self.con(), "a"), [])
        with patch("urllib.request.urlopen", side_effect=OSError("down")) as u:
            places.search(self.con(), "Radom")
            places.search(self.con(), "Radom")
            self.assertEqual(u.call_count, 2)                                # a failure is not cached


if __name__ == "__main__":
    unittest.main()
