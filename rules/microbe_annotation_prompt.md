# Microbe role annotation: instructions for annotator agents

You annotate soil microbial **genera** with their roles for crops, using a small fixed ontology, and write a short
plain-language description of each genus. Your rows become the knowledge base behind the "Roles" view of the
Soil microbes tab and the "who may carry it" lists of the Soil functions tab. Farmers and agronomists read the
result, so a wrong "pathogen" or a wrong "nitrogen fixer" is worse than an honest "unknown".

Work from your own knowledge only. Do **not** read FUNGuild, FungalTraits or any other file in the repo except your
input chunk and `rules/microbe_ontology.csv` (part of the fungal output is used for a blind agreement test against
those databases). Do not browse the web.

## 1. Context: where the soil comes from

- NEON farm sites in the US Great Plains: **STER** (Sterling, north-east Colorado: dryland winter wheat, corn,
  fallow, some sunflower/millet; semi-arid, alkaline, low organic matter) and **KONA** (Konza area, north-east
  Kansas: cropland next to tallgrass prairie; corn, soybean, sorghum, wheat, alfalfa).
- Bacteria and archaea come from shotgun metagenomes classified with **Kraken2** (NCBI taxonomy names; short reads,
  so a small share of reads lands in wrong, often well-studied genera). Fungi come from NEON **ITS amplicons**
  (UNITE names).
- Genus is the finest level we have. Species appear only as named examples in your rows, never as data.

## 2. Input

You are given a chunk name (e.g. `c07`) and either a ready file `data/annotation_chunks/<chunk>_input.csv` or a
row range of `data/processed/microbe_taxa.csv`. In the second case first write the rows to
`data/annotation_chunks/<chunk>_input.csv` (same header, same order) with pandas, so the self-check (section 8)
has a file to compare against. Columns:

| column | meaning |
|---|---|
| `domain` | `Bacteria`, `Archaea` or `Fungi` |
| `genus` | genus name exactly as in the data (keep it byte-for-byte in your output, `Candidatus` prefix included) |
| `phylum`, `class` | lineage to disambiguate homonyms (`class` is empty for bacteria/archaea) |
| `reads`, `n_samples`, `abundance_rank` | how common the genus is in these soils (rank 1 = most reads in its group) |

Annotate **every** input row. The pair (`domain`, `genus`) is the key.

## 3. Output: two CSV files per chunk

Create `data/annotation_chunks/` if needed. Write with Python's `csv.writer` (default `QUOTE_MINIMAL`, UTF-8,
`\n` line ends): never build CSV lines by string concatenation, because notes and descriptions contain commas.

### 3a. `data/annotation_chunks/<chunk>_roles.csv`

Header, exactly: `domain,genus,term_id,confidence,evidence,source,species_examples,note`

| column | allowed values / format |
|---|---|
| `domain`, `genus` | copied from the input row |
| `term_id` | a `term_id` from `rules/microbe_ontology.csv` (section 4); never a root other than `unknown` |
| `confidence` | `high` \| `medium` \| `low` (section 5) |
| `evidence` | `well_known_genus` (role holds for most species of the genus) \| `some_species` (only some species; name them) \| `inferred` (indirect: from related genera, or from scattered isolate reports you cannot pin to a named species). Never `curated_db` (reserved for the database mapping). |
| `source` | `llm:<your model id>`, the exact model id you run as (e.g. `llm:claude-sonnet-4-6`); the same value on every row you write |
| `species_examples` | full binomials separated by `; ` (e.g. `Pseudomonas syringae; Pseudomonas savastanoi`), at most 3; required for `some_species`, optional otherwise, empty for `unknown` / `doubtful_assignment`. Only species you are sure exist **and** have the role. |
| `note` | optional, at most 120 characters: the crop/disease or compound that justifies the row (e.g. `wheat head blight; corn ear rot`) |

Rules:
- Every genus gets **at least one** row. When nothing crop-relevant is known, write exactly one row
  `term_id=unknown, confidence=low, evidence=inferred`.
- **At most 4 rows per genus.** Pick the roles that matter most in cropland soil.
- **Prefer the most specific term** (a leaf). Use a parent (`nutrient_supply`, `plant_growth_promotion`,
  `biocontrol`, `plant_pathogen`) only when no child fits. Never give a genus both a term and one of its ancestors.
