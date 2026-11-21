"""Unit tests of the ULDK answer parser and the connector errors (offline)."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.ingestion.uldk_connector import UldkConnector, UldkError, parse_response  # noqa: E402

POLY = "SRID=4326;POLYGON((20.99 52.19, 21.0 52.19, 21.0 52.2, 20.99 52.19))"


class Parse(unittest.TestCase):
    def test_one_parcel(self):
        r = parse_response(f"0\n146505_8.0116.5|5|1-01-16|{POLY}\n")
        self.assertEqual(r, [{"parcel_id": "146505_8.0116.5", "parcel_number": "5", "region": "1-01-16", "ewkt": POLY}])

    def test_several_parcels(self):
        r = parse_response(f"2\n111_1.0001.1|1|A|{POLY}\n111_1.0001.2|2|A|{POLY}\n")
        self.assertEqual([p["parcel_id"] for p in r], ["111_1.0001.1", "111_1.0001.2"])

    def test_no_match_is_empty_not_an_error(self):
        self.assertEqual(parse_response("-1 brak wyników\nbłędny format odpowiedzi XML\n"), [])

    def test_garbage_is_an_error(self):
        for bad in ("", "\n", "<html>502 Bad Gateway</html>", "ERROR something"):
            with self.assertRaises(UldkError):
                parse_response(bad)

    def test_incomplete_or_wrong_srid_records_are_skipped(self):
        self.assertEqual(parse_response(f"1\nonly|two\n111|1|A|POLYGON((0 0, 1 0, 1 1, 0 0))\n"), [])


class Connector(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_lookup_by_xy_and_number(self, urlopen):
        resp = MagicMock()
        resp.read.return_value = f"0\n146505_8.0116.5|5|1-01-16|{POLY}\n".encode()
        urlopen.return_value.__enter__.return_value = resp
        self.assertEqual(UldkConnector.lookup_by_xy(21.0, 52.2)[0]["parcel_id"], "146505_8.0116.5")
        self.assertEqual(UldkConnector.lookup_by_number("146505_8.0116.5")[0]["parcel_number"], "5")
        url = urlopen.call_args[0][0].full_url
        self.assertIn("GetParcelByIdOrNr", url)
        self.assertIn("srid=4326", url)

    @patch("urllib.request.urlopen", side_effect=OSError("timed out"))
    def test_network_failure_is_uldk_error(self, _):
        with self.assertRaises(UldkError):
            UldkConnector.lookup_by_xy(21.0, 52.2)


if __name__ == "__main__":
    unittest.main()
