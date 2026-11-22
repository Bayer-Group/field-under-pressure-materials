# 🤝 Contributing Guide (CONTRIBUTING)

Thank you for contributing to the development of **Field Under Pressure — GeoEarth Junction**, which includes the merged PyQGIS FastAPI Bridge starter!
Whether you work alone, in a human team or with the help of AI agents, the following rules for working with the repository, the code standards and the commit conventions apply in this project.

---

## 🧭 Philosophy: Human-First Development

This repository follows the iron rule of **Human-First**:
* **The human is the Architect and Decision-Maker.** All decisions about architecture, data structures, technology choices and business logic are made by the human.
* **AI is an Execution Tool.** AI assistants (Copilot, Claude, Gemini, ChatGPT, etc.) act as precise executors of instructions: they never make decisions for the human, do not change the architecture and do not add libraries without an explicit instruction.

Detailed guidelines for artificial intelligence agents are in the [`AGENTS.md`](AGENTS.md) files in the individual directories.

---

## 🎯 Work Model: Issue-Driven Development (Agile Division of Responsibilities)

To keep a clear division of responsibilities, avoid code conflicts and not slow the work down with needless bureaucracy:

1. **Every task starts with a GitHub Issue:**
   * Before you start writing code or assign a task to an AI agent, create a short issue in the **Issues** tab.
   * Choose the **🚀 New Task (Task)** template or write a concise issue.
2. **A light, non-blocking Issue format:**
   Three concrete points are enough:
   * **Goal (1-2 sentences):** What we are doing and why (e.g. *"Add an endpoint that fetches a parcel outline as GeoJSON from ULDK"*).
   * **Module and Owner:** Who takes the task (`backend`, `qgis_plugin`, `web`, `docs`).
   * **Completion checklist (Definition of Done):** 2-3 points verifying readiness (e.g. `- [ ] endpoint returns 200 OK`, `- [ ] unit test passes`).
3. **A smooth flow (Issue $\rightarrow$ Branch $\rightarrow$ Commit):**
   * We create a branch linked to the task: e.g. `feat/12-uldk-geojson` (where 12 is the issue number).
   * Closing commit: `feat(backend): add uldk geojson endpoint (closes #12)`.
   * This way the whole team sees right away who is working on what, without chaos and duplicated work.

---

## 🌿 Git Work Model (GitHub Flow)

We work on a simple, agile **GitHub Flow** model:
1. The team branch in this repository is `team/geoearth-junction`. Do not assume that the merged starter is already verified as a finished application.
2. Every new feature or fix is created on a dedicated branch starting from the team branch.
3. Branch naming:
   * `feat/<feature-name>` – new features (e.g. `feat/uldk-polygon-loader`)
   * `fix/<bug-description>` – bug fixes (e.g. `fix/crs-transformation-epsg2180`)
   * `docs/<topic>` – documentation changes (e.g. `docs/update-datasets-guide`)
   * `refactor/<scope>` – restructuring existing code without changing behaviour
4. When the work is finished we open a Pull Request or, after human verification, merge into the team branch.

---

## 📝 Commit Convention (Conventional Commits)

All commits in the repository **must** be formatted according to the [Conventional Commits v1.0.0](https://www.conventionalcommits.org/) specification:

```text
<type>(<optional-scope>): <concise description in the imperative mood>

[optional body explaining the motivation and context of the change]
```

### Allowed types:
* **`feat`** – adding a new feature (e.g. `feat(backend): add endpoint for parcel bounding box`)
* **`fix`** – fixing a bug (e.g. `fix(qgis): resolve task crash on empty polygon geometry`)
* **`docs`** – documentation-only changes (e.g. `docs: add contributing guide and agent rules`)
* **`refactor`** – code refactoring (e.g. `refactor(shared): simplify geo response schema`)
* **`perf`** – performance optimization (e.g. `perf(backend): cache spatial index lookups`)
* **`test`** – adding or modifying unit tests
* **`chore`** – housekeeping, repository configuration, helper scripts (e.g. `chore: update gitignore`)

### Examples of valid messages:
* `feat(ingestion): add retry logic to uldk connector`
* `fix(plugin): prevent GUI freeze by offloading network request to QgsTask`
* `docs(datasets): register new LiDAR WCS endpoint from GUGiK`
* `refactor(backend): decouple router configuration from app instance`

---

## 🌐 Language

Everything in the repository is written in **English**: documentation, code comments, docstrings, issues, commit messages
and pull requests (see [`AGENTS.md`](AGENTS.md)). Names of Polish institutions, registers, places and legal terms stay in
their original form.

---

## 💻 Code Quality Standards

### 1. Python (Backend & Shared)
* Code compliant with **PEP 8** (readable names, 4-space indentation, clear modules).
* Mandatory **Type Hints** in all function and method signatures.
* We use **Pydantic** models to validate API input and output data.
* **The decision about dependencies belongs to the human:** The AI agent does not install or arbitrarily add new libraries. The choice of tools (e.g. `httpx`, `requests`, `shapely`, `geopandas`) is the human's instruction within a given task.

### 2. PyQGIS (QGIS Plugin)
* **Multithreading:** No I/O operations (network requests, heavy geometry computations) **may** be executed synchronously in the main GUI thread. We must use the `QgsTask` pattern (`AsyncApiTask`).
* **UI:** All visual changes are made in Qt Designer in the `dockwidget.ui` file. The Python code loads the view dynamically through `uic.loadUiType`; we do not compile manually to `_ui.py`.
* **Clean logging:** Instead of `print()` in the system console, messages for the user go to the panel's log window or the `iface.messageBar()` info bar.

### 3. Web Frontend (`web/`)
* Clean, lightweight code (HTML5, CSS, vanilla JS) integrated with MapLibre GL JS.
* We do not introduce heavy frameworks (Next.js, Vue, Angular) without an explicit human decision.

---

## 🔒 Security and Data Hygiene
1. **Never commit API keys, passwords or tokens!** All sensitive data is kept in `.env` files (this file is ignored by `.gitignore`).
2. **Data and licences:** Do not commit large data or private access links. Follow the organizers' terms and document the sources.
