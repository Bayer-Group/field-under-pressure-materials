# Microbe roles: contract for backend, frontend and annotation

What microbes in a soil sample are likely to *do* for a crop, at genus level, GO-style: a small ontology of
terms (`rules/microbe_ontology.csv`), many-to-many annotations genus → term (`rules/microbe_annotations.csv`,
plus a deterministic mapping of FUNGuild / FungalTraits for fungi), one plain-language description per genus
(`rules/microbe_genera.csv`). Shown as a "Roles" view in the Soil microbes tab, as hover descriptions wherever a
genus name appears, and as "who may carry it (by name)" in the Soil functions tab.

Everything below is binding for the parallel agents. Names, values and field orders are exact.

## 1. Files

| file | written by | content |
|---|---|---|
| `rules/microbe_ontology.csv` | step 1 (fixed) | `term_id,parent_id,label,polarity,ko_group,description`; 32 terms |
| `rules/microbe_annotation_prompt.md` | step 1 (fixed) | instructions for annotator agents |
| `data/annotation_chunks/<chunk>_roles.csv`, `<chunk>_desc.csv` | annotators (step 3) | gitignored chunks |
| `rules/microbe_annotations.csv` | merge (step 4) | LLM rows only: `domain,genus,term_id,confidence,evidence,source,species_examples,note`, sorted by domain, genus, ontology order of term |
| `rules/microbe_genera.csv` | merge (step 4) | `domain,genus,description`, one row per exported genus, sorted by domain, genus |
| `src/cropfit/microbe_roles.py` | backend (step 5) | loading, curated fungal mapping, summary rule, roll-up |

Curated fungal rows are **not** written into `microbe_annotations.csv`; `microbe_roles.py` computes them at load
time from `data/processed/kb_fungaltraits_genus.parquet` and `data/processed/fungal_guilds.parquet` (section 4).

### 1.1 Ontology rules

- Rows are in **depth-first order** (every parent directly followed by its whole subtree). That order is the
  display order of the term tree and the tie-break order everywhere below.
- Five roots, `parent_id` empty: `useful`, `harmful`, `context`, `background`, `unknown`. Every term's `polarity`
  equals its root's id. `depth`: roots 0, their children 1, and so on.
- `ko_group`: `function_group` values of `rules/ko_panel.csv`, `;`-separated, empty for none. The join with the
  Soil functions tab always goes through this column, never through `term_id`.
- Term ids (32):

```
useful                        Useful
  nutrient_supply             Nutrient suppliers
    n_fixation                Nitrogen fixers                         ko: n_fixation
      legume_symbiont         Legume nodule partners
    p_mobilisation            Phosphorus solubilisers                 ko: p_mobilisation
    mycorrhizal_partner       Arbuscular mycorrhizal fungi
  plant_growth_promotion      Growth promoters
    acdS                      Root stress relievers                   ko: acdS
    phytohormone              Plant hormone makers
  biocontrol                  Pest and disease suppressors
    antibiotic_producer       Antimicrobial producers                 ko: phlD;hcnA
    mycoparasite              Parasites of other fungi
    chitinase                 Chitin digesters                        ko: chitinase
    pest_antagonist           Insect and nematode enemies
harmful                       Potentially harmful
  plant_pathogen              Genera with plant pathogens
    root_soilborne_pathogen   Root and soilborne pathogens
    foliar_pathogen           Leaf, stem, head and seed pathogens
  mycotoxin_producer          Mycotoxin producers
  animal_human_pathogen       Human or animal pathogens
context                       Nitrogen cyclers
  nitrification               Nitrifiers                              ko: nitrification
  denitrification             Denitrifiers                            ko: denitrification
  nosZ                        N2O reducers                            ko: nosZ
  dnra                        Nitrate-to-ammonium (DNRA)              ko: dnra
background                    Neutral / background
  decomposer                  Decomposers
  endophyte                   Endophytes
  tree_mycorrhizal            Tree mycorrhizal fungi
  common_soil_microbe         Common soil microbes
unknown                       Role unknown
  doubtful_assignment         Probably misnamed reads
```

`ko_panel.csv` groups without a term: `urease` (in nearly every soil bacterium), `copper_resistance`, `marker`.

### 1.2 Annotation rows

`domain` ∈ `Bacteria | Archaea | Fungi`; `confidence` ∈ `high | medium | low`; `evidence` ∈ `curated_db |
well_known_genus | some_species | inferred`; `source` ∈ `funguild | fungaltraits | llm:<model id> |
llm:<model id>+reviewed`; `species_examples` `; `-separated binomials (API: list, split on `;`, stripped, empties
dropped); `note` free text ≤120 chars. Key (`domain`, `genus`, `term_id`) is unique. LLM rows never use
`curated_db`. Every exported genus has ≥1 row; `unknown` / `doubtful_assignment` rows stand alone; no term
together with one of its ancestors for the same genus (LLM file; merged curated rows follow section 4).

**Counted rows**: rows with `confidence` in (`high`, `medium`). Low rows are kept in the files for review but are
ignored by every share, class and list the API returns.

## 2. Summary rule (genus → exactly one class: the partition)

For a genus, let *P* = the set of polarities of the terms of its **counted** rows (merged LLM + curated). Then, in
this order:

1. `useful` ∈ P **and** `harmful` ∈ P → **`mixed`**
2. `harmful` ∈ P → **`harmful`**
3. `useful` ∈ P → **`useful`**
4. `context` ∈ P → **`context`**
5. `background` ∈ P → **`background`**
6. otherwise (no rows, only low rows, only `unknown`-subtree rows, or genus not annotated) → **`unknown`**

So useful/harmful outrank nitrogen cycling, which outranks background (Bradyrhizobium with `legume_symbiont` +
`denitrification` is `useful`; Nitrososphaera with only `nitrification` is `context`).

