# 🤖 AI Agent Instructions: Backend Module (`backend/`)

> Before editing files in this folder, read the parent [`/AGENTS.md`](../AGENTS.md) and [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Module Scope and Role (`Scope`)
The `backend/` folder is the computational and communication core of the system (FastAPI). It is responsible for:
1. Exposing asynchronous REST API endpoints under the `/api/v1` prefix.
2. Fetching raw spatial and environmental data through connector modules (`app/ingestion/`).
3. Performing geometric and analytical computations on demand (`app/domain/`).
4. Providing full interactive Swagger UI documentation at `/docs`.

---

## 📂 Directory Structure
```text
backend/
├── app/
│   ├── main.py                 # FastAPI initialization, CORS middleware, routers
│   ├── core/
│   │   └── config.py           # Environment variables, fixed API addresses
│   ├── ingestion/              # DATA CONNECTORS (ULDK GUGiK, IMGW, etc.)
│   │   ├── uldk_connector.py   # ULDK GUGiK API client
│   │   └── imgw_connector.py   # IMGW-PIB data client
│   ├── domain/                 # ANALYTICAL AND COMPUTATIONAL FUNCTIONS
│   │   └── geometry_metrics.py # Bounding box, area and metrics calculations
│   └── api/v1/
│       ├── router.py           # Router registration under /api/v1
│       └── endpoints/          # Endpoint files (cadastre.py, analysis.py)
├── requirements.txt            # Minimal dependencies (FastAPI, uvicorn, pydantic)
└── run_backend.py              # One-click server start script
```

---

## 🛑 Backend-Specific Rules (`Hard Rules`)

1. **Dependencies under human control:**
   * Do not install additional libraries (`requests`, `httpx`, `aiohttp`, `geopandas`, `shapely`) without an explicit human instruction in the given task.
   * Use libraries already declared in `requirements.txt` or tell the human that a new library needs to be added.
2. **Consistency with Pydantic models:**
   * All endpoints in `api/v1/endpoints/` **must** use models from `shared/schemas/geo_models.py` as `response_model`.
   * Do not create local, duplicated Pydantic models in the backend: the schemas are shared with the QGIS plugin and the frontend.
3. **Error handling:**
   * Every request to external services (ULDK, IMGW) must be wrapped in a `try-except` block that handles timeouts (`timeout=5`) and returns a clear HTTP status (`HTTPException`).
4. **Code cleanliness:**
   * Keep the FastAPI endpoint functions asynchronous (`async def`).
   * Do not put any business logic in `app/domain/` that the human did not ask for.
