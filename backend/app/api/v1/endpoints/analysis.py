# -*- coding: utf-8 -*-
"""
Uniwersalny endpoint analityki geoprzestrzennej.
Zwraca kontrakt 'GeoAnalysisResponse' konsumowany przez wtyczkę QGIS oraz frontend webowy.
"""

from fastapi import APIRouter
from shared.schemas.geo_models import GeoAnalysisResponse, SpatialMetric

router = APIRouter()

@router.get("/{feature_id}", response_model=GeoAnalysisResponse)
async def analyze_feature(
    feature_id: str,
    teryt_id: str = None,
    lat: float = 52.18,
    lon: float = 20.76
):
    """Przykładowy endpoint wykonujący prostą analizę przestrzenną."""
    metrics = {
        "calculated_area_ha": 12.4,
        "perimeter_m": 1420.0,
        "sample_index": 0.72
    }

    details = [
        SpatialMetric(name="Area", value=12.4, unit="ha", description="Powierzchnia obiektu"),
        SpatialMetric(name="Centroid Lat", value=lat, unit="deg", description="Szerokość geograficzna środka"),
        SpatialMetric(name="Centroid Lon", value=lon, unit="deg", description="Długość geograficzna środka")
    ]

    return GeoAnalysisResponse(
        feature_id=feature_id,
        status="PROCESSED",
        teryt_id=teryt_id,
        metrics=metrics,
        details=details,
        attributes={
            "processed_by": "FastAPI Spatial Engine",
            "source_crs": "EPSG:2180"
        },
        layers={
            "result_geojson": f"/api/v1/layers/{feature_id}.geojson"
        }
    )
