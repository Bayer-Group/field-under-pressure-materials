# -*- coding: utf-8 -*-
"""
Testy jednostkowe konektorów otwartych danych w trybie mock/offline.
"""

import sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import unittest
from unittest.mock import patch, MagicMock
from backend.app.ingestion.uldk_connector import UldkConnector
from backend.app.ingestion.imgw_connector import ImgwConnector

class TestIngestionConnectorsOffline(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_uldk_connector_success(self, mock_urlopen):
        # Prawdziwy format ULDK: status 0, potem rekord id|numer|obręb|EWKT (pola rozdzielone znakiem |)
        mock_response = MagicMock()
        mock_response.read.return_value = (b"0\n141201_1.0001.123/4|123/4|1-01-16|"
                                           b"SRID=4326;POLYGON((20.75 52.18, 20.76 52.18, 20.76 52.17, 20.75 52.17, 20.75 52.18))\n")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = UldkConnector.get_parcel_by_id("141201_1.0001.123/4")
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["teryt_id"], "141201_1.0001.123/4")
        self.assertTrue(res["wkt"].startswith("SRID=4326;POLYGON"))

    @patch("urllib.request.urlopen")
    def test_uldk_connector_not_found(self, mock_urlopen):
        # Brak działki w ULDK: status "-1 brak wyników"
        mock_response = MagicMock()
        mock_response.read.return_value = "-1 brak wyników\n".encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = UldkConnector.get_parcel_by_id("INVALID_ID")
        self.assertEqual(res["status"], "NOT_FOUND")

    @patch("urllib.request.urlopen")
    def test_imgw_connector_stations(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'[{"id_stacji": "12375", "stacja": "Warszawa", "temperatura": "15.4"}]'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        stations = ImgwConnector.get_latest_synop_stations()
        self.assertIsInstance(stations, list)
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0]["stacja"], "Warszawa")

if __name__ == "__main__":
    unittest.main()
