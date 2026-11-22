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
├── _config.yml                          # GitHub Pages (Jekyll) site configuration
├── index.md                             # Home page of the documentation site
├── getting-started.md, architecture.md, risk-models.md, api.md, deployment.md, data-sources.md, team.md
├── PROJECT.md                           # Product requirements and open decisions
├── *_CONTRACT.md, *_contract.md         # Agreed contracts (farmer input, geometry validation, curated layer, serve read)
├── LIVE_SANDBOX_INTEGRATION.md, MOCK_API_GUIDE.md, DATA_PIPELINE_NOTES.md
├── polskie_rejestry_publiczne_gis.csv   # Table with sources, formats and URLs (46 services)
└── polskie_rejestry_publiczne_gis.md    # Detailed description divided into categories
```

The folder is published as the GitHub Pages site. Avoid Liquid syntax (`{{ }}`, `{% %}`) in Markdown files here: Jekyll would
try to evaluate it. Link to code outside `docs/` with full GitHub URLs, because relative links leave the published site.

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
