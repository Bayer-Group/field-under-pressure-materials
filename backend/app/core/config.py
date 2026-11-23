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

# Tryb demo (sandbox dla publiczności): limity i wyłącznik zapisu
DEMO_READONLY = os.environ.get("DEMO_READONLY", "0") == "1"                  # 1: nikt nic nie zapisuje, sala tylko ogląda
SANDBOX_TTL_HOURS = int(os.environ.get("SANDBOX_TTL_HOURS", "8"))            # ważność tokenu i czas życia danych sandboxu
SANDBOX_MAX_OWNERS = int(os.environ.get("SANDBOX_MAX_OWNERS", "300"))        # tylu sandboxów z danymi naraz
MAX_AREAS_SANDBOX = int(os.environ.get("MAX_AREAS_SANDBOX", "10"))           # pól na sandbox
MAX_AREAS_OTHER = int(os.environ.get("MAX_AREAS_OTHER", "50"))               # pól na zwykłego rolnika demo
MAX_AREA_HA = float(os.environ.get("MAX_AREA_HA", "150"))                    # maks. powierzchnia jednego pola
MAX_PARALLEL_REFRESH = int(os.environ.get("MAX_PARALLEL_REFRESH", "4"))      # równoległe przeliczenia pól
# Nowych sandboxów na minutę z jednego adresu IP. Wysoko, bo cała sala na jednym Wi-Fi wychodzi zwykle przez jeden publiczny adres (NAT).
SANDBOX_RATE_PER_MIN = int(os.environ.get("SANDBOX_RATE_PER_MIN", "150"))
# The example farms a sandbox copies (comma-separated owner_id): ten reviewed farms with a good mix of risk classes on the demo day.
# Empty: every example farmer. Ids missing from the database are skipped; if none is there, every example farmer is used.
SANDBOX_TEMPLATES = [s.strip() for s in os.environ.get(
    "SANDBOX_TEMPLATES",
    "farmer-024,farmer-055,farmer-042,farmer-020,farmer-015,farmer-016,farmer-099,farmer-086,farmer-051,farmer-093",
).split(",") if s.strip()]

# Konta przykładowych rolników (farmer-001...) mają przewidywalne hasła i służą za wzorce kopiowane do sandboxów: tylko do odczytu.
ALLOW_EXAMPLE_FARM_WRITES = os.environ.get("ALLOW_EXAMPLE_FARM_WRITES", "0") == "1"

# Dodawanie użytkowników (POST /register): sam login i hasło, makieta bez prawdziwej autentykacji
ALLOW_REGISTRATION = os.environ.get("ALLOW_REGISTRATION", "1") == "1"
MAX_ACCOUNTS = int(os.environ.get("MAX_ACCOUNTS", "500"))                    # tylu kont w tabeli app.user_account najwyżej

# Dozwolone originy CORS
CORS_ORIGINS = ["*"]
