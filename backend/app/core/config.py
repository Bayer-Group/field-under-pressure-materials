# -*- coding: utf-8 -*-
"""
Konfiguracja backendu FastAPI (PyQGIS FastAPI Bridge).
"""

import os

PROJECT_NAME = "PyQGIS FastAPI Bridge API"
API_V1_STR = "/api/v1"

# Polskie publiczne serwisy geodezyjne i pogodowe (otwarte dane publiczne)
ULDK_API_URL = os.environ.get("GUGIK_ULDK_URL", "https://uldk.gugik.gov.pl/")
IMGW_SYNOP_URL = os.environ.get("IMGW_SYNOP_URL", "https://danepubliczne.imgw.pl/api/data/synop")
IMGW_WARNINGS_URL = os.environ.get("IMGW_WARNINGS_URL", "https://danepubliczne.imgw.pl/api/data/warnings/meteo")

# Dozwolone originy CORS
CORS_ORIGINS = ["*"]