- `unknown` and `doubtful_assignment` stand **alone**: no other rows for that genus.
- No duplicate (`domain`, `genus`, `term_id`).

### 3b. `data/annotation_chunks/<chunk>_desc.csv`

Header, exactly: `domain,genus,description`

One row per input genus. `description`: plain English for a farmer or agronomist, **at most 2 sentences and at most
220 characters**. Say what the genus is (kind of organism, where it lives) and why it matters, or does not, in
cropland soil. Rules:
- No jargon a farmer would not know without a gloss (say "turn ammonium into nitrate", not "ammonia monooxygenase").
- No invented facts, numbers or species; name a species only if it is well known (e.g. *Fusarium graminearum*).
- Must agree with the roles file (a genus annotated `unknown` must not be described as a pathogen).
- Little-known genera get an honest line, e.g. "Little-studied soil bacteria of the Acidobacteria, known mostly
  from DNA. No known role for crops."
- Doubtful names say so, e.g. "...Not expected in ordinary cropland soil, so these reads are probably misnamed DNA."
- Do not start with the genus name ("Fusarium is..."); the UI already shows it. No markdown, no line breaks.

## 4. The ontology (authoritative copy: `rules/microbe_ontology.csv`)

Read the CSV before starting; if it differs from this table, the CSV wins. Indentation = parent/child.

