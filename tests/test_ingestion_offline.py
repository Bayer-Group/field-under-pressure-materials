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
        # Symulacja poprawnej odpowiedzi GUGiK ULDK: kod 0 + linia WKT
        mock_response = MagicMock()
        mock_response.read.return_value = b"0\nPOLYGON((20.75 52.18, 20.76 52.18, 20.76 52.17, 20.75 52.17, 20.75 52.18));Mazowieckie;Warszawa\n"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = UldkConnector.get_parcel_by_id("141201_1.0001.123/4")
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["teryt_id"], "141201_1.0001.123/4")
        self.assertTrue(res["wkt_2180"].startswith("POLYGON"))

    @patch("urllib.request.urlopen")
    def test_uldk_connector_not_found(self, mock_urlopen):
        # Symulacja błędu braku działki w ULDK (kod -1)
        mock_response = MagicMock()
        mock_response.read.return_value = b"-1\nNie znaleziono obiektu\n"
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
