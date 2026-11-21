# 🤖 Instructions for AI Agents in the Tests Module (`tests/`)

> **FOR EVERY AI AGENT AND CODE ASSISTANT:**  
> Read this file before creating, modifying or suggesting any tests in this repository.

---

## 🛑 TEST WRITING RULES (HUMAN-FIRST TESTING)

This project follows the **absolute Human-First Testing rule**. The human decides on the test architecture, the verification goals and the acceptable success criteria. The AI agent is only an executor of instructions and has no right to arbitrarily expand the test suite.

### 🚫 WHAT THE AI AGENT MUST NOT DO (Zero Tolerance):
1. **NO TESTING OF TRIVIAL AND OBVIOUS THINGS (Test Bloat):**
   * Do not write tests that check whether Python works correctly (e.g. whether `1 + 1 == 2`, whether `list.append()` adds an element, whether a built-in dictionary stores keys).
   * Do not write tests for simple getters/setters, empty constructors or trivial attribute assignments, unless they contain explicit validation logic.
   * Do not generate artificial tests just to "increase code coverage" (code coverage padding).
2. **NO ARBITRARY CREATION OF NEW TEST FILES:**
   * The AI agent **does not create new test files** without an explicit human instruction defining the goal and scope of the test.
   * If you notice a missing scenario, ask the human: *"Do you want me to add a test verifying case X?"*.
3. **NO TESTING DIRECT EXTERNAL DEPENDENCIES (Zero Live Network in tests):**
   * No unit test may make real HTTP requests to external servers (ULDK, IMGW, Open-Meteo, etc.).
   * All integration tests with external services must use mocks (`unittest.mock`), stubs or the offline mode (`test_ingestion_offline.py`).
4. **NO FLAKY (UNSTABLE) TESTS:**
   * Do not use `time.sleep()`, unseeded random values (`random.seed`) or tests that depend on the time zone or the user's location.

---

## 🎯 WHAT THE AI AGENT SHOULD TEST (On the Human's Instruction):

1. **Data Contracts and Pydantic Schemas (`test_schemas.py`):**
   * Whether invalid geographic coordinates or wrong data types are correctly rejected by validation (`ValidationError`).
   * Whether serialization and deserialization to GeoJSON follows the RFC 7946 specification.
2. **Coordinate Transformations and Metric Calculations (`test_crs_and_geometry.py`):**
   * Whether conversions between EPSG:2180 and EPSG:4326/EPSG:3857 return values within the expected tolerances.
   * Whether the function computing area in $m^2$ and hectares handles polygons correctly and raises an error for degenerate geometry.
3. **Error Handling and Resilience (Error Handling & Fallback):**
   * How the code behaves with an empty API response, an HTTP 500 code, a timeout or a corrupted JSON/WKT format.
4. **QGIS Plugin Structure and Environment Isolation (`test_qgis_plugin.py`):**
   * Whether the plugin has a valid `metadata.txt` file, a consistent import structure and does not raise exceptions when the QGIS GUI environment is missing.

---

## 🛠️ TECHNICAL TEST STANDARDS

* **Framework:** The standard `unittest` module from the standard library.
* **Zero new dependencies:** Tests must be runnable in a clean Python environment without installing additional packages (e.g. `pytest`, unless the human explicitly asks for it).
* **Path isolation:** Every test file must dynamically set the project path with `sys.path.insert(0, ...)`.
* **Conditional skipping:** For optional modules (e.g. `fastapi`), tests must use `@unittest.skipIf(not MODULE_AVAILABLE, "reason for skipping")`, so the test suite passes in every environment.
