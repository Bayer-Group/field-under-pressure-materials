#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skrypt do szybkiego uruchomienia serwera FastAPI lokalnie.
Użycie: python backend/run_backend.py
"""

import sys
import os

# Dodaj główny katalog projektu do PYTHONPATH
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print(" Uruchamianie Backend API: http://127.0.0.1:8000")
    print(" Dokumentacja interaktywna Swagger UI: http://127.0.0.1:8000/docs")
    print("=" * 60)
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