| class id | label (UI, exact) |
|---|---|
| `useful` | Useful |
| `harmful` | Potentially harmful |
| `mixed` | Mixed (useful and harmful species) |
| `context` | Nitrogen cyclers |
| `background` | Neutral / background |
| `unknown` | Role unknown |

Fixed order everywhere (bar, legend, API list): useful, mixed, harmful, context, background, unknown. Reads
without a genus name stay in `unassigned_pct` and are never spread over classes.

## 3. Roll-up of one sample (terms overlap, summary does not)

Input: the sample's named genera with `pct` (share of the group's reads, 0-100, exactly as
`Composition.taxa[].pct` at rank `genus`) and `reads`.

- **Summary class pct** = Σ pct of the genera in that class. The six add up to `100 - unassigned_pct`.
  `pct_of_named` = class pct / (100 - unassigned_pct) × 100 (0 when nothing is named).
- **Term pct** (every term except the `unknown` root) = Σ pct over the *distinct* genera that have a counted row
  on the term **or any descendant**. Overlaps are intended: a genus counts once per term but can count in several
  terms; roots `useful` and `harmful` both include `mixed` genera.
- **`unknown` root pct** = Σ pct of genera whose summary class is `unknown` (includes genera not in the annotation
  files). `doubtful_assignment` follows the general rule (counted rows only).
- **Representative row** for a (term, genus) pair, shown in genus lists: among the genus's counted rows in the
  term's subtree, the highest confidence, then the first in ontology order. For the `unknown` root: the genus's
  `unknown` / `doubtful_assignment` row if any (any confidence), else a synthetic row `term_id=unknown,
  confidence=low, evidence=inferred, source=unannotated, species_examples=[], note="not in the annotation files"`.
- `annotated_pct` = Σ pct of genera with ≥1 row in the merged annotations (any confidence).
- Genus lookup: bacteria samples match annotation rows with domain `Bacteria` or `Archaea` by genus name;
  fungi samples match domain `Fungi`. Names are compared exactly (`Candidatus ...` included).

## 4. Curated fungal mapping (FUNGuild, FungalTraits) and override rule

### 4.1 Mapping tables (coded as constants in `microbe_roles.py`)

**FungalTraits** (`kb_fungaltraits_genus.parquet`, join on column `genus`; `primary_lifestyle` and
`secondary_lifestyle` may hold several values separated by `|`, `plant_pathogenic_capacity` several separated by
`,`). Every row produced: `evidence=curated_db`, `source=fungaltraits`, `species_examples` empty, `note` =
`"FungalTraits primary_lifestyle=<value>"` (or `secondary_lifestyle=` / `plant_pathogenic_capacity=`).

`FT_LIFESTYLE_TERM` (applies to primary and secondary lifestyle):

| lifestyle value | term_id |
|---|---|
| `plant_pathogen` | pathogen axis, organ from capacity (below) |
| `arbuscular_mycorrhizal` | `mycorrhizal_partner` |
| `ectomycorrhizal`, `ericoid_mycorrhizal` | `tree_mycorrhizal` |
| `mycoparasite` | `mycoparasite` |
| `soil_saprotroph`, `litter_saprotroph`, `wood_saprotroph`, `unspecified_saprotroph`, `unsepcified_saprotroph` (typo in source), `dung_saprotroph`, `nectar/tap_saprotroph`, `pollen_saprotroph`, `fungal_decomposer`, `animal_decomposer`, `algal_decomposer` | `decomposer` |
| `foliar_endophyte`, `root_endophyte`, `root_endophyte_dark_septate` | `endophyte` |
| anything else (`lichenized`, `animal_parasite`, `lichen_parasite`, `epiphyte`, `sooty_mold`, `algal_parasite`, `animal_endosymbiont`, `root-associated`, `unspecified*`, ...) or empty | no row |

`FT_CAPACITY_TERM` (organ of a plant pathogen):

| `plant_pathogenic_capacity` value | term_id |
|---|---|
| `root_pathogen` | `root_soilborne_pathogen` |
| `leaf/fruit/seed_pathogen` | `foliar_pathogen` |
| `wood_pathogen`, `other_plant_pathogen`, `unspecified_plant_pathogen` | `plant_pathogen` (only if no root/foliar value is present) |
| `algal_parasite`, `moss_parasite`, `root-associated`, `moss-associated` | ignored |

Confidence of FungalTraits rows:
- primary lifestyle → `high`; secondary lifestyle → `medium`;
- pathogen axis when **primary** is `plant_pathogen`: one row per organ term from the capacity, `high`; no
  usable capacity → one `plant_pathogen` row, `high`; capacity `wood_pathogen` only → `plant_pathogen`, `low`
  (tree pathogens, note `"... wood/tree pathogen"`);
- pathogen axis otherwise (secondary lifestyle `plant_pathogen`, or a capacity value on a genus whose primary is
  not `plant_pathogen`): organ rows (or `plant_pathogen`) at `low`.

**FUNGuild** (`fungal_guilds.parquet`, column `category` from `funguild.CATEGORY`, join on `genus`). Rows:
`evidence=curated_db`, `source=funguild`, `note="FUNGuild primary guild=<primary_guild>"`; confidence from
FUNGuild `confidence`: `Highly Probable` → `high`, `Probable` → `medium`, `Possible` → `low`.

`FUNGUILD_CATEGORY_TERM`:

| `category` | term_id |
|---|---|
| `arbuscular_mycorrhizal` | `mycorrhizal_partner` |
| `other_mycorrhizal` | `tree_mycorrhizal` |
| `fungal_parasite` | `mycoparasite` |
| `plant_pathogen` | `plant_pathogen` (organ unknown) |
| `endophyte` | `endophyte` |
| `saprotroph` | `decomposer` |
| `animal_or_lichen`, `other`, `unknown` | no row |

