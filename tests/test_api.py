# -*- coding: utf-8 -*-
"""
Testy jednostkowe API FastAPI i logiki endpointów.
"""

import sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import unittest
import asyncio

try:
    from backend.app.main import app, health_check
    from backend.app.api.v1.endpoints.analysis import analyze_feature
    from shared.schemas.geo_models import GeoAnalysisResponse
    FASTAPI_INSTALLED = True
except ImportError:
    FASTAPI_INSTALLED = False

@unittest.skipIf(not FASTAPI_INSTALLED, "Pomiń testy FastAPI - moduł nie jest zainstalowany w środowisku")
class TestApiEndpoints(unittest.TestCase):
    def test_app_initialization(self):
        self.assertIsNotNone(app)
        self.assertEqual(app.title, "PyQGIS FastAPI Bridge API")

    def test_health_endpoint(self):
        result = asyncio.run(health_check())
        self.assertEqual(result["status"], "online")
        self.assertIn("service", result)

    def test_analysis_endpoint(self):
        resp = asyncio.run(analyze_feature(
            feature_id="TEST-001",
            teryt_id="141201_1.0001.123/4",
            lat=52.20,
            lon=20.80
        ))
        self.assertIsInstance(resp, GeoAnalysisResponse)
        self.assertEqual(resp.feature_id, "TEST-001")
        self.assertEqual(resp.status, "PROCESSED")
        self.assertEqual(resp.teryt_id, "141201_1.0001.123/4")
        self.assertIn("calculated_area_ha", resp.metrics)
        self.assertTrue(len(resp.details) > 0)

if __name__ == "__main__":
    unittest.main()
