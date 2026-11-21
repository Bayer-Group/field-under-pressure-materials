# 🤖 AI Agent Instructions: Documentation Module (`docs/`)

> Before editing files in this folder, read the parent [`/AGENTS.md`](../AGENTS.md) and [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Module Scope and Role (`Scope`)
The `docs/` directory is the central geospatial knowledge base of the project. It contains:
1. A register of open Polish and European spatial data services (WMS, WFS, WCS, STAC API, REST).
2. Catalogues and technical descriptions of national datasets (GUGiK, IMGW, IUNG, GIOŚ, PIG, Copernicus).
3. Technical instructions and integration specifications.

---

## 📂 Directory Structure
```text
docs/
├── polskie_rejestry_publiczne_gis.csv   # Table with sources, formats and URLs (46 services)
└── polskie_rejestry_publiczne_gis.md    # Detailed description divided into categories
```

---

## 🛑 Documentation-Specific Rules (`Hard Rules`)

1. **Two-way consistency rule:**
   * Every change or addition of a new data source **must** be reflected in both files at the same time:
     * In the machine-readable file `polskie_rejestry_publiczne_gis.csv` (delimiter: semicolon `;`),
     * In the human-readable file `polskie_rejestry_publiczne_gis.md` (Markdown table).
2. **Technological neutrality:**
   * Keep the descriptions neutral, general-geographic and engineering in character, as a universal GIS knowledge base.
3. **Truthfulness of links:**
   * Add only verified, official national and EU addresses (domains `.gov.pl`, `.imgw.pl`, `.europa.eu`).