`can_be_plant_pathogen` / `can_parasitise_fungi` (any guild) are **not** mapped (FUNGuild lists "Plant Pathogen"
for most large genera).

Within the curated rows of one genus: the same term from both sources → keep one row, the higher confidence (tie:
`fungaltraits`). Drop a curated `plant_pathogen` row when a curated organ row (`root_soilborne_pathogen` /
`foliar_pathogen`) exists for the genus.

### 4.2 Override rule (fungi only; bacteria/archaea use LLM rows unchanged)

`CURATED_TERMS` = pathogen axis {`plant_pathogen`, `root_soilborne_pathogen`, `foliar_pathogen`} ∪
{`mycorrhizal_partner`, `tree_mycorrhizal`, `mycoparasite`, `decomposer`, `endophyte`}.

A fungal genus **has a curated record** when FungalTraits has a row with a non-empty `primary_lifestyle`, or
FUNGuild has a row with `category` not in {`other`, `unknown`}. For such a genus:

1. **Pathogen axis.** `curated_pathogen` := the curated rows include a pathogen-axis row with confidence
   `high`/`medium`.
   - If `curated_pathogen`: final pathogen rows = curated pathogen rows + the LLM rows on `root_soilborne_pathogen`
     / `foliar_pathogen` for organ terms the curated rows lack (kept as written, `source=llm:...`); then drop any
     `plant_pathogen` row if an organ row remains. (FungalTraits gives Fusarium only `leaf/fruit/seed_pathogen`; the
     LLM row adds its root/wilt diseases.)
   - Else: curated pathogen rows (all `low`) are kept; LLM pathogen-axis rows are kept with `confidence` capped at
     `low` and note prefixed `"capped: curated sources do not list it as a plant pathogen; "`. If both exist on the
     same term, keep the curated row.
2. **Other curated terms** (`mycorrhizal_partner`, `tree_mycorrhizal`, `mycoparasite`, `decomposer`,
   `endophyte`): per term, a curated row replaces the LLM row on that term; where curated has no row on the term,
   the LLM row stays.
3. **All other terms** (`mycotoxin_producer`, `animal_human_pathogen`, `pest_antagonist`, `p_mobilisation`,
   `antibiotic_producer`, `chitinase`, `phytohormone`, `plant_growth_promotion`, ...): LLM rows unchanged.
4. If the genus now has any row other than `unknown`/`doubtful_assignment`, drop its LLM `unknown` row. (A curated
   row next to an LLM `doubtful_assignment` row: keep both, curated wins the summary because `unknown` polarity
   never counts.)

Fungal genera without a curated record keep their LLM rows unchanged. Curated rows are produced for every genus in
the curated tables (not only exported ones); lookups by name make the extra rows harmless. When the parquet
files are missing, curated rows are empty and fungi use LLM rows only (and a note says so, section 6.2).

Examples (real values): Fusarium: FT primary `plant_pathogen` + capacity `leaf/fruit/seed_pathogen` →
`foliar_pathogen` high (fungaltraits); FUNGuild `plant_pathogen`/Possible → `plant_pathogen` low, dropped (organ
row exists); FT secondary `litter_saprotroph` → `decomposer` medium (replaces the LLM decomposer row); LLM
`root_soilborne_pathogen` and `mycotoxin_producer` kept → class `harmful`. Trichoderma: FT primary `mycoparasite`
→ `mycoparasite` high; secondary `foliar_endophyte` → `endophyte` medium; capacity `leaf/fruit/seed_pathogen` →
`foliar_pathogen` low; not `curated_pathogen` → class `useful`. Cladosporium: primary `litter_saprotroph` →
`decomposer` high; secondary `plant_pathogen` → `foliar_pathogen` low; LLM pathogen rows capped → `background`.

## 5. Module API: `src/cropfit/microbe_roles.py`

Pure functions over DataFrames; no FastAPI imports. Paths are module constants read **at call time**, so tests can
monkeypatch them; file loaders cache by `(resolved path, file mtime)` (no manual cache clearing needed).