| term_id | label | use when |
|---|---|---|
| **useful** | Useful | root, never annotate directly |
| &nbsp;&nbsp;nutrient_supply | Nutrient suppliers | other nutrient supply with good evidence (potassium release, iron siderophores feeding plants); else use a child |
| &nbsp;&nbsp;&nbsp;&nbsp;n_fixation | Nitrogen fixers | free-living or root-associative N2 fixers (Azotobacter, Azospirillum, Paenibacillus polymyxa, many Cyanobacteria) |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;legume_symbiont | Legume nodule partners | nodulating rhizobia (Bradyrhizobium, Rhizobium, Sinorhizobium/Ensifer, Mesorhizobium); implies n_fixation, do not add both |
| &nbsp;&nbsp;&nbsp;&nbsp;p_mobilisation | Phosphorus solubilisers | genera repeatedly shown to free mineral or organic P in soil (not one in-vitro plate test) |
| &nbsp;&nbsp;&nbsp;&nbsp;mycorrhizal_partner | Arbuscular mycorrhizal fungi | Glomeromycota (Glomus, Rhizophagus, Funneliformis, Claroideoglomus, Paraglomus...). Do not add p_mobilisation for them |
| &nbsp;&nbsp;plant_growth_promotion | Growth promoters | documented growth promotion or induced resistance not covered by a child |
| &nbsp;&nbsp;&nbsp;&nbsp;acdS | Root stress relievers | genera known for ACC deaminase (e.g. Pseudomonas, Variovorax, Burkholderia/Paraburkholderia) |
| &nbsp;&nbsp;&nbsp;&nbsp;phytohormone | Plant hormone makers | auxin/gibberellin/cytokinin production with shown plant effect (Azospirillum auxin, Gibberella/Fusarium fujikuroi gibberellin is a pathogen, not this) |
| &nbsp;&nbsp;biocontrol | Pest and disease suppressors | suppression by competition etc. not covered by a child |
| &nbsp;&nbsp;&nbsp;&nbsp;antibiotic_producer | Antimicrobial producers | antifungal/antibacterial compounds that matter against root pathogens (Streptomyces, Pseudomonas DAPG/phenazine/HCN, Bacillus lipopeptides, Lysobacter) |
| &nbsp;&nbsp;&nbsp;&nbsp;mycoparasite | Parasites of other fungi | fungi or bacteria that attack fungi (Trichoderma, Clonostachys, Coniothyrium, Ampelomyces) |
| &nbsp;&nbsp;&nbsp;&nbsp;chitinase | Chitin digesters | genera *notable* for chitinolysis used against fungi (Chitinophaga, Lysobacter, Serratia). Not every actinobacterium |
| &nbsp;&nbsp;&nbsp;&nbsp;pest_antagonist | Insect and nematode enemies | entomopathogens and nematode antagonists (Bacillus thuringiensis, Beauveria, Metarhizium, Arthrobotrys, Purpureocillium, Pasteuria) |
| **harmful** | Potentially harmful | root, never annotate directly |
| &nbsp;&nbsp;plant_pathogen | Genera with plant pathogens | pathogenic species whose disease type is unclear or mixed; else use a child |
| &nbsp;&nbsp;&nbsp;&nbsp;root_soilborne_pathogen | Root and soilborne pathogens | root, crown, tuber, seedling rots, damping-off, scab, take-all, vascular wilts entering via roots (Fusarium oxysporum, Rhizoctonia, Gaeumannomyces, Macrophomina, Verticillium, Streptomyces scabies) |
| &nbsp;&nbsp;&nbsp;&nbsp;foliar_pathogen | Leaf, stem, head and seed pathogens | leaf spots, blights, rusts, head blight, stalk/ear rot; soil/residue is a reservoir (Pseudomonas syringae, Xanthomonas, Clavibacter nebraskensis, Pyrenophora, Bipolaris, Alternaria, Colletotrichum graminicola) |
| &nbsp;&nbsp;mycotoxin_producer | Mycotoxin producers | species that leave toxins in grain/forage (Fusarium DON/fumonisin/zearalenone, Aspergillus aflatoxin, Penicillium ochratoxin, Alternaria) |
| &nbsp;&nbsp;animal_human_pathogen | Human or animal pathogens | established human/livestock pathogens, incl. opportunists from soil, dust or manure (Bacillus anthracis, Clostridium, Nocardia, Mycobacterium bovis, Burkholderia cepacia complex, Aspergillus fumigatus, Coccidioides). Not "isolated once from a patient" |
| **context** | Nitrogen cyclers | root, never annotate directly |
| &nbsp;&nbsp;nitrification | Nitrifiers | ammonia oxidisers (Nitrosospira, Nitrosomonas, Nitrososphaera, Candidatus Nitrosocosmicus), nitrite oxidisers (Nitrobacter, Nitrospira incl. comammox) |
| &nbsp;&nbsp;denitrification | Denitrifiers | genera where denitrification (nitrate/nitrite to gas) is a characteristic trait (Pseudomonas stutzeri group, Paracoccus, Thauera, Rhodanobacter, Bradyrhizobium diazoefficiens). Not every nitrate reducer |
| &nbsp;&nbsp;nosZ | N2O reducers | genera known to reduce N2O to N2, incl. non-denitrifying "clade II" N2O reducers (Anaeromyxobacter, Gemmatimonas, Dechloromonas) |
| &nbsp;&nbsp;dnra | Nitrate-to-ammonium (DNRA) | genera known for dissimilatory nitrate reduction to ammonium (Geobacter, Anaeromyxobacter, Shewanella, some Bacillus) |
| **background** | Neutral / background | root, never annotate directly |
| &nbsp;&nbsp;decomposer | Decomposers | fungal saprotrophs; bacteria notable for degrading plant polymers (cellulose, lignin, chitin): Cellulomonas, Cytophaga, Sorangium, Streptomyces |
| &nbsp;&nbsp;endophyte | Endophytes | live inside plants with unclear effect (dark septate endophytes, many Sordariomycetes); if a clear benefit or disease is known, use that instead |
| &nbsp;&nbsp;tree_mycorrhizal | Tree mycorrhizal fungi | ecto-, ericoid, orchid mycorrhizal fungi (Inocybe, Tomentella, Geopora, Tuber, Cenococcum); likely from field edges or past land use |
| &nbsp;&nbsp;common_soil_microbe | Common soil microbes | known, often abundant soil genera with no crop-specific role (Conexibacter, Gaiella, Solirubrobacter, soil yeasts like Solicoccozyma). Not for genera we know nothing about |
| **unknown** | Role unknown | too little known: one row `unknown, low, inferred` |
| &nbsp;&nbsp;doubtful_assignment | Probably misnamed reads | genus cannot plausibly live in aerobic, temperate, non-saline cropland soil (obligate insect/animal endosymbionts, hyperthermophiles, extreme halophiles, strictly marine taxa): the reads are likely misassigned or incidental |

Roles overlap on purpose: a genus can be a nitrogen fixer and include pathogens. The app turns the rows of a genus
into one summary class (Useful / Potentially harmful / Mixed / Nitrogen cyclers / Neutral / Role unknown), counting
only `high` and `medium` rows. So a `medium` harmful row on a big genus turns it "Mixed" or "Potentially harmful"
for every user: be sure before you write it.

