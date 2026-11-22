# -*- coding: utf-8 -*-
"""
Punkt wejścia aplikacji FastAPI.
Czysty most komunikacyjny między FastAPI a środowiskiem QGIS.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import PROJECT_NAME, API_V1_STR, CORS_ORIGINS
from backend.app.api.v1.router import api_router

app = FastAPI(
    title=PROJECT_NAME,
    openapi_url=f"{API_V1_STR}/openapi.json",
    docs_url="/docs",
    description="Asynchroniczny backend analityki przestrzennej dla wtyczki QGIS i podglądu Web"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,   # the API uses the Authorization header, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=API_V1_STR)

@app.get("/health", tags=["Status"])
async def health_check():
    return {
        "status": "online",
        "service": PROJECT_NAME,
        "docs_url": "/docs"
    }