```python
from .config import PROCESSED, RULES

ONTOLOGY_FILE = RULES / "microbe_ontology.csv"
ANNOTATIONS_FILE = RULES / "microbe_annotations.csv"
GENERA_FILE = RULES / "microbe_genera.csv"
FUNGALTRAITS_TABLE = "kb_fungaltraits_genus.parquet"     # in the `processed` dir passed in
FUNGUILD_TABLE = "fungal_guilds.parquet"

POLARITIES = ("useful", "harmful", "context", "background", "unknown")
SUMMARY_CLASSES: list[tuple[str, str]] = [
    ("useful", "Useful"), ("mixed", "Mixed (useful and harmful species)"), ("harmful", "Potentially harmful"),
    ("context", "Nitrogen cyclers"), ("background", "Neutral / background"), ("unknown", "Role unknown")]
COUNTED = ("high", "medium")
CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}
ANNOTATION_COLUMNS = ["domain", "genus", "term_id", "confidence", "evidence", "source", "species_examples", "note"]
KIND_DOMAINS = {"bacteria": ("Bacteria", "Archaea"), "fungi": ("Fungi",)}
PATHOGEN_AXIS = ("plant_pathogen", "root_soilborne_pathogen", "foliar_pathogen")
CURATED_TERMS = PATHOGEN_AXIS + ("mycorrhizal_partner", "tree_mycorrhizal", "mycoparasite", "decomposer", "endophyte")
FT_LIFESTYLE_TERM: dict[str, str]; FT_CAPACITY_TERM: dict[str, str]; FUNGUILD_CATEGORY_TERM: dict[str, str]
FUNGUILD_CONFIDENCE = {"Highly Probable": "high", "Probable": "medium", "Possible": "low"}


def load_ontology(path: Path | None = None) -> pd.DataFrame:
    """Terms in CSV (depth-first) order. Columns: term_id, parent_id (None for roots), label, polarity,
    ko_groups (list[str]), description, depth (int), root (str). Raises ValueError when a parent is missing or
    comes later, the graph has a cycle, polarity differs from the root id, or a root is not one of POLARITIES."""

def subtree(onto: pd.DataFrame, term_id: str) -> list[str]:
    """The term and all its descendants, in ontology order."""

def terms_for_ko_group(onto: pd.DataFrame, group: str) -> list[str]:
    """Terms whose ko_group lists `group` ("phlD" -> ["antibiotic_producer"]); [] when none."""

def load_llm_annotations(path: Path | None = None) -> pd.DataFrame:
    """rules/microbe_annotations.csv as ANNOTATION_COLUMNS (strings, '' for empty). Empty frame with those
    columns when the file is missing."""

def curated_fungal_rows(fungaltraits: pd.DataFrame | None, guilds: pd.DataFrame | None) -> pd.DataFrame:
    """Section 4.1 for every genus in the two tables: ANNOTATION_COLUMNS rows, domain 'Fungi', within-curated
    duplicates already resolved. Either table may be None or empty."""

def curated_record_genera(fungaltraits: pd.DataFrame | None, guilds: pd.DataFrame | None) -> set[str]:
    """Fungal genera that have a curated record (section 4.2)."""

def merge_fungal(llm: pd.DataFrame, curated: pd.DataFrame, record_genera: set[str]) -> pd.DataFrame:
    """Section 4.2 applied to the Fungi rows of `llm`; Bacteria/Archaea rows pass through unchanged. Returns
    ANNOTATION_COLUMNS, sorted by domain, genus, ontology order."""

def load_annotations(processed: Path | None = None) -> pd.DataFrame:
    """LLM rows merged with curated fungal rows read from `processed` (default PROCESSED; tables optional).
    Cached. This is what every consumer uses."""

def load_descriptions(path: Path | None = None) -> dict[tuple[str, str], str]:
    """(domain, genus) -> description from rules/microbe_genera.csv; {} when the file is missing."""

def describe(kind: str, genus: str, descriptions: dict | None = None) -> str | None:
    """Description for a genus of a 'bacteria' sample (tries Bacteria, then Archaea) or a 'fungi' sample."""

def summary_class(polarities: Iterable[str]) -> str:
    """Rule of section 2 on the polarities of a genus's COUNTED rows; returns a class id."""

def genus_summary(ann: pd.DataFrame, onto: pd.DataFrame) -> pd.DataFrame:
    """One row per annotated (domain, genus): domain, genus, summary_class, terms (list of counted term ids)."""

@dataclass
class RollUp:
    genera: pd.DataFrame       # one row per named genus of the sample: name, domain (None if unannotated),
                               # phylum, pct, reads, summary_class, annotated (bool), description
    summary: pd.DataFrame      # SUMMARY_CLASSES order, all six: class_id, label, pct, pct_of_named, n_genera,
                               # top (list[str], up to 3 largest genus names)
    terms: pd.DataFrame        # every ontology term, ontology order: term_id, parent_id, label, description,
                               # polarity, depth, ko_groups, pct, n_genera
    term_genera: pd.DataFrame  # one row per (term_id, genus) counted in the term (section 3), with the
                               # representative row: term_id, name, domain, phylum, pct, reads, row_term_id,
                               # confidence, evidence, source, species_examples (list), note, summary_class,
                               # description; sorted by term (ontology order), then pct desc, name
    annotated_pct: float
    named_pct: float           # Σ pct of named genera (= 100 - unassigned_pct)
    sources: list[str]         # distinct `source` values of counted rows of present genera, sorted

def roll_up(taxa: pd.DataFrame, kind: str, ann: pd.DataFrame | None = None, onto: pd.DataFrame | None = None,
            descriptions: dict | None = None) -> RollUp:
    """`taxa`: the sample's genus-rank table as returned by api_microbiome._bacteria_taxa / _fungi_taxa
    (columns name, phylum, pct, reads; rows with reads <= 0 are dropped). `kind`: 'bacteria' | 'fungi'.
    Defaults: load_annotations(), load_ontology(), load_descriptions()."""
```

The blind agreement test (step 4/E) uses `curated_fungal_rows` + `curated_record_genera` against the LLM rows of
the same genera, compared on three axes: pathogen (any counted pathogen-axis row), decomposer, mycorrhizal
(`mycorrhizal_partner` or `tree_mycorrhizal`).

## 6. API

### 6.1 `Taxon` gains a description (`api_microbiome.py`)

```python
class Taxon(BaseModel):
    name: str
    phylum: str | None
    pct: float
    reads: int
    description: str | None = None   # rank genus only: rules/microbe_genera.csv via microbe_roles.describe(); else None
```

### 6.2 `GET /api/microbiome/{sample_id}/roles` → `RoleComposition`

Query: `genera_per_term: int = Query(50, ge=1, le=5000)`. 404 for an unknown sample (same lookup as
`composition`). Uses `_bacteria_taxa(key, "genus")` / `_fungi_taxa(plot, date, "genus")` and
`microbe_roles.roll_up(..., ann=microbe_roles.load_annotations(core.PROCESSED))`.
Rounding: genus `pct` 4 decimals, every other pct 2 decimals.