## 5. Confidence calibration

| confidence | meaning | typical cases |
|---|---|---|
| `high` | textbook knowledge; you would be surprised to be wrong; a soil microbiologist would agree without checking | Bradyrhizobium legume_symbiont; Nitrososphaera nitrification; Fusarium root_soilborne_pathogen with named species; Rhizophagus mycorrhizal_partner |
| `medium` | documented in several independent studies or in recognised products/diseases, but not universal in the genus, or you know it for named species only | Pseudomonas acdS (P. putida); Bacillus animal_human_pathogen (B. anthracis); Streptomyces root_soilborne_pathogen (S. scabies) |
| `low` | single reports, in-vitro screens only, or inferred from relatives; **not counted** in the app's shares, kept for review | "PGPR" claims from one greenhouse study; Mortierella p_mobilisation |

- **Prefer `unknown` to guessing.** Many soil genera (Acidobacteria, Chloroflexi, Verrucomicrobia, Planctomycetes
  subgroups, most `Candidatus` genera) have no known crop role: write `unknown` rather than a speculative role.
- **Harmful rows need a named species**: `plant_pathogen` subtree, `mycotoxin_producer` and `animal_human_pathogen`
  rows at `medium`/`high` must be `well_known_genus` or `some_species` **with** `species_examples`. Harmful rows that
  are `inferred` are at most `low`.
- **`some_species` + named species when only part of a genus fits.** *Pseudomonas syringae* (leaf pathogen) vs
  *P. fluorescens* / *P. protegens* (root protectors): annotate both roles, each with its own species. Same for
  *Streptomyces scabies* vs antibiotic producers, *Fusarium oxysporum* vs saprotrophic Fusaria, *Burkholderia
  glumae* vs *Paraburkholderia* (environmental, not pathogenic).
- A plant pathogen of any crop counts (field crops, vegetables, forage, fruit), not only the crops of these sites;
  mention the crop or disease in `note`. Pure tree/wood pathogens: `plant_pathogen`, `low`.
- `inferred` is never `high`.
- Do not mark a genus "useful" just because a paper calls an isolate a "plant-growth-promoting bacterium": that
  claim is made for almost every genus. Useful rows at `medium`/`high` need repeated field/greenhouse evidence or
  use in commercial products.

## 6. Special cases

