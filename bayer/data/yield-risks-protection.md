### Crop Yield Risks and Protection

**Source:**

Official Polish **metodyki integrowanej ochrony** (integrated crop protection methodologies) for advisors and producers — crop-specific guides covering diseases, pests, weeds, and agronomic risk factors. The Excel summary (`zboza_ryzyka.xlsx`) is a condensed extract of key risk conditions (temperature, humidity, and other predisposing factors) gathered from those files.

**Description:**

Reference briefings to help frame grower decisions — spray, treat, harvest, or wait. This is **agronomic context**, not a spatial layer: use it alongside weather, soil, and crop maps when reasoning about yield risk and protection timing.

The package includes:

- **PDFs** — full guidance documents (advisor and producer editions where available) for major field crops grown in Poland
- **Excel summary** — curated risk tables by crop (pathogens, pests, favourable weather / soil conditions, and additional risk notes)


**Coverage (crops)**

| Material | Crops / documents |
|----------|-------------------|
| PDFs (metodyki) | Wheat, triticale, rye, barley, oat, maize, sugar beet, potato, sunflower; plus a GIORiN cereals methodological guide |
| Excel summary | Sugar beet, maize, wheat, sunflower, potato (one sheet per crop) |

**File format**

- PDF (`.pdf`) — guidance documents and producer guides
- Excel (`.xlsx`) — condensed risk / protection summary

**Directory layout**

```text
metodyki/
├── zboza_ryzyka.xlsx
├── Metodyka integrowanej ochrony slonecznika dla doradcow (2020).pdf
├── Metodyka integrowanej ochrony ziemniaka dla doradcow.pdf
├── Metodyka_-_OWIES_-_www.pdf
├── Metodyka_integrowanej_ochrony_buraka_cukrowego_i_pastewnego_DLA_DORADCOW.pdf
├── Metodyka_integrowanej_ochrony_jeczmienia_ozimego_i_jarego_DLA_DORADCOW.pdf
├── Metodyka_integrowanej_ochrony_kukurydzy_dla_doradcow_2019.pdf
├── Metodyka_integrowanej_ochrony_pszenzyta_dla_doradcow.pdf
├── PORADNIK_METODYCZNY_-_ZBOZA_GIORiN.pdf
├── metodyka_-_PSZENICA_-_www.pdf
├── jeczmienia_ozimego_i_jarego_DLA_PRODUCENTOW.pdf
├── kukurydzy__DLA_PRODUCENTOW.pdf
├── owsa_DLA_PRODUCENTOW.pdf
├── pszenicy_ozimej_i_jarej__DLA_PRODUCENTOW.pdf
├── pszenzyta_ozimego_i_jarego_DLA_PRODUCENTOW.pdf
└── zyta__DLA_PRODUCENTOW.pdf
```

Metodyki can be found in the `metodyki/` folder in this repo. The Excel summary is also included there.

**Excel summary (`zboza_ryzyka.xlsx`)**

One sheet per crop. Typical content:

- Optimal soil pH / site conditions and agronomic risk notes (rotation, drought, excess moisture, nutrient imbalance, weeds, storage)
- Tables of diseases / pests with favourable **temperature**, **humidity**, and other risk factors
- Extra threat notes (monoculture, residues, dense canopy, pests as disease vectors, etc.)

**How to use in the hackathon**

- Treat PDFs as the authoritative metodyki text; use the Excel file as a quick lookup for risk windows
- Join this knowledge to weather (e.g. temp / humidity / leaf wetness proxies) and crop type when scoring disease or pest pressure
- Cite the 'metodyka' title in your team README / demo materials