```python
SummaryClassId = Literal["useful", "mixed", "harmful", "context", "background", "unknown"]
Polarity = Literal["useful", "harmful", "context", "background", "unknown"]
Confidence = Literal["high", "medium", "low"]
Evidence = Literal["curated_db", "well_known_genus", "some_species", "inferred"]


class RoleSummary(BaseModel):
    class_id: SummaryClassId
    label: str                       # section 2 labels, exact
    pct: float                       # share of the group's reads (same basis as Composition.taxa[].pct)
    pct_of_named: float              # share of reads with a genus name; the six add up to 100 (0 if none named)
    n_genera: int
    top: list[str]                   # up to 3 largest genus names in the class


class RoleGenus(BaseModel):
    name: str
    domain: str | None               # Bacteria | Archaea | Fungi; None when the genus is not annotated
    phylum: str | None
    pct: float                       # share of the group's reads, 0-100
    reads: int
    term_id: str                     # term of the representative row: the listed term itself or a descendant
    confidence: Confidence
    evidence: Evidence
    source: str                      # funguild | fungaltraits | llm:<model> | llm:<model>+reviewed | unannotated
    species_examples: list[str]
    note: str | None
    summary_class: SummaryClassId
    description: str | None


class RoleTerm(BaseModel):
    term_id: str
    parent_id: str | None
    label: str
    description: str                 # the ontology's one-sentence description
    polarity: Polarity
    depth: int                       # 0 for the five roots
    ko_groups: list[str]
    pct: float                       # Σ pct of distinct genera with a counted row on the term or a descendant
    n_genera: int
    genera: list[RoleGenus]          # largest first, at most `genera_per_term`
    other_genera_pct: float          # pct of the term's genera beyond the list (0 when all listed)


class RoleComposition(BaseModel):
    sample_id: str
    kind: Kind
    plot_id: str
    date: dt.date
    reads: int
    n_genera: int                    # named genera in the sample
    summary: list[RoleSummary]       # always six, order useful, mixed, harmful, context, background, unknown
    terms: list[RoleTerm]            # all 32 terms, ontology (depth-first) order, empty ones included
    annotated_pct: float             # share of the group's reads from genera with >= 1 annotation row
    unassigned_pct: float            # reads without a genus name, as Composition at rank genus
    sources: list[str]               # distinct sources behind the counted rows of this sample
    notes: list[str]
```

`notes`: the sample notes of `_notes(r)` first, then, in this order:
1. `"Roles are given per genus: a genus marked as including pathogens usually also holds harmless species, and one genus can have several roles."`
2. bacteria: `"Roles come from an AI (LLM) annotation of each genus, checked by a second AI review only for harmful and abundant genera."`;
   fungi: the same sentence + `" For fungi, FUNGuild and FungalTraits are used wherever they give a role."`
   (if their tables are missing: `" FUNGuild and FungalTraits tables are missing here, so fungal roles are from the AI annotation only."`)
3. `"Only roles given with medium or high confidence are counted."`
4. when `named_pct - annotated_pct >= 0.5`: `f"{named_pct - annotated_pct:.0f}% of the reads are from genera not yet annotated; they count as Role unknown."`

### 6.3 Soil functions additions (`api_functions.py`)

Genes say the capacity is in the soil; names say who is likely to carry it. Named carriers come from the
**same metagenome** (Kraken2 genus composition, bacteria + archaea, via `api_microbiome._bacteria_taxa(
r.metagenome_key, "genus")` and `microbe_roles.roll_up(..., "bacteria")`). Fungi are not used as carriers (the
gene panel is bacterial). Shares are **of the sample's classified bacterial + archaeal reads**, the same numbers
as the Soil microbes tab. Each sample on its own, no comparison with other plots.

Constants:

```python
CARRIER_MIN_PCT = 0.1                 # summed share of a term's genera from which "known carriers are present"
CARRIER_TOP = 5                       # genera listed per term
BACTERIA_PATHOGEN_GENUS_FLAG = 1.0    # % of classified bacterial+archaeal reads, one mostly-pathogenic genus
CARRIER_TERMS = ["n_fixation", "nitrification", "denitrification", "nosZ", "dnra", "p_mobilisation",
                 "antibiotic_producer", "acdS", "chitinase"]   # = ontology terms with a ko_group, ontology order
```

Models (new and changed):

```python
Agreement = Literal["both", "genes_only", "names_only", "neither", "unknown"]


class CarrierGenus(BaseModel):
    name: str
    pct: float                       # share of classified bacterial + archaeal reads, 4 decimals
    term_id: str                     # term of the representative row (e.g. legume_symbiont under n_fixation)
    confidence: Literal["high", "medium"]
    evidence: str
    species_examples: list[str]
    description: str | None


class Carriers(BaseModel):
    term_id: str
    label: str                       # ontology label
    ko_groups: list[str]             # function groups behind the genes
    pct: float                       # term pct from the roll-up (counted rows, term + descendants)
    n_genera: int
    top: list[CarrierGenus]          # largest first, at most CARRIER_TOP
    genes: str                       # found | trace | not_found | too_few_genes: best status over ko_groups
    agreement: Agreement
    agreement_text: str


class FunctionGroup(BaseModel):      # existing + term_id
    ...
    term_id: str | None              # ontology term whose ko_group lists this group (phlD, hcnA -> antibiotic_producer)


class Pathway(BaseModel):            # existing + term_id
    ...
    term_id: str | None              # Denitrification -> denitrification, DNRA -> dnra, Nitrification ->
                                     # nitrification, Nitrogen fixation -> n_fixation, Urea breakdown -> None


class FungalRole(BaseModel):         # existing + term_id
    ...
    term_id: str | None              # FUNGUILD_CATEGORY_TERM[role]; label = ontology label when set, else FUNGAL_ROLE


class DecisionCard(BaseModel):       # existing + carrier_terms; basis gains "names"
    ...
    basis: str                       # measured | genes | fungi | names
    carrier_terms: list[str] = []    # term ids to look up in FunctionProfile.carriers, shown as "Who may carry it"


class FunctionProfile(BaseModel):    # existing + carriers
    ...
    carriers: list[Carriers]         # one per CARRIER_TERMS entry, that order; [] when taxa_lineage is missing
```

