# -*- coding: utf-8 -*-
from fastapi import APIRouter
from backend.app.api.v1.endpoints import cadastre, analysis, farm

api_router = APIRouter()
api_router.include_router(farm.router, tags=["Rolnik i analityk (serve)"])
api_router.include_router(cadastre.router, prefix="/cadastre", tags=["Kataster & ULDK"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["Analiza Przestrzenna"])
