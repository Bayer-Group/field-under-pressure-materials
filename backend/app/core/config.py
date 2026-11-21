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

# Baza (schemat serve) i uwierzytelnianie demo
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("LOAD_DB_DSN", "")
# Bez AUTH_SECRET tokeny są podpisywane losowym kluczem i tracą ważność po restarcie (bezpieczne domyślnie).
AUTH_SECRET = os.environ.get("AUTH_SECRET") or os.urandom(32).hex()
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "28800"))

# Dozwolone originy CORS
CORS_ORIGINS = ["*"]