`carrier_terms` per card: `nitrogen` → `["n_fixation", "nitrification", "denitrification", "nosZ", "dnra"]`;
`p_release` → `["p_mobilisation"]`; `root_health` → `["antibiotic_producer", "acdS", "chitinase"]`; all other
cards `[]`. The three "Too few genes to tell" stub cards carry the same `carrier_terms`.

**Gene status of a term** = the best `FunctionGroup.status` over its `ko_groups`, order found > trace > not_found
> too_few_genes. `genes_present` = status in (found, trace). `names_present` = `pct >= CARRIER_MIN_PCT`.

| agreement | when | agreement_text (exact) |
|---|---|---|
| `both` | genes_present and names_present | `Genes found, and genera known to carry them are present.` |
| `genes_only` | genes_present, not names_present | `Genes found, but no known carrier by name: they may come from unnamed or unexpected microbes.` |
| `names_only` | status not_found, names_present | `Known carriers present by name, but genes not found: sequencing depth may be too low, or these strains lack the genes.` |
| `neither` | status not_found, not names_present | `Neither genes nor known carriers by name found.` |
| `unknown` | status too_few_genes | `Too few genes to compare with the named carriers.` |

For `antibiotic_producer` append `" The marker genes (DAPG, hydrogen cyanide) cover only some antimicrobial producers."`
to every agreement_text.

Add to `FunctionProfile.notes`: `"Who may carry it: genera of this sample's bacteria and archaea known for the role (AI annotation, medium or high confidence); shares are of the classified bacterial and archaeal reads."`

**New card `bacteria_pathogens`** ("Bacteria that include plant pathogens"), computed from the same roll-up,
added for every sample with genus-level bacterial data, **before** the `if not deep` early return (it does not
depend on gene depth, like the fungi card):

- *pathogen genera* = genera with a counted row on `plant_pathogen`, `root_soilborne_pathogen` or
  `foliar_pathogen`; *mostly pathogenic* = those whose representative pathogen row has
  `evidence == "well_known_genus"` (e.g. Xanthomonas, Clavibacter, Pectobacterium); the others are
  *some species only* (Pseudomonas, Streptomyces).
- shares: of classified bacterial + archaeal reads (`_p()` formatting as elsewhere).
- `status="notice"` and `flag=f"{name} alone is {pct:.1f}% of bacterial DNA"` when one mostly pathogenic genus
  has `pct >= BACTERIA_PATHOGEN_GENUS_FLAG`; else `status="info"`, `flag=None`. Genera where only some species are
  pathogens never colour the card.
- `headline`: `f"{_p(total)} from genera that include plant pathogens · {_p(mostly)} from mostly pathogenic genera"`;
  none present: `"No genera known for plant pathogens"`.
- `finding`: `"Of the classified bacterial DNA, X is from genera that include plant pathogens: "` + up to 4
  largest as `"Streptomyces 14% (S. scabies)"` (first species example abbreviated), joined by `", "`, + `"."`.
- `implications`: risk, when mostly pathogenic genera are present: `"Genera whose species are mostly plant pathogens are present (...). Disease also needs a susceptible crop and suitable weather."`; neutral, when some-species genera are present: `"Most of this share is from genera where only some species cause disease (...); harmless relatives usually dominate in soil."`; neutral always: `"Names come from short DNA reads matched to reference genomes: small shares of well-known pathogen genera can be misassigned reads."`
- `evidence`: one line per listed genus `f"{name} {pct:.2f}%: {term label}, {confidence} confidence, {source}" + species`,
  then `f"Coloured when one genus whose species are mostly plant pathogens makes up {BACTERIA_PATHOGEN_GENUS_FLAG:.0f}% or more of the classified bacterial DNA."`,
  then `"Roles from the microbe role annotation (AI, with a second AI review of harmful genera), genus level."`
  (+ `"Few bacterial reads: small shares may be noise."` when `reads < MIN_BACTERIA_READS`).
- `basis="names"`, `confidence="low"`, `carrier_terms=[]`.

**Fungi card**: unchanged rules and FUNGuild source; only `FungalRole.label` comes from the ontology
(`FUNGUILD_CATEGORY_TERM` → term label) where a term exists, and `FungalRole.term_id` is set.

## 7. TypeScript (`web/src/api.ts`)

