# -*- coding: utf-8 -*-
"""
Testy jednostkowe układów współrzędnych i obliczeń geometrycznych.
"""

import sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import unittest
from shared.constants.poland_crs import (
    EPSG_POLAND_1992,
    EPSG_WGS84,
    EPSG_WEB_MERCATOR,
    BBOX_POLAND_4326,
    BBOX_POLAND_2180
)
from backend.app.domain.geometry_metrics import calculate_bounding_box

class TestCrsAndGeometry(unittest.TestCase):
    def test_epsg_constants(self):
        self.assertEqual(EPSG_POLAND_1992, 2180)
        self.assertEqual(EPSG_WGS84, 4326)
        self.assertEqual(EPSG_WEB_MERCATOR, 3857)

    def test_poland_bbox(self):
        # min_lon < max_lon, min_lat < max_lat
        self.assertLess(BBOX_POLAND_4326[0], BBOX_POLAND_4326[2])
        self.assertLess(BBOX_POLAND_4326[1], BBOX_POLAND_4326[3])
        # Sprawdzenie czy Warszawa (21.01, 52.23) mieści się w BBOX
        lon_waw, lat_waw = 21.01, 52.23
        self.assertTrue(BBOX_POLAND_4326[0] <= lon_waw <= BBOX_POLAND_4326[2])
        self.assertTrue(BBOX_POLAND_4326[1] <= lat_waw <= BBOX_POLAND_4326[3])

    def test_calculate_bounding_box(self):
        coords = [
            (20.0, 52.0),
            (21.0, 52.0),
            (21.0, 53.0),
            (20.0, 53.0)
        ]
        bbox = calculate_bounding_box(coords)
        self.assertEqual(bbox, [20.0, 52.0, 21.0, 53.0])

    def test_calculate_bounding_box_empty(self):
        bbox = calculate_bounding_box([])
        self.assertEqual(bbox, [0.0, 0.0, 0.0, 0.0])

if __name__ == "__main__":
    unittest.main()
