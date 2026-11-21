# 🤖 AI Agent Instructions: Web Module (`web/`)

> Before editing files in this folder, read the parent [`/AGENTS.md`](../AGENTS.md) and [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Module Scope and Role (`Scope`)
The `web/` folder is responsible for a lightweight map viewer in the web browser. It is used for:
1. Visualizing spatial data (GeoJSON vector layers and tile basemaps) with the **MapLibre GL JS** library.
2. Demonstrating queries to the FastAPI backend endpoints (`/api/v1/analysis/...`) directly from the browser.
3. Checking that the CORS headers are configured correctly on the server side.

---

## 📂 Directory Structure
```text
web/
└── index.html              # Single-file map viewer (HTML5 + CSS + vanilla JS + MapLibre GL JS)
```

---

## 🛑 Web-Specific Rules (`Hard Rules`)

1. **No heavy frameworks:**
   * Do not install or configure Next.js, React, Vue, Angular, Vite or Webpack projects without an explicit human instruction.
   * The module must stay ultra-light: opened directly from disk as an `index.html` file or served as a static file.
2. **Map visualization standards:**
   * Use the open-source **MapLibre GL JS** library (not Mapbox GL, which requires paid access tokens).
   * Use the free OpenStreetMap tiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`) as the default tile basemap.
3. **API communication:**
   * Make network calls with the standard browser `fetch()` function.
   * Always handle network errors (`try-catch`), informing the user clearly about the status of the connection to the local server.

## Farmer interface design

For every frontend design and change, follow [Frontend design principles](DESIGN.md) together with [Emil Kowalski's Apple Design skill](https://www.ui-skills.com/skills/emilkowalski/apple-design). Apply the principles to the specific interaction, and preserve accessibility and reduced-motion preferences.
