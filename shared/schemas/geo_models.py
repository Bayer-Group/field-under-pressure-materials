# -*- coding: utf-8 -*-
"""
Uniwersalne schematy danych geoprzestrzennych (Pydantic).
Wspólny kontrakt dla API FastAPI, wtyczki QGIS oraz frontendu webowego.
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel

class GeoFeatureRequest(BaseModel):
    feature_id: str
    teryt_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    attributes: Dict[str, Any] = {}

class SpatialMetric(BaseModel):
    name: str
    value: float
    unit: str = ""
    description: str = ""

class GeoAnalysisResponse(BaseModel):
    feature_id: str
    status: str = "PROCESSED"
    teryt_id: Optional[str] = None
    metrics: Dict[str, float] = {}
    details: List[SpatialMetric] = []
    attributes: Dict[str, Any] = {}
    layers: Dict[str, str] = {}

class MeteoObservation(BaseModel):
    station: str
    temp_c: float
    wind_ms: float
    humidity_pct: float
    precip_mm: float