```ts
export interface Taxon {
  name: string
  phylum: string | null
  pct: number
  reads: number
  description: string | null // genus rank only: plain-language hover text, else null
}

export type SummaryClassId = 'useful' | 'mixed' | 'harmful' | 'context' | 'background' | 'unknown'
export type RolePolarity = 'useful' | 'harmful' | 'context' | 'background' | 'unknown'
export type RoleConfidence = 'high' | 'medium' | 'low'
export type RoleEvidence = 'curated_db' | 'well_known_genus' | 'some_species' | 'inferred'

export interface RoleSummary {
  class_id: SummaryClassId
  label: string
  pct: number // share of the group's reads
  pct_of_named: number // share of reads with a genus name; the six add up to 100
  n_genera: number
  top: string[]
}

export interface RoleGenus {
  name: string
  domain: string | null
  phylum: string | null
  pct: number
  reads: number
  term_id: string // the term of this row: the listed term or a descendant
  confidence: RoleConfidence
  evidence: RoleEvidence
  source: string // funguild | fungaltraits | llm:<model>[+reviewed] | unannotated
  species_examples: string[]
  note: string | null
  summary_class: SummaryClassId
  description: string | null
}

export interface RoleTerm {
  term_id: string
  parent_id: string | null
  label: string
  description: string
  polarity: RolePolarity
  depth: number
  ko_groups: string[]
  pct: number // genera with this role or a sub-role; terms overlap
  n_genera: number
  genera: RoleGenus[] // largest first, capped
  other_genera_pct: number
}

export interface RoleComposition {
  sample_id: string
  kind: MicrobeKind
  plot_id: string
  date: string
  reads: number
  n_genera: number
  summary: RoleSummary[] // six, fixed order
  terms: RoleTerm[] // depth-first ontology order
  annotated_pct: number
  unassigned_pct: number
  sources: string[]
  notes: string[]
}

export type Agreement = 'both' | 'genes_only' | 'names_only' | 'neither' | 'unknown'

export interface CarrierGenus {
  name: string
  pct: number // share of classified bacterial + archaeal reads
  term_id: string
  confidence: 'high' | 'medium'
  evidence: string
  species_examples: string[]
  description: string | null
}

export interface Carriers {
  term_id: string
  label: string
  ko_groups: string[]
  pct: number
  n_genera: number
  top: CarrierGenus[]
  genes: PresenceStatus
  agreement: Agreement
  agreement_text: string
}

// changed existing types
export interface FunctionGroup { /* existing fields */ term_id: string | null }
export interface Pathway { /* existing fields */ term_id: string | null }
export interface Fungi { /* existing */ roles: { role: string; label: string; pct: number; top: string[]; term_id: string | null }[] }
export interface DecisionCard { /* existing */ basis: 'measured' | 'genes' | 'fungi' | 'names'; carrier_terms: string[] }
export interface FunctionProfile { /* existing */ carriers: Carriers[] }

// in `api`:
roles: (sampleId: string, s?: AbortSignal) => get<RoleComposition>(`/microbiome/${id(sampleId)}/roles`, s),
```

`DecisionCards.tsx` `BASIS_LABEL` gains `names: 'Bacterial names'`.

## 8. UI behaviour

### 8.1 Genus hover descriptions (shared component)

New `web/src/GenusName.tsx`: `<GenusName name={string} description={string | null} />`.
- With a description: renders the name as `<span className="genus-name" tabIndex={0} aria-describedby={tipId}>`
  (dotted underline) plus `<span role="tooltip" id={tipId} className="genus-tip">{description}</span>` (`useId`).
  The tip shows on pointer hover **and** keyboard focus, hides on blur/pointer leave and on `Escape`; max width
  ~280px, above the name (below when no room), never clipped by table containers (position: absolute inside a
  `position: relative` wrapper, `z-index` above tables), does not steal clicks.
- Without a description: plain text, not focusable, no tooltip. Never use the native `title` attribute alone.
- Used wherever a genus name is shown:
  1. Soil microbes, Taxonomy view, rank **genus**: the table's first cell (`CompositionView`), and the readout
     under the bar: when the hovered part is a genus with a description, a second line `<p className="seg-desc">`
     shows it (bar segments stay non-focusable; the table is the keyboard path).
  2. Roles view genus table (8.2).
  3. Soil functions: every carrier genus in "Who may carry it" lists (8.3).

### 8.2 Soil microbes: "View: Roles | Taxonomy"

- Route: the view is a hash query parameter on the microbes route: `#/plot/<id>/microbes/<sample>?view=taxonomy`.
  `parseRoute` strips `?...` from the hash before splitting and returns `view: 'taxonomy' | 'roles'` (default
  `'roles'`) on the map route; `microbesHref(plotId, sampleId?, view?)` appends `?view=taxonomy` only for taxonomy.
  Switching sample, year or organism keeps the view.
- `MicrobiomePanel`: a `Choice` "View" with buttons **Roles** (the default) and **Taxonomy** after "Organisms". In Roles view
  the "Group by" choice is hidden (roles are genus level) and the sub-heading reads `Share of DNA reads per role ·
  N reads from K soil cores`. Data: `api.roles(sampleId)` with `useFetch` key `` `${sample}|roles` ``. The notes
  block ("About this sample") renders `RoleComposition.notes` as in Taxonomy view.
- `RolesView.tsx` (new, `web/src/features/microbiome/`), top to bottom:
  1. **Summary bar**: one 100% stacked bar (same height/style as `seg-bar`) of the six classes by `pct`, in the
     fixed order, plus a final grey segment "No genus name" (`unassigned_pct`, colour `UNASSIGNED`). Segments
     carry their pct text when wide enough. Hover shows a readout: `label · pct · n_genera genera · top names`.
     Legend below with each class's colour, label and `pct_of_named` (e.g. "Useful 31% of named").
     Colours (add `ROLE_COLOR` to `colors.ts`): useful `#1baf7a`, mixed `#eda100` (dark ink), harmful `#e34948`,
     context `#2a78d6`, background `#b39b72` (dark ink), unknown `#a9a8a1` (`OTHER`).
  2. **Term tree**: one row per term in API order, indented by `depth`. Roots expanded (their depth-1 children
     visible); deeper levels collapsed behind a disclosure button (`aria-expanded`). Each row: label, a separate
     horizontal bar (not stacked) in the polarity colour, pct text and `n_genera`. All bars share one scale:
     0 to the largest `pct` among the terms. Terms with `n_genera == 0` are shown dimmed ("none in this sample").
     The ontology `description` is the row's hover/focus tooltip (same tooltip component pattern). Line above the
     tree: "A genus can have several roles, so these shares can add up to more than 100%."
  3. **Genus table** for the selected term: selecting a row (click or Enter/Space; the row label is a `button`,
     `aria-pressed`) shows its `genera` below the tree in a `comp-table`: Genus (`GenusName`), Share (bar +
     pct, as in `CompositionView`), Reads, Role (the label of `term_id` when it differs from the selected term,
     e.g. "Legume nodule partners" under Nitrogen fixers), Confidence, Source (`fungaltraits` → "FungalTraits",
     `funguild` → "FUNGuild", `llm:...` → "AI annotation", `...+reviewed` → "AI annotation, reviewed",
     `unannotated` → "Not annotated"), Species examples (italic, `; `-joined). If `other_genera_pct > 0`: a last
     muted row `"N more genera, together x%"` (N = `n_genera - genera.length`). Default selection: none, with the
     hint "Choose a role to list its genera."
  4. **Caveat line** (fixed, muted, always shown): "Genus level: a genus marked as including pathogens also
     contains harmless species. Roles come from an AI annotation of each genus, checked by a second AI review only
     for harmful and abundant genera; for fungi, FUNGuild and FungalTraits are used where they give a role."

