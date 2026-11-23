# 🤖 Instructions for AI Agents (AGENTS.md) — Human-First Development

> **FOR EVERY AI AGENT AND CODE ASSISTANT (Copilot, Claude, Gemini, Cursor, ChatGPT, etc.):**  
> Read this file in full before making any modification to the code in this repository.

---

## 🛑 MANIFESTO: HUMAN-FIRST DEVELOPMENT

In this project, human decisions take absolute precedence. You are an **execution tool ("a workhorse")**, not the architect of the project. The human defines the goals, requirements and architecture. Your role is to carry out the given scope of work precisely, without arbitrary innovation.

### 🚫 HARD PROHIBITIONS (Zero Tolerance):
1. **NO ARBITRARY ADDING OF NEW LIBRARIES AND DEPENDENCIES:**
   * You must not install or add to `requirements.txt`, `package.json` or the environment any new libraries (`pip install ...`, `npm install ...`) without explicit prior human consent.
   * Use libraries and tools indicated by the human or already configured in the project.
2. **NO WORK WITHOUT A DEFINED SCOPE (Issue-Driven AI Execution):**
   * Do not do tasks "in advance". Your work must be tied to a specific goal/issue defined by the human.
   * If the human gives you an issue number or content, stick strictly to that issue's acceptance criteria (Definition of Done).
3. **NO MAKING ARCHITECTURAL AND DOMAIN DECISIONS ON YOUR OWN:**
   * You do not decide on changes to the directory structure, design patterns, database technologies or the data contracts in `shared/schemas/`.
   * You do not add on your own initiative business heuristics, decision algorithms or domain assumptions that the human did not explicitly ask for.
3. **NO ARBITRARY REWRITING AND DELETING OF EXISTING CODE:**
   * Use a **minimal diff**: modify only the lines necessary to complete the task.
   * Never delete existing functions, comments, tests or documentation "while you are at it".
4. **NO HALLUCINATING ENDPOINTS AND IMPORTS:**
   * Use only modules that actually exist in the project. Before importing something, verify that the file physically exists on disk.
5. **DUTY TO ASK WHEN IN DOUBT:**
   * If the human's instruction is ambiguous, a specification is missing or you see a contradiction, **stop and ask the human for a decision** instead of guessing.

---

## 🗺️ Module Map and Subordinate AGENTS.md Files

The repository is organized as a modular architecture. Every subdirectory has its own specialized `AGENTS.md` file that defines the scope and working rules for that component:

| Module | Path | Role in the system | Dedicated guidelines |
| :--- | :--- | :--- | :--- |
| **Shared** | [`shared/`](shared/AGENTS.md) | Single Source of Truth: Pydantic schemas, CRS constants | [shared/AGENTS.md](shared/AGENTS.md) |
| **Backend** | [`backend/`](backend/AGENTS.md) | FastAPI server, `/api/v1` routing, open API connectors (ULDK, IMGW) | [backend/AGENTS.md](backend/AGENTS.md) |
| **QGIS Plugin** | [`qgis_plugin/`](qgis_plugin/AGENTS.md) | PyQGIS plugin with a docked panel and `QgsTask` multithreading | [qgis_plugin/AGENTS.md](qgis_plugin/AGENTS.md) |
| **Web** | [`web/`](web/AGENTS.md) | Lightweight MapLibre GL JS map viewer | [web/AGENTS.md](web/AGENTS.md) |
| **Docs** | [`docs/`](docs/AGENTS.md) | Project documentation (GitHub Pages), contracts, public data registries | [docs/AGENTS.md](docs/AGENTS.md) |
| **Docker** | [`docker/`](docker/AGENTS.md) | Auxiliary container configuration (PostGIS, MinIO, TiTiler) | [docker/AGENTS.md](docker/AGENTS.md) |
| **Tests** | [`tests/`](tests/AGENTS.md) | Automated unit tests and Human-First Testing rules | [tests/AGENTS.md](tests/AGENTS.md) |
| **Organizer materials** | [`bayer/`](bayer/README.md) | The organizer's original hackathon materials, kept unchanged (read-only: do not edit) | none |

---

## 🌐 Language: English

All project text is written in **English**: documentation, code comments, docstrings, SQL and shell comments, script
messages, issues, commit messages and pull requests. This also applies to AI agents.

* Names of Polish institutions, registers, places and legal terms stay in their original form.
* Data and user-visible strings that are intentionally Polish (e.g. the Polish public data registers) stay as they are.

---

## 📋 Code Working Standard for the AI Agent

Before you report a task as finished to the human, make sure that:
1. **The code works and does not cause syntax errors (`SyntaxError`) or import errors (`ImportError`).**
2. **The naming conventions and the commit convention described in [`CONTRIBUTING.md`](CONTRIBUTING.md) have not been broken.**
3. **All new functions have type hints and concise docstrings in English.**
4. **All file paths are relative or built with `os.path.join()`, to stay fully independent of the operating system (Windows, macOS, Linux).**

---

## 🧪 Test Writing Rules (Human-First Testing)

This project follows **Human-First Testing**: tests must protect the real quality of the system and not serve to artificially inflate statistics:
1. **The human decides what we test:** The AI agent is strictly forbidden from adding new test files or inventing extensive test suites without the human's approval.
2. **No testing the obvious (Zero Test Bloat):** We do not write tests that check whether Python works correctly, whether a simple attribute assignment worked, or tests for getters without business logic.
3. **Focus on real risk:** Tests should check data contracts (`Pydantic`), resilience to external API failures (mocks/offline), coordinate system conversions (`EPSG:2180`) and the integrity of the QGIS plugin.
4. **More details:** See the dedicated guide in [`tests/AGENTS.md`](tests/AGENTS.md).
