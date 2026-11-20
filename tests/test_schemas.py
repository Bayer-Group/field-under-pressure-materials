# -*- coding: utf-8 -*-
"""
Testy jednostkowe schematów Pydantic (shared/schemas/geo_models.py).
"""

import sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import unittest

try:
    from shared.schemas.geo_models import (
        GeoFeatureRequest,
        SpatialMetric,
        GeoAnalysisResponse,
        MeteoObservation
    )
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False


@unittest.skipIf(not PYDANTIC_AVAILABLE, "Pomiń testy schematów - Pydantic nie jest zainstalowany w środowisku")
class TestGeoSchemas(unittest.TestCase):
    def test_geo_feature_request_defaults(self):
        req = GeoFeatureRequest(feature_id="PARCEL-001")
        self.assertEqual(req.feature_id, "PARCEL-001")
        self.assertIsNone(req.teryt_id)
        self.assertIsNone(req.lat)
        self.assertIsNone(req.lon)
        self.assertEqual(req.attributes, {})

    def test_spatial_metric_serialization(self):
        metric = SpatialMetric(
            name="Area",
            value=14.5,
            unit="ha",
            description="Powierzchnia w hektarach"
        )
        data = metric.model_dump() if hasattr(metric, "model_dump") else metric.dict()
        self.assertEqual(data["name"], "Area")
        self.assertEqual(data["value"], 14.5)
        self.assertEqual(data["unit"], "ha")

    def test_geo_analysis_response(self):
        resp = GeoAnalysisResponse(
            feature_id="PARCEL-100",
            status="PROCESSED",
            metrics={"area_ha": 14.5, "perimeter_m": 1200.0}
        )
        self.assertEqual(resp.feature_id, "PARCEL-100")
        self.assertEqual(resp.status, "PROCESSED")
        self.assertIn("area_ha", resp.metrics)
        self.assertEqual(resp.metrics["area_ha"], 14.5)

    def test_meteo_observation(self):
        obs = MeteoObservation(
            station="Warszawa-Okęcie",
            temp_c=16.5,
            wind_ms=4.2,
            humidity_pct=72.0,
            precip_mm=0.0
        )
        self.assertEqual(obs.station, "Warszawa-Okęcie")
        self.assertEqual(obs.temp_c, 16.5)

if __name__ == "__main__":
    unittest.main()