**Archaea.** Thaumarchaeota/Nitrososphaerota ammonia oxidisers (Nitrososphaera, Nitrosopumilus-like soil taxa,
Candidatus Nitrosocosmicus, Candidatus Nitrosotalea) → `nitrification` high. Extreme halophiles (Halobacterium,
Haloferax, Halorubrum, Natrinema, Haloarcula... the Halobacteria) and hyperthermophiles (Thermococcus, Pyrococcus,
Sulfolobus) in these soils are almost always misassigned short reads → `doubtful_assignment` (`medium`; `high` for
hyperthermophiles). Methanogens (Methanosarcina, Methanoculleus, Methanobrevibacter): anaerobic, from wet
microsites or manure → `common_soil_microbe` `low`/`medium` with a note ("methane producer; manure or waterlogged
spots"), or `doubtful_assignment` for strictly gut or marine ones.

**Kraken2 / NCBI names.**
- `Candidatus X` genera: keep the full name. Many are obligate endosymbionts of insects or protists (Candidatus
  Blochmannia, Carsonella, Hamiltonella, Cardinium...) → `doubtful_assignment`; reads may come from insects in the
  soil core or be misassigned. Environmental `Candidatus` genera known from soil (Candidatus Koribacter, Candidatus
  Solibacter, Candidatus Udaeobacter) → `common_soil_microbe` or `unknown`. Candidatus Kuenenia and other anammox
  genera → `unknown`/`doubtful_assignment` (wastewater/anoxic).
- Recently split genera: annotate from what is known of the species now in the genus, using `inferred` where you
  rely on the old genus: Mycolicibacterium (environmental mycobacteria, from Mycobacterium), Paraburkholderia and
  Caballeronia (environmental, not pathogenic, from Burkholderia), Pseudarthrobacter/Paenarthrobacter (from
  Arthrobacter), Priestia/Peribacillus/Neobacillus (from Bacillus), Ensifer = Sinorhizobium.
- Human/animal-associated genera that show up from manure or dust (Corynebacterium, Staphylococcus, Escherichia,
  Bacteroides, Clostridium): annotate the real role (`animal_human_pathogen` with named species where justified);
  add a note "manure or animal source" if relevant.
- Kraken2 places a share of reads into famous genera (Mycobacterium, Burkholderia, Escherichia, Xanthomonas) by
  error. This affects shares, not the genus's role: annotate the genus for what it is.

**Fungi (ITS / UNITE names).**
- Many names are teleomorph/anamorph pairs or recent splits: Gibberella = Fusarium; Linnemannia, Podila,
  Entomortierella were split from Mortierella; Solicoccozyma, Naganishia, Vishniacozyma are soil yeasts formerly in
  Cryptococcus. Annotate from the species now in the genus.
- Saprotrophic fungi → `decomposer`. Endophytes with no known effect → `endophyte`. Yeasts → `decomposer` or
  `common_soil_microbe`.
- Common cropland pathogens to recognise: wheat take-all (Gaeumannomyces), common root rot and spot blotch (Bipolaris
  sorokiniana / Cochliobolus), tan spot (Pyrenophora), crown rot and head blight (Fusarium), eyespot
  (Oculimacula), Rhizoctonia, corn anthracnose (Colletotrichum graminicola), Diplodia (Stenocarpella), grey leaf
  spot (Cercospora), charcoal rot (Macrophomina), sunflower and soybean Sclerotinia, Verticillium wilt, Phoma /
  Leptosphaeria. Oomycetes (Pythium, Phytophthora) are not fungi and should not appear; if they do, annotate them
  normally (`root_soilborne_pathogen`).

## 7. Worked examples

These are calibration examples, written as they would appear in the files (`llm:<model id>` stands for your id).

`<chunk>_roles.csv`

```csv
domain,genus,term_id,confidence,evidence,source,species_examples,note
Bacteria,Bradyrhizobium,legume_symbiont,high,well_known_genus,llm:<model id>,Bradyrhizobium japonicum; Bradyrhizobium diazoefficiens,soybean nodules; many soil strains are free-living
Bacteria,Bradyrhizobium,denitrification,medium,some_species,llm:<model id>,Bradyrhizobium diazoefficiens,full denitrification pathway incl. nosZ
Bacteria,Bradyrhizobium,nosZ,medium,some_species,llm:<model id>,Bradyrhizobium diazoefficiens,
Bacteria,Streptomyces,antibiotic_producer,high,well_known_genus,llm:<model id>,Streptomyces griseus; Streptomyces lydicus,source of most known antibiotics; biocontrol products
Bacteria,Streptomyces,decomposer,high,well_known_genus,llm:<model id>,,"degrades cellulose, chitin and residues"
Bacteria,Streptomyces,root_soilborne_pathogen,medium,some_species,llm:<model id>,Streptomyces scabies; Streptomyces acidiscabies,common scab of potato and root crops
Bacteria,Pseudomonas,antibiotic_producer,high,some_species,llm:<model id>,Pseudomonas protegens; Pseudomonas fluorescens,"DAPG, phenazines, HCN; take-all decline in wheat"
Bacteria,Pseudomonas,acdS,medium,some_species,llm:<model id>,Pseudomonas putida,
Bacteria,Pseudomonas,foliar_pathogen,medium,some_species,llm:<model id>,Pseudomonas syringae,bacterial leaf spots and blights; ice-nucleation frost damage
Bacteria,Pseudomonas,denitrification,medium,some_species,llm:<model id>,Pseudomonas stutzeri; Pseudomonas aeruginosa,
Bacteria,Bacillus,antibiotic_producer,high,some_species,llm:<model id>,Bacillus subtilis; Bacillus velezensis,lipopeptides; sold as seed treatments
Bacteria,Bacillus,pest_antagonist,high,some_species,llm:<model id>,Bacillus thuringiensis,Bt insecticidal toxins
Bacteria,Bacillus,animal_human_pathogen,medium,some_species,llm:<model id>,Bacillus anthracis; Bacillus cereus,anthrax spores persist in some Great Plains soils
Archaea,Nitrososphaera,nitrification,high,well_known_genus,llm:<model id>,Nitrososphaera viennensis,ammonia-oxidising archaea
Archaea,Halobacterium,doubtful_assignment,medium,well_known_genus,llm:<model id>,,extreme halophile; likely misassigned short reads
Bacteria,Gemmatirosa,unknown,low,inferred,llm:<model id>,,
Fungi,Fusarium,root_soilborne_pathogen,high,some_species,llm:<model id>,Fusarium oxysporum; Fusarium pseudograminearum; Fusarium solani,"wilts, crown and root rots"
Fungi,Fusarium,foliar_pathogen,high,some_species,llm:<model id>,Fusarium graminearum; Fusarium verticillioides,wheat head blight; corn stalk and ear rot
Fungi,Fusarium,mycotoxin_producer,high,some_species,llm:<model id>,Fusarium graminearum; Fusarium verticillioides,"deoxynivalenol, zearalenone, fumonisins"
Fungi,Fusarium,decomposer,medium,well_known_genus,llm:<model id>,,residue saprotrophs
Fungi,Trichoderma,mycoparasite,high,well_known_genus,llm:<model id>,Trichoderma harzianum; Trichoderma asperellum,biocontrol products
Fungi,Trichoderma,decomposer,high,well_known_genus,llm:<model id>,,
Fungi,Trichoderma,plant_growth_promotion,medium,some_species,llm:<model id>,Trichoderma harzianum,root growth and induced resistance
Fungi,Rhizophagus,mycorrhizal_partner,high,well_known_genus,llm:<model id>,Rhizophagus irregularis,most used AMF inoculant
Fungi,Mortierella,decomposer,high,well_known_genus,llm:<model id>,,sugar fungi on fresh residues
Fungi,Mortierella,p_mobilisation,low,inferred,llm:<model id>,,phosphate solubilisation reported for some soil isolates
```

`<chunk>_desc.csv`

```csv
domain,genus,description
Bacteria,Bradyrhizobium,Nitrogen-fixing bacteria that form root nodules on soybean and also live free in soil. Among the most common soil bacteria; a natural nitrogen source for legumes.
Bacteria,Streptomyces,Thread-forming soil bacteria that break down residues and make many antibiotics; they give soil its earthy smell. A few species cause potato scab.
Bacteria,Pseudomonas,"Diverse, fast-growing root bacteria. Some protect roots from disease such as take-all and ease plant stress; a few, like P. syringae, cause leaf spots."
Bacteria,Bacillus,"Hardy spore-forming soil bacteria; some are sold as biological seed treatments or as the Bt insecticide. A few, such as B. anthracis, harm animals or people."
Archaea,Nitrososphaera,"Archaea that turn ammonium into nitrite, the first step of nitrification. Common in farmed soil; part of how fertiliser nitrogen becomes nitrate that can leach."
Archaea,Halobacterium,"Salt-loving archaea of brines and salt lakes. Not expected in ordinary cropland soil, so these reads are probably misnamed DNA; no role for crops."
Bacteria,Gemmatirosa,"Little-studied soil bacteria of the Gemmatimonadetes, known mostly from DNA. No known role for crops."
Fungi,Fusarium,"Common soil and residue fungi. Several species cause root and crown rot, wheat head blight or corn stalk and ear rot, and can leave mycotoxins in grain."
Fungi,Trichoderma,Fast-growing soil fungi that attack other fungi; several species are sold as biological seed and soil treatments. Also strong residue decomposers.
Fungi,Rhizophagus,"Arbuscular mycorrhizal fungi that partner with the roots of most crops, helping them reach phosphorus and water. Used in commercial inoculants."
Fungi,Mortierella,"Very common soil fungi that feed on simple organic matter and fresh residues. Generally harmless; some isolates are reported to free phosphorus."
```

What the examples show: Bradyrhizobium (useful, also a nitrogen cycler: the summary is "Useful"); Streptomyces,
Pseudomonas, Bacillus and Fusarium (useful and harmful species: "Mixed", each harmful row with named species);
Nitrososphaera (pure nitrogen cycler); Halobacterium (doubtful name, alone); Gemmatirosa (honest unknown, alone);
Mortierella (`low` row kept for review, not counted).

## 8. Working method and self-check

1. Read `rules/microbe_ontology.csv` and your input chunk.
2. Work in **batches of about 50 genera** in input order. After each batch, append its rows to both output files
   (write the header only once), so a crash never loses more than one batch.
3. After the last batch, run the self-check below and fix every reported problem (re-write the affected rows; do
   not just delete genera). Repeat until it prints `OK`. Run it from the repo root.

```bash
.venv/bin/python - c07 <<'PY'   # replace c07 by your chunk name
import re, sys
import pandas as pd
chunk = sys.argv[1]
d = "data/annotation_chunks"
onto = pd.read_csv("rules/microbe_ontology.csv", keep_default_na=False)
parent = dict(zip(onto.term_id, onto.parent_id))
def ancestors(t):
    out = set()
    while parent.get(t):
        t = parent[t]; out.add(t)
    return out
roots_ok = {"unknown"}
inp = pd.read_csv(f"{d}/{chunk}_input.csv", keep_default_na=False)
roles = pd.read_csv(f"{d}/{chunk}_roles.csv", keep_default_na=False, dtype=str)
desc = pd.read_csv(f"{d}/{chunk}_desc.csv", keep_default_na=False, dtype=str)
err = []
if list(roles.columns) != "domain,genus,term_id,confidence,evidence,source,species_examples,note".split(","): err.append("roles header")
if list(desc.columns) != ["domain", "genus", "description"]: err.append("desc header")
keys = set(zip(inp.domain, inp.genus))
for name, df in (("roles", roles), ("desc", desc)):
    got = set(zip(df.domain, df.genus))
    if keys - got: err.append(f"{name}: missing {sorted(keys - got)[:10]} ({len(keys - got)})")
    if got - keys: err.append(f"{name}: not in input {sorted(got - keys)[:10]}")
if desc.duplicated(["domain", "genus"]).any(): err.append("desc: duplicate genera")
if roles.duplicated(["domain", "genus", "term_id"]).any(): err.append("roles: duplicate (genus, term)")
bad = roles[~roles.term_id.isin(onto.term_id) | (roles.term_id.isin(onto.term_id[onto.parent_id == ""]) & ~roles.term_id.isin(roots_ok))]
if len(bad): err.append(f"bad term_id: {bad[['genus','term_id']].values.tolist()[:10]}")
for col, ok in (("confidence", {"high", "medium", "low"}), ("evidence", {"well_known_genus", "some_species", "inferred"})):
    b = roles[~roles[col].isin(ok)]
    if len(b): err.append(f"bad {col}: {b[['genus', col]].values.tolist()[:10]}")
if roles.source.nunique() != 1 or not roles.source.iloc[0].startswith("llm:"): err.append(f"source: {roles.source.unique()}")
b = roles[(roles.evidence == "some_species") & (roles.species_examples.str.strip() == "")]
if len(b): err.append(f"some_species without species: {b.genus.tolist()[:10]}")
b = roles[(roles.evidence == "inferred") & (roles.confidence == "high")]
if len(b): err.append(f"inferred + high: {b.genus.tolist()[:10]}")
b = roles[roles.note.str.len() > 120]
if len(b): err.append(f"note > 120 chars: {b.genus.tolist()[:10]}")
for (dom, g), sub in roles.groupby(["domain", "genus"]):
    t = set(sub.term_id)
    if len(sub) > 4: err.append(f"{g}: {len(sub)} rows (max 4)")
    if t & {"unknown", "doubtful_assignment"} and len(t) > 1: err.append(f"{g}: unknown/doubtful must stand alone")
    if any(ancestors(x) & t for x in t): err.append(f"{g}: term together with its ancestor")
abbrev = re.compile(r"\b(e\.g|i\.e|etc|spp|sp|incl|cf|vs)\.|\b[A-Z]\.")
for r in desc.itertuples():
    s = r.description.strip()
    if not s: err.append(f"{r.genus}: empty description"); continue
    if len(s) > 220: err.append(f"{r.genus}: description {len(s)} chars (max 220)")
    if len(re.findall(r"[.!?](?=\s+[A-Z(]|\s*$)", abbrev.sub("X", s))) > 2: err.append(f"{r.genus}: more than 2 sentences")
    if "\n" in s: err.append(f"{r.genus}: line break in description")
print("\n".join(err) if err else f"OK: {len(keys)} genera, {len(roles)} role rows")
PY
```

Do not write anything else into `data/annotation_chunks/` and do not edit other repo files. When done, report: the
chunk name, number of genera, number of role rows, how many genera ended as `unknown` and `doubtful_assignment`,
and any genus whose name you could not place (written as `unknown`).
