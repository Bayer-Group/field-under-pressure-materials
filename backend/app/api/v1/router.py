# -*- coding: utf-8 -*-
from fastapi import APIRouter
from backend.app.api.v1.endpoints import cadastre, analysis, farm, farm_write, parcels, fields, places, register

api_router = APIRouter()
api_router.include_router(farm.router, tags=["Rolnik i analityk (serve)"])
api_router.include_router(farm_write.router, tags=["Zapis rolnika i sandbox demo"])
api_router.include_router(register.router, tags=["Dodanie użytkownika (login i hasło)"])
api_router.include_router(parcels.router, tags=["Działki (GUGiK ULDK)"])
api_router.include_router(places.router, tags=["Wyszukiwarka miejscowości"])
api_router.include_router(fields.router, tags=["Pola rolnika: odczyt, walidacja geometrii, zapis grupowy"])
api_router.include_router(cadastre.router, prefix="/cadastre", tags=["Kataster & ULDK"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["Analiza Przestrzenna"])