### 8.3 Soil functions: "Who may carry it (by name)"

- `DecisionCards` takes an optional `carriers?: Carriers[]` prop; inside a card's "More" section, after the
  evidence, for each id in `card.carrier_terms` found in `carriers`: a block titled "Who may carry it (by name)":
  `label · pct` (formatted like `_p`, e.g. "<1%"), then the `agreement_text` (styled muted; `names_only` and
  `genes_only` get the caution style), then the `top` genera as an inline list `GenusName pct` with species
  examples in italics after each name (first one only, abbreviated "B. japonicum"). Empty `top`: "No known
  carrier above 0.1% of reads."
- Details section, "Nitrogen pathways in this sample": under each pathway with `term_id`, one line "Who may
  carry it: Bradyrhizobium 6.1%, Mesorhizobium 1.2%, ..." (GenusName each) + the `agreement_text`.
- The new `bacteria_pathogens` card renders like any other card (basis label "Bacterial names").
- `FungalRoles` table unchanged except its labels now come from the API (already ontology labels).

## 9. Fixtures and tests

Tests monkeypatch `microbe_roles.ANNOTATIONS_FILE` / `GENERA_FILE` to files in `tmp_path` and keep the real
`rules/microbe_ontology.csv`. Minimal annotations matching the existing `tests/test_api_microbiome.py` fixture
(Streptomyces 20 000, Bradyrhizobium 10 000, Nitrososphaera 5 000 of 100 000 classified reads; fungi Fusarium
40%, Mortierella 30%, 30% unnamed):

```csv
domain,genus,term_id,confidence,evidence,source,species_examples,note
Bacteria,Streptomyces,antibiotic_producer,high,well_known_genus,llm:test,Streptomyces griseus,
Bacteria,Streptomyces,root_soilborne_pathogen,medium,some_species,llm:test,Streptomyces scabies,potato scab
Bacteria,Bradyrhizobium,legume_symbiont,high,well_known_genus,llm:test,Bradyrhizobium japonicum,
Bacteria,Bradyrhizobium,denitrification,low,some_species,llm:test,Bradyrhizobium diazoefficiens,
Archaea,Nitrososphaera,nitrification,high,well_known_genus,llm:test,Nitrososphaera viennensis,
Fungi,Fusarium,root_soilborne_pathogen,high,some_species,llm:test,Fusarium oxysporum,
Fungi,Fusarium,mycotoxin_producer,high,well_known_genus,llm:test,Fusarium graminearum,
Fungi,Mortierella,unknown,low,inferred,llm:test,,
```

```csv
domain,genus,description
Bacteria,Streptomyces,Thread-forming soil bacteria that break down residues and make many antibiotics. A few species cause potato scab.
Fungi,Fusarium,Common soil and residue fungi; several species cause root rot or head blight.
```

Expected for `mg-dobj-1` roles: summary pct useful 10 (Bradyrhizobium; its low denitrification row ignored),
mixed 20 (Streptomyces), harmful 0, context 5 (Nitrososphaera), background 0, unknown 0; `pct_of_named` useful
28.57, mixed 57.14, context 14.29; `unassigned_pct` 65, `annotated_pct` 35. Terms: `useful` 30,
`nutrient_supply` 10, `n_fixation` 10 (Bradyrhizobium with `term_id` `legume_symbiont`), `legume_symbiont` 10,
`biocontrol` 20, `antibiotic_producer` 20, `harmful` 20, `plant_pathogen` 20, `root_soilborne_pathogen` 20,
`context` 5, `nitrification` 5, `denitrification` 0. Genus-rank composition: Streptomyces has its description,
Bradyrhizobium `description` null; phylum rank all null.

Fungi `its-P_001-20200615`, no curated tables: Fusarium `harmful` 40, Mortierella `unknown` 30. Add a curated
fixture `fungal_guilds.parquet` with `genus=Mortierella, category=saprotroph, primary_guild="Undefined Saprotroph",
confidence=Probable` (plus the other `guild_table` columns): Mortierella becomes `decomposer` medium,
`source=funguild`, its LLM `unknown` row is dropped, class `background` 30. A FungalTraits fixture row
`genus=Fusarium, primary_lifestyle=plant_pathogen, secondary_lifestyle=litter_saprotroph,
plant_pathogenic_capacity=leaf/fruit/seed_pathogen` gives Fusarium `foliar_pathogen` high (fungaltraits) +
`decomposer` medium, while the LLM `root_soilborne_pathogen` row stays (section 4.2 rule 1).

Unit tests to cover (`tests/test_microbe_roles.py`): ontology is a depth-first tree with valid polarities and
`ko_group` values that exist in `rules/ko_panel.csv`; annotation files use valid ids and enums, no duplicate
keys, `unknown`/`doubtful_assignment` alone, every genus in `microbe_genera.csv`; `summary_class` cases (useful +
harmful → mixed; useful + context → useful; context + background → context; only low rows → unknown; empty →
unknown); roll-up: summary pcts + unassigned = 100, term pct counts each genus once even with two rows in its
subtree; curated override cases above; carriers agreement table (one case per value); `bacteria_pathogens` flag
fires for a 1.2% `well_known_genus` pathogen and not for a 20% `some_species` one.
