# 🤖 AI Agent Instructions: Shared Module (`shared/`)

> Before editing files in this folder, read the parent [`/AGENTS.md`](../AGENTS.md) and [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Module Scope and Role (`Scope`)
The `shared/` directory is the **Single Source of Truth** for the whole repository. It contains:
1. Common **Pydantic** data models (`schemas/geo_models.py`) used at the same time by:
   * The FastAPI backend (as request validators and `response_model` response schemas),
   * The QGIS plugin (as types returned by the API client),
   * The web frontend (as definitions of JSON structures).
2. Coordinate system constants and spatial definitions (`constants/poland_crs.py`).

---

## 📂 Directory Structure
```text
shared/
├── constants/
│   ├── poland_crs.py       # EPSG codes (2180, 4326, 3857) and the BBOX of Poland
│   └── __init__.py
└── schemas/
    ├── geo_models.py       # Models: GeoFeatureRequest, SpatialMetric, GeoAnalysisResponse
    └── __init__.py
```

---

## 🛑 Shared-Specific Rules (`Hard Rules`)

1. **ABSOLUTE BAN ON ARBITRARY CHANGES TO CONTRACTS:**
   * Modifying fields in `geo_models.py` immediately affects the backend, the QGIS plugin and the frontend.
   * **You must not add, remove or rename any field** in the Pydantic models without an unambiguous human instruction.
2. **Dependency cleanliness:**
   * The `shared/` module must be completely independent of the QGIS environment (`qgis.core`) and of the FastAPI framework.
   * It may use only the Python standard library and `pydantic`.
3. **Backward compatibility:**
   * All new optional fields in Pydantic models must have default values (`= None`, `= {}`, `= []`), so they do not cause deserialization errors in other components.
