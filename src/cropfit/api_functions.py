"""GUI API: the story one soil sample tells about its microbes. Treats the sample on its own, as if it were the
only one we had: no ranking against other plots or sites.

Three sources, all from the same soil:
  * bacteria and archaea: KEGG genes of the NMDC metagenome (rules/ko_panel.csv panel), read as which steps of
    known pathways (KEGG modules) this soil's microbes carry, and the balance between steps;
  * fungi: NEON ITS reads of the same soil cores (joined_fungi_genus; else the same plot within MATCH_DAYS),
    each genus given its ecological role from FUNGuild (fungal_guilds, scripts/16_fetch_funguild.py);
  * measurements NEON made in that soil at that visit (inorganic nitrogen, pH, carbon, nitrogen, moisture).

From these it writes *cards*: what is there, and what that can mean (possible upsides and risks), each with what
it rests on and how sure it is, most trustworthy first. Statements are of three kinds, none of which needs other
samples: measured values against textbook thresholds; presence of a pathway step (with the sequencing-depth
caveat); balances within the sample (e.g. genes that make N2O vs genes that remove it). Genes are capacity, not
activity; a genus's role is the typical role of that genus, not of every species in it.

Reads ko_panel, metagenomes (scripts/05), neon_inorganic_n, neon_chem, its_genus (scripts/02b),
joined_fungi_genus (scripts/06) and fungal_guilds (scripts/14).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import api as core
from . import microbe_roles
from .api_microbiome import MIN_BACTERIA_READS, _bacteria_taxa

MATCH_DAYS = 7          # a NEON measurement within this many days of the metagenome counts as the same visit
MIN_COUNT = 5           # fewer gene copies than this is a trace
MIN_RATIO_GENES = 20    # within-sample balances need at least this many gene copies in total
MIN_FUNGAL_READS = 5_000
# When a gene or fungal card is coloured "worth noticing" (rules on the sample alone, stated on the card):
N2O_FLAG_RATIO = 10     # N2O-making genes (norB) per N2O-removing gene (nosZ), or no remover at all
PATHOGEN_GENUS_FLAG = 15.0   # one genus that includes plant pathogens makes up this % of named fungal DNA
# Named carriers (docs/microbe_roles.md section 6.3): shares are of the sample's classified bacterial + archaeal reads
CARRIER_MIN_PCT = 0.1                 # summed share of a term's genera from which "known carriers are present"
CARRIER_TOP = 5                       # genera listed per term
BACTERIA_PATHOGEN_GENUS_FLAG = 1.0    # % of classified bacterial+archaeal reads, one mostly-pathogenic genus
CARRIER_TERMS = ["n_fixation", "nitrification", "denitrification", "nosZ", "dnra", "p_mobilisation",
                 "antibiotic_producer", "acdS", "chitinase"]   # = ontology terms with a ko_group, ontology order
CARD_CARRIER_TERMS = {"nitrogen": ["n_fixation", "nitrification", "denitrification", "nosZ", "dnra"],
                      "p_release": ["p_mobilisation"], "root_health": ["antibiotic_producer", "acdS", "chitinase"]}
PATHWAY_TERM = {"Denitrification": "denitrification", "Nitrate kept as ammonium (DNRA)": "dnra",
                "Nitrification": "nitrification", "Nitrogen fixation": "n_fixation"}   # Urea breakdown: no term
GENE_STATUS_ORDER = ["found", "trace", "not_found", "too_few_genes"]
AGREEMENT_TEXT = {
    "both": "Genes found, and genera known to carry them are present.",
    "genes_only": "Genes found, but no known carrier by name: they may come from unnamed or unexpected microbes.",
    "names_only": "Known carriers present by name, but genes not found: sequencing depth may be too low, or these "
                  "strains lack the genes.",
    "neither": "Neither genes nor known carriers by name found.",
    "unknown": "Too few genes to compare with the named carriers.",
}

# Plain names for the phyla the gene phylogeny reports (closest known relatives of the genes)
FRIENDLY_PHYLUM = {
    "Actinomycetota": "actinobacteria", "Pseudomonadota": "proteobacteria", "Nitrososphaerota": "soil archaea",
    "Thermoproteota": "soil archaea", "Gemmatimonadota": "Gemmatimonadetes", "Chloroflexota": "Chloroflexi",
    "Myxococcota": "myxobacteria", "Bacteroidota": "Bacteroidetes", "Verrucomicrobiota": "Verrucomicrobia",
    "Acidobacteriota": "acidobacteria", "Cyanobacteriota": "cyanobacteria", "Bacillota": "Firmicutes",
    "Planctomycetota": "Planctomycetes", "Nitrospirota": "Nitrospira", "Ascomycota": "fungi (Ascomycota)",
}
WHO_MIN_SHARE = 15.0        # % of a function's genes for a phylum to be named
WHO_CLOSE_IDENTITY = 95.0   # % protein identity from which a genus is named as a close match
WHO_CLOSE_SHARE = 10.0      # ... and that genus carries at least this % of the genes
AMMONIA_OXIDISERS = {"Nitrososphaerota", "Thermoproteota"}             # ammonia-oxidising archaea
AMMONIA_OXIDISER_FAMILIES = {"Nitrosomonadaceae", "Nitrospiraceae"}   # ammonia-oxidising / comammox bacteria
METHANOTROPH_FAMILIES = {"Methylococcaceae", "Methylomonadaceae", "Methylocystaceae", "Beijerinckiaceae",
                         "Methylacidiphilaceae", "Methylomirabilaceae"}   # aerobic methane oxidisers
SOLUBLE_MMO = ["K16157", "K16158", "K16159", "K16160", "K16161"]       # mmoXYZBC: methanotrophs only
UNUSUAL_CLASSES = {"Energy metabolism", "Xenobiotics biodegradation", "Biosynthesis of other secondary metabolites",
                   "Biosynthesis of terpenoids and polyketides"}   # ecologically telling; housekeeping left out
UNUSUAL_RARE, MIN_REFERENCE = 2, 5   # "uncommon": complete in at most 2 of the other deep samples (needs >= 5 of them)
# Plain-language (short name, meaning) for modules a farmer may care about (general knowledge, kept short), most
# relevant first: this order ranks the "unusual" card, and only modules listed here are named in its headline.
MODULE_NOTES = {
    "M00790": ("pyrrolnitrin", "an antifungal compound made by some biocontrol bacteria"),
    "M00875": ("staphyloferrin B", "an iron-binding siderophore, which can starve pathogens of iron"),
    "M00876": ("staphyloferrin A", "an iron-binding siderophore, which can starve pathogens of iron"),
    "M01070": ("ferricrocin", "an iron-binding siderophore best known from fungi"),
    "M00623": ("phthalate breakdown", "breaks down phthalates (plastic softeners)"),
    "M00636": ("phthalate breakdown", "breaks down phthalates (plastic softeners)"),
    "M00174": ("methane oxidation", "consumes methane"),
    "M00778": ("type II polyketides", "the backbone of many antibiotics, made mostly by actinobacteria"),
    "M01039": ("spirilloxanthin", "a pigment of light-harvesting bacteria"),
    "M01044": ("astaxanthin", "a red antioxidant pigment"),
}
COPPER_RESISTANCE = ["K07233", "K07156", "K07245", "K07787", "K07798", "K07796", "K07810"]   # pco/cop + cus

# function_group in rules/ko_panel.csv -> (title, what it does, theme); used for the gene list
GROUPS: dict[str, tuple[str, str, str]] = {
    "n_fixation": ("Nitrogen fixation", "Turn nitrogen gas from the air into ammonium.", "nitrogen"),
    "nitrification": ("Nitrification", "Turn ammonium into nitrate (genes shared with methane oxidisers).", "nitrogen"),
    "denitrification": ("Denitrification", "Turn nitrate into gas, partly the greenhouse gas N2O.", "nitrogen"),
    "nosZ": ("N2O reduction", "Turn N2O into harmless nitrogen gas.", "nitrogen"),
    "dnra": ("Nitrate to ammonium", "Turn nitrate back into ammonium, which stays in the soil.", "nitrogen"),
    "urease": ("Urea breakdown", "Release ammonium from urea (manure, urea fertiliser).", "nitrogen"),
    "p_mobilisation": ("Phosphorus release", "Free phosphorus from organic matter and minerals.", "phosphorus"),
    "acdS": ("Plant stress relief", "ACC deaminase lowers the stress hormone ethylene in roots.", "plant"),
    "chitinase": ("Chitin breakdown", "Digest chitin of fungal walls and insects.", "plant"),
    "phlD": ("Antifungal DAPG", "Make the antifungal compound DAPG.", "plant"),
    "hcnA": ("Hydrogen cyanide", "Make hydrogen cyanide.", "plant"),
    "copper_resistance": ("Copper resistance", "Pump out or neutralise copper.", "pressure"),
}

# Nitrogen pathways as KEGG modules, step by step; a step is carried out by any of its genes (names as in the panel).
PATHWAYS: list[tuple[str, str, list[tuple[str, list[str]]], str | None]] = [
    ("Denitrification", "M00529", [("nitrate → nitrite", ["narG/nxrA", "napA"]), ("nitrite → NO", ["nirK", "nirS"]),
                                   ("NO → N2O", ["norB"]), ("N2O → N2", ["nosZ"])],
     "nitrate → nitrite is shared with DNRA; nosZ here is clade I only"),
    ("Nitrate kept as ammonium (DNRA)", "M00530", [("nitrate → nitrite", ["narG/nxrA", "napA"]),
                                                   ("nitrite → ammonium", ["nrfA"])],
     "only nrfA is used for the second step: nirB also serves the cell's own nitrogen uptake"),
    ("Nitrification", "M00528", [("ammonia → hydroxylamine", ["pmoA-amoA"]), ("hydroxylamine → nitrite", ["hao"]),
                                 ("nitrite → nitrate", ["narH/nxrB"])],
     "amoA cannot be told from methane-oxidiser pmoA in this annotation; nxrB not from nitrate-reducing narH"),
    ("Nitrogen fixation", "M00175", [("N2 → ammonia", ["nifH", "nifD", "nifK"])],
     "rare genes, often missed by assembly; nodule rhizobia of legumes are not covered"),
    ("Urea breakdown", "—", [("urea → ammonium", ["ureC"])], None),
]

FUNGAL_ROLE = {  # FUNGuild category -> label
    "saprotroph": "Decomposers", "plant_pathogen": "Genera that include plant pathogens",
    "arbuscular_mycorrhizal": "Arbuscular mycorrhizal (crop root partners)",
    "other_mycorrhizal": "Other mycorrhizal (mostly tree partners)", "fungal_parasite": "Parasites of other fungi",
    "endophyte": "Endophytes (live inside plants)", "animal_or_lichen": "Animal or lichen associates",
    "other": "Other roles", "unknown": "Role unknown", "no_guild": "Genus not in FUNGuild",
}

# Late-spring / pre-sidedress soil nitrate test for corn (Magdoff et al. 1984; Iowa State, Blackmer et al.).
NITRATE_ENOUGH, NITRATE_LOW = 25.0, 10.0
CN_IMMOBILISE = 20.0    # C:N above this: microbes tend to lock up nitrogen while breaking residues down
# Textbook ranges for arable topsoils (general soil fertility, e.g. Brady & Weil, The Nature and Properties of Soils).
PH_BANDS = [(5.5, "strongly acidic", "risk", "phosphorus binds to iron and aluminium and aluminium can harm roots"),
            (6.0, "moderately acidic", "neutral", "phosphorus is starting to bind to iron and aluminium"),
            (7.0, "slightly acidic to neutral", "upside", "the range where phosphorus and most nutrients are most available"),
            (7.5, "neutral to slightly alkaline", "neutral", "phosphorus is starting to bind to calcium"),
            (99, "alkaline", "risk", "phosphorus binds to calcium and iron, zinc and manganese are harder for roots to take up")]
OC_BANDS = [(1.0, "low", "risk", "little organic matter to hold water and nutrients and to feed soil life"),
            (2.0, "moderate", "neutral", "an average store of organic matter for an arable soil"),
            (99, "high", "upside", "a good store of organic matter that holds water and nutrients")]


# ---------------------------------------------------------------- response models
class FunctionSample(BaseModel):
    sample_id: str                   # same ids as the soil microbes view (mg-...)
    date: dt.date
    year: int
    n_genes: int                     # genes assembled and annotated
    deep_enough: bool                # enough genes to read absences and balances at all


class GeneCount(BaseModel):
    gene: str
    ko: str
    count: int
    caveat: str | None


class FunctionGroup(BaseModel):
    group: str
    title: str
    meaning: str
    theme: str                       # nitrogen | phosphorus | plant | pressure
    status: str                      # found | trace | not_found | too_few_genes
    genes: list[GeneCount]
    term_id: str | None              # ontology term whose ko_group lists this group (phlD, hcnA -> antibiotic_producer)


class PathwayStep(BaseModel):
    step: str
    genes: list[str]
    copies: int
    status: str                      # found | trace | not_found | too_few_genes


class Pathway(BaseModel):
    name: str
    kegg_module: str
    steps: list[PathwayStep]
    complete: bool                   # every step found
    note: str | None
    term_id: str | None              # ontology term of the pathway (None for urea breakdown)


class FungalRole(BaseModel):
    role: str
    label: str
    pct: float                       # share of fungal reads with a genus name
    top: list[str]                   # largest genera, "Fusarium 11.6%"
    term_id: str | None              # ontology term of the FUNGuild category; label is the ontology label when set


class Fungi(BaseModel):
    date: dt.date
    same_cores: bool                 # from exactly the cores of the metagenome (else same plot, nearest visit)
    reads: int | None
    named_pct: float                 # share of fungal reads that have a genus name
    roles: list[FungalRole]


class Measured(BaseModel):
    date: dt.date
    ammonium_n_mgkg: float | None
    nitrate_n_mgkg: float | None
    net_n_min_mgkg_d: float | None
    net_nitrif_mgkg_d: float | None
    ph_water: float | None
    organic_c_pct: float | None
    total_n_pct: float | None
    cn_ratio: float | None
    soil_moisture: float | None      # g water per g dry soil


class Implication(BaseModel):
    kind: str                        # upside | risk | neutral
    text: str


class DecisionCard(BaseModel):
    card: str                        # n_now | n_release | soil | nitrogen | fungi | bacteria_pathogens | p_release | copper | root_health
    title: str
    status: str                      # good | watch | act (measured threshold) | notice (sample rule) | info | unknown
    headline: str                    # one short line for the card face
    flag: str | None                 # why the card is coloured, when it is
    finding: str                     # what is there, one or two sentences
    implications: list[Implication]  # what that can mean: possible upsides and risks, no prescriptions
    basis: str                       # measured | genes | fungi | names
    confidence: str                  # high | medium | low
    evidence: list[str]              # the numbers and rules behind the finding
    carrier_terms: list[str] = []    # term ids to look up in FunctionProfile.carriers ("Who may carry it")
    section: str = "microbes"        # measured | microbes | life: where the card sits on the page
    who: list[str] = []              # who carries it, from the genes' closest known relatives (gene phylogeny)
    context: str | None = None       # one line placing the sample among the well-sequenced NEON farm soils


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


class FunctionProfile(BaseModel):
    sample_id: str
    plot_id: str
    date: dt.date
    n_genes: int
    deep_enough: bool
    cards: list[DecisionCard]
    pathways: list[Pathway]
    fungi: Fungi | None
    groups: list[FunctionGroup]
    measured: Measured | None
    notes: list[str]
    carriers: list[Carriers]         # one per CARRIER_TERMS entry, that order; [] when taxa_lineage is missing


# ---------------------------------------------------------------- data
def _has(name: str) -> bool:
    return (core.PROCESSED / f"{name}.parquet").exists()


def _sample_id(key: str) -> str:
    return "mg-" + key.replace("nmdc:", "")


def _metagenomes() -> pd.DataFrame:
    mg = core.table("metagenomes").copy()
    keys = set(core.table("ko_panel")["metagenome_key"])
    mg = mg[mg["metagenome_key"].isin(keys)].copy()
    mg["sample_id"] = mg["metagenome_key"].map(_sample_id)
    mg["date"] = pd.to_datetime(mg["date"]).dt.date
    mg["n_ko_genes"] = mg["n_ko_genes"].fillna(0).astype(int)
    mg["ko_depth_ok"] = mg["ko_depth_ok"].fillna(False).astype(bool)
    return mg.sort_values("date")


def _nearest(df: pd.DataFrame, plot_id: str, date: dt.date, date_col: str) -> pd.Series | None:
    d = df[df["plotID"] == plot_id].copy()
    if d.empty:
        return None
    d["_gap"] = (pd.to_datetime(d[date_col]) - pd.Timestamp(date)).abs().dt.days
    d = d[d["_gap"] <= MATCH_DAYS].sort_values("_gap")
    return None if d.empty else d.iloc[0]


def _measured(plot_id: str, date: dt.date) -> Measured | None:
    n = _nearest(core.table("neon_inorganic_n"), plot_id, date, "collectDate") if _has("neon_inorganic_n") else None
    c = _nearest(core.table("neon_chem"), plot_id, date, "collectDate") if _has("neon_chem") else None
    if n is None and c is None:
        return None
    num = lambda s, k: None if s is None or k not in s or pd.isna(s[k]) else round(float(s[k]), 3)  # noqa: E731
    when = pd.to_datetime((n if n is not None else c)["collectDate"]).date()
    return Measured(date=when, ammonium_n_mgkg=num(n, "ammonium_n_mgkg"), nitrate_n_mgkg=num(n, "nitrate_n_mgkg"),
                    net_n_min_mgkg_d=num(n, "net_n_min_mgkg_d"), net_nitrif_mgkg_d=num(n, "net_nitrif_mgkg_d"),
                    ph_water=num(c, "ph_water"), organic_c_pct=num(c, "organic_c_pct"),
                    total_n_pct=num(c, "total_n_pct"), cn_ratio=num(c, "cn_ratio"), soil_moisture=num(c, "soil_moisture"))


def _status(copies: int, deep: bool) -> str:
    return "found" if copies >= MIN_COUNT else "trace" if copies > 0 else "not_found" if deep else "too_few_genes"


def _pathways(copies: dict[str, int], deep: bool) -> list[Pathway]:
    out = []
    for name, module, steps, note in PATHWAYS:
        st = [PathwayStep(step=s, genes=g, copies=sum(copies.get(x, 0) for x in g),
                          status=_status(sum(copies.get(x, 0) for x in g), deep)) for s, g in steps]
        out.append(Pathway(name=name, kegg_module=module, steps=st, note=note,
                           complete=all(s.status == "found" for s in st), term_id=PATHWAY_TERM.get(name)))
    return out


def _fungi(r) -> Fungi | None:
    """Fungal genera of the same soil cores (else nearest NEON visit to the plot), grouped by FUNGuild role."""
    same, g = False, None
    if _has("joined_fungi_genus"):
        j = core.table("joined_fungi_genus")
        j = j[j["metagenome_key"] == r.metagenome_key]
        if len(j):
            same, g, date = True, j[["genus", "rel_abund_pct"]], r.date
    if g is None and _has("its_genus"):
        its = core.table("its_genus")
        near = _nearest(its.drop_duplicates(["plotID", "collectDate"]), r.plotID, r.date, "collectDate")
        if near is None:
            return None
        g = its[(its["plotID"] == r.plotID) & (its["collectDate"] == near["collectDate"])][["genus", "rel_abund_pct"]]
        date = pd.to_datetime(near["collectDate"]).date()
    if g is None or g.empty:
        return None
    reads = None
    if _has("its_genus"):
        its = core.table("its_genus")
        hit = its[(its["plotID"] == r.plotID) & (pd.to_datetime(its["collectDate"]).dt.date == date)]
        reads = int(hit["total_reads"].iloc[0]) if len(hit) else None
    g = g[g["rel_abund_pct"] > 0]
    unnamed = g["genus"].str.startswith("unclassified") | g["genus"].str.contains("Incertae_sedis", regex=False)
    named = g[~unnamed].copy()                          # placeholders count as "no genus name", as in the microbes view
    total = float(named["rel_abund_pct"].sum())
    if total <= 0:
        return None
    guilds = core.table("fungal_guilds").set_index("genus") if _has("fungal_guilds") else pd.DataFrame()
    named["role"] = named["genus"].map(guilds["category"]) if len(guilds) else "no_guild"
    named["role"] = named["role"].fillna("no_guild")
    named["pct"] = 100 * named["rel_abund_pct"] / total
    onto = microbe_roles.load_ontology().set_index("term_id")["label"]
    roles = []
    for role, sub in named.groupby("role"):
        term = microbe_roles.FUNGUILD_CATEGORY_TERM.get(role)
        sub = sub.sort_values("pct", ascending=False)
        roles.append(FungalRole(role=role, label=onto[term] if term else FUNGAL_ROLE.get(role, role), term_id=term,
                                pct=round(float(sub["pct"].sum()), 2),
                                top=[f"{x.genus} {x.pct:.1f}%" if x.pct >= 0.05 else f"{x.genus} <0.1%"
                                     for x in sub.head(4).itertuples()]))
    roles.sort(key=lambda x: -x.pct)
    return Fungi(date=date, same_cores=same, reads=reads, named_pct=round(total / float(g["rel_abund_pct"].sum()) * 100, 1),
                 roles=roles)


# ---------------------------------------------------------------- named carriers
def _gene_status(onto_row, groups: dict[str, str]) -> str:
    """Best gene status over the term's ko_groups: found > trace > not_found > too_few_genes."""
    got = [groups[g] for g in onto_row.ko_groups if g in groups]
    return min(got, key=GENE_STATUS_ORDER.index) if got else "too_few_genes"


def _agreement(term_id: str, genes: str, pct: float) -> tuple[str, str]:
    """Do the genes and the named genera tell the same story? (docs/microbe_roles.md 6.3 table)"""
    names = pct >= CARRIER_MIN_PCT
    if genes == "too_few_genes":
        kind = "unknown"
    elif genes in ("found", "trace"):
        kind = "both" if names else "genes_only"
    else:
        kind = "names_only" if names else "neither"
    text = AGREEMENT_TEXT[kind]
    if genes == "trace":    # the cards call a trace "not found"; say so instead of "Genes found"
        text = ("Only a trace of the genes (rare genes are often missed when DNA is assembled), but genera known to "
                "carry them are present." if names else
                "Only a trace of the genes, and no known carrier by name.")
    if term_id == "antibiotic_producer":
        text += " The marker genes (DAPG, hydrogen cyanide) cover only some antimicrobial producers."
    return kind, text


def _carriers(ru: microbe_roles.RollUp, groups: list[FunctionGroup]) -> list[Carriers]:
    """Genera of this metagenome that are known for each gene-backed role, next to what the genes say."""
    status = {g.group: g.status for g in groups}
    terms = ru.terms.set_index("term_id", drop=False)
    out = []
    for tid in CARRIER_TERMS:
        t = terms.loc[tid]
        genes = _gene_status(t, status)
        agreement, text = _agreement(tid, genes, float(t["pct"]))
        top = ru.term_genera[ru.term_genera["term_id"] == tid].head(CARRIER_TOP)
        out.append(Carriers(
            term_id=tid, label=t["label"], ko_groups=list(t["ko_groups"]), pct=round(float(t["pct"]), 2),
            n_genera=int(t["n_genera"]), genes=genes, agreement=agreement, agreement_text=text,
            top=[CarrierGenus(name=x.name, pct=round(float(x.pct), 4), term_id=x.row_term_id,
                              confidence=x.confidence, evidence=x.evidence, species_examples=list(x.species_examples),
                              description=x.description if isinstance(x.description, str) else None)
                 for x in top.itertuples()]))
    return out


def _bacteria_rollup(r) -> tuple[microbe_roles.RollUp | None, int]:
    """Genus roll-up of the metagenome's bacteria + archaea (as in the Soil microbes tab) and its classified reads."""
    if not _has("taxa_lineage"):
        return None, 0
    lin = core.table("taxa_lineage")
    reads = int(lin[(lin["metagenome_key"] == r.metagenome_key) & (lin["rank"] == "domain")]["reads"].sum())
    taxa = _bacteria_taxa(r.metagenome_key, "genus")
    return microbe_roles.roll_up(taxa, "bacteria", ann=microbe_roles.load_annotations(core.PROCESSED)), reads


# ---------------------------------------------------------------- KEGG modules and gene phylogeny
def _module_state(key: str) -> tuple[pd.DataFrame, int] | None:
    """This metagenome's KEGG module completeness (all its KOs) with, per module, in how many of the *other*
    well-sequenced metagenomes it is complete. None without scripts/19 output."""
    if not (_has("kegg_module_completeness") and _has("kegg_modules")):
        return None
    comp, mods = core.table("kegg_module_completeness"), core.table("kegg_modules")
    mine = comp[comp["metagenome_key"] == key].merge(
        mods[["module", "name", "class_a", "class_b", "class_c", "definition"]], on="module")
    if mine.empty:
        return None
    mg = _metagenomes()
    others = set(mg.loc[mg["ko_depth_ok"], "metagenome_key"]) - {key}
    ref = comp[comp["metagenome_key"].isin(others)]
    full = ref.assign(full=ref["completeness"] == 1).groupby("module")["full"].sum()
    mine = mine.assign(ref_complete=mine["module"].map(full).fillna(0).astype(int))
    return mine, len(others)


def _plain(name: str) -> str:
    """'Denitrification, nitrate => nitrogen' -> 'Denitrification'."""
    return name.split(",")[0].strip()


def _who(key: str, kos: list[str]) -> list[str]:
    """Who carries these genes: the phyla of their closest known relatives (>= WHO_MIN_SHARE % of the genes), plus a
    genus when the match is close. [] without scripts/20 output or with too few genes."""
    if not _has("ko_taxa"):
        return []
    t = core.table("ko_taxa")
    x = t[(t["metagenome_key"] == key) & t["ko"].isin(kos)]
    total = float(x["n_genes"].sum())
    if total < MIN_COUNT:
        return []
    out = []
    ph = x.groupby("phylum")["n_genes"].sum().sort_values(ascending=False)
    for phylum, n in ph.head(3).items():
        share = 100 * n / total
        if share >= WHO_MIN_SHARE and phylum:
            out.append(f"{FRIENDLY_PHYLUM.get(phylum, phylum)} ({share:.0f}%)")
    g = x.groupby("genus").agg(n=("n_genes", "sum"), ident=("identity_median", "median"))
    g = g[(100 * g["n"] / total >= WHO_CLOSE_SHARE) & (g["ident"] >= WHO_CLOSE_IDENTITY)]
    out += [f"{genus}, close match ({100 * r.n / total:.0f}%)" for genus, r in g.sort_values("n", ascending=False).head(2).iterrows()
            if genus and not genus.startswith("unclassified")]
    return out


def _ammonia_oxidiser_share(key: str) -> float | None:
    """% of the ambiguous amoA/pmoA genes (K10944) whose closest relatives are known ammonia oxidisers."""
    if not _has("ko_taxa"):
        return None
    t = core.table("ko_taxa")
    x = t[(t["metagenome_key"] == key) & (t["ko"] == "K10944")]
    total = float(x["n_genes"].sum())
    if total < MIN_COUNT:
        return None
    hit = x[x["phylum"].isin(AMMONIA_OXIDISERS) | x["family"].isin(AMMONIA_OXIDISER_FAMILIES)]["n_genes"].sum()
    return 100 * float(hit) / total


def _methanotroph_genes(key: str) -> int:
    """Methane-oxidation genes that really point to methanotrophs: soluble MMO, or particulate MMO (K10944-6,
    shared with ammonia oxidisers) whose closest relatives are methanotroph families."""
    if not _has("ko_taxa"):
        return 0
    t = core.table("ko_taxa")
    x = t[t["metagenome_key"] == key]
    smmo = x[x["ko"].isin(SOLUBLE_MMO)]["n_genes"].sum()
    pmmo = x[x["ko"].isin(["K10944", "K10945", "K10946"]) & x["family"].isin(METHANOTROPH_FAMILIES)]["n_genes"].sum()
    return int(smmo + pmmo)


def _per_genome_reference(key: str, kos: list[str]) -> tuple[float, list[float]] | None:
    """Copies of these KOs per genome (marker mean) here and in each other well-sequenced metagenome."""
    if not _has("ko_counts_all"):
        return None
    mg = _metagenomes().set_index("metagenome_key")
    deep = mg[mg["ko_depth_ok"] & (mg["marker_mean"] > 0)]
    if key not in deep.index:
        return None
    k = core.table("ko_counts_all")
    per = (k[k["ko"].isin(kos) & k["metagenome_key"].isin(deep.index)].groupby("metagenome_key")["count"].sum()
           .reindex(deep.index, fill_value=0) / deep["marker_mean"])
    return float(per[key]), [float(v) for v in per.drop(key)]


def _compare(value: float, others: list[float]) -> str:
    """'more than', 'fewer than' or 'about as many as' the others (outside / inside their range)."""
    if value > max(others):
        return "more than"
    if value < min(others):
        return "fewer than"
    return "about as many as"


def _count_range(counts: list[int]) -> str:
    lo, hi = int(min(counts)), int(max(counts))
    return "none" if hi == 0 else str(lo) if lo == hi else f"{lo}-{hi}"


def _module_kos(definition: str) -> list[str]:
    return re.findall(r"K\d{5}", definition or "")


def _ref_line(row, n_ref: int, what: str = "complete") -> str | None:
    if row is None or n_ref < 1:
        return None
    return f"{what.capitalize()} in {int(row.ref_complete)} of the {n_ref} other well-sequenced NEON farm soils."


# ---------------------------------------------------------------- cards
def _p(v: float) -> str:
    """Share for text: '<1%' for small non-zero shares, so 'present' and '0%' never meet."""
    return "0%" if v <= 0 else "<1%" if v < 0.5 else f"{v:.0f}%"


def _band(value: float, bands: list) -> tuple[str, str, str]:
    return next((name, kind, text) for top, name, kind, text in bands if value < top)


def _abbrev(species: str) -> str:
    """'Streptomyces scabies' -> 'S. scabies'."""
    genus, _, rest = species.partition(" ")
    return f"{genus[:1]}. {rest}" if rest else species


def _bacteria_pathogen_card(ru: microbe_roles.RollUp, reads: int) -> DecisionCard:
    """Named bacterial genera with plant pathogens, from the microbe-role roll-up (docs/microbe_roles.md 6.3).
    Genera whose species are *mostly* pathogens (evidence well_known_genus) may colour the card; genera where
    only some species are pathogens (Pseudomonas, Streptomyces) never do."""
    imp = lambda kind, text: Implication(kind=kind, text=text)  # noqa: E731
    label = dict(zip(ru.terms["term_id"], ru.terms["label"]))
    path = ru.term_genera[ru.term_genera["term_id"] == "plant_pathogen"]
    total = float(path["pct"].sum())
    mostly = path[path["evidence"] == "well_known_genus"]
    some = path[path["evidence"] != "well_known_genus"]
    mostly_pct = float(mostly["pct"].sum())
    flagged = mostly[mostly["pct"] >= BACTERIA_PATHOGEN_GENUS_FLAG].head(1)
    flag = f"{flagged.iloc[0]['name']} alone is {flagged.iloc[0]['pct']:.1f}% of bacterial DNA" if len(flagged) else None
    listed = path.head(4)                                     # term_genera is sorted largest first
    names = lambda df: ", ".join(f"{x.name} {_p(x.pct)}" for x in df.head(3).itertuples())  # noqa: E731
    if path.empty:
        headline, finding = ("No genera known for plant pathogens",
                             "No genus with a known plant pathogen was found among the classified bacterial DNA.")
    else:
        headline = (f"{_p(total)} from genera that include plant pathogens · "
                    f"{_p(mostly_pct)} from mostly pathogenic genera")
        parts = [f"{x.name} {_p(x.pct)}" + (f" ({_abbrev(x.species_examples[0])})" if x.species_examples else "")
                 for x in listed.itertuples()]
        finding = (f"Of the classified bacterial DNA, {_p(total)} is from genera that include plant pathogens: "
                   + ", ".join(parts) + ".")
    imps = []
    if len(mostly):
        imps.append(imp("risk", f"Genera whose species are mostly plant pathogens are present ({names(mostly)}). "
                                "Disease also needs a susceptible crop and suitable weather."))
    if len(some):
        imps.append(imp("neutral", f"Most of this share is from genera where only some species cause disease "
                                   f"({names(some)}); harmless relatives usually dominate in soil."))
    imps.append(imp("neutral", "Names come from short DNA reads matched to reference genomes: small shares of "
                               "well-known pathogen genera can be misassigned reads."))
    ev = [f"{x.name} {x.pct:.2f}%: {label.get(x.row_term_id, x.row_term_id)}, {x.confidence} confidence, {x.source}"
          + (f" ({'; '.join(x.species_examples[:2])})" if x.species_examples else "") for x in listed.itertuples()]
    ev.append(f"Coloured when one genus whose species are mostly plant pathogens makes up "
              f"{BACTERIA_PATHOGEN_GENUS_FLAG:.0f}% or more of the classified bacterial DNA.")
    ev.append("Roles from the microbe role annotation (AI, with a second AI review of harmful genera), genus level.")
    if reads < MIN_BACTERIA_READS:
        ev.append("Few bacterial reads: small shares may be noise.")
    return DecisionCard(card="bacteria_pathogens", title="Bacteria that include plant pathogens",
                        status="notice" if flag else "info", headline=headline, flag=flag, finding=finding,
                        implications=imps, basis="names", confidence="low", evidence=ev, carrier_terms=[])


SECTION = {"n_now": "measured", "n_release": "measured", "soil": "measured", "fungi": "life",
           "bacteria_pathogens": "life", "root_health": "life", "copper": "life"}   # everything else: microbes


def _cards(copies: dict[str, int], pathways: list[Pathway], fungi: Fungi | None, m: Measured | None,
           deep: bool, guilds: pd.DataFrame, bacteria: microbe_roles.RollUp | None = None,
           bacteria_reads: int = 0, key: str | None = None) -> list[DecisionCard]:
    """The cards of one sample; `bacteria` is the sample's genus roll-up (None without genus-level data); `key`
    (the metagenome) adds who carries each function and the KEGG-module cards when scripts 19/20 have run."""
    cards = _gene_cards(copies, pathways, fungi, m, deep, guilds, bacteria, bacteria_reads)
    for c in cards:
        c.carrier_terms = CARD_CARRIER_TERMS.get(c.card, [])
        c.section = SECTION.get(c.card, "microbes")
    if key and deep:
        cards += _module_cards(cards, key, m)
    return cards


def _module_cards(cards: list[DecisionCard], key: str, m: Measured | None) -> list[DecisionCard]:
    """Use all KEGG genes: who carries the nitrogen, phosphorus and root-health functions (gene phylogeny), how
    common each pathway is among the other well-sequenced NEON farm soils, and three cards built from KEGG modules."""
    U, N = "upside", "neutral"
    imp = lambda kind, text: Implication(kind=kind, text=text)  # noqa: E731
    by = {c.card: c for c in cards}
    state = _module_state(key)
    mods, n_ref = state if state else (pd.DataFrame(), 0)
    row = lambda mid: next(iter(mods[mods["module"] == mid].itertuples()), None) if len(mods) else None  # noqa: E731
    complete = lambda mid: bool(row(mid) is not None and row(mid).completeness == 1)  # noqa: E731

    # ---- nitrogen: plain summary from the modules, who does each step, reference
    if "nitrogen" in by and len(mods):
        c = by["nitrogen"]
        can = [txt for mid, txt in (("M00528", "turn ammonium into nitrate"),
                                    ("M00529", "turn nitrate back into nitrogen gas"),
                                    ("M00530", "keep nitrate in the soil as ammonium")) if complete(mid)]
        c.headline = ("Microbes here can " + ", ".join(can[:-1]) + (" and " if len(can) > 1 else "") + can[-1]
                      if can else "Few complete nitrogen pathways") + (
            "; no sign of nitrogen fixation." if not complete("M00175") else "; some can fix nitrogen.")
        aob = _ammonia_oxidiser_share(key)
        if aob is not None:
            c.implications.insert(0, imp(U if aob >= 50 else N,
                f"About {aob:.0f}% of the ammonia-oxidation genes come from known ammonia oxidisers (mostly soil "
                "archaea), so nitrification is real here, not only a look-alike enzyme."
                if aob >= 50 else
                f"Only about {aob:.0f}% of the ammonia-oxidation genes come from known ammonia oxidisers; the rest "
                "are similar enzymes of other bacteria."))
            c.implications = [i for i in c.implications if "(if these genes are from ammonia rather than methane" not in i.text]
        c.who = [f"N2O made by: {', '.join(_who(key, ['K04561'])[:2]) or 'too few genes'}",
                 f"N2O removed by: {', '.join(_who(key, ['K00376'])[:3]) or 'too few genes'}",
                 f"Ammonium to nitrate: {', '.join(_who(key, ['K10944'])[:2]) or 'too few genes'}"]
        c.context = _ref_line(row("M00529"), n_ref, "full denitrification")
    if "p_release" in by:
        by["p_release"].who = _who(key, ["K01113", "K01077", "K00117", "K06137"])
    if "copper" in by:
        c = by["copper"]
        c.who = _who(key, COPPER_RESISTANCE)
        ref = _per_genome_reference(key, COPPER_RESISTANCE)
        if ref and len(ref[1]) >= MIN_REFERENCE:
            value, others = ref
            c.headline = (f"Some soil bacteria carry copper-resistance genes, {_compare(value, others)} in the other "
                          "well-sequenced farm soils.")
            c.context = (f"About {value:.1f} copies per bacterial genome here; {min(others):.1f}-{max(others):.1f} in "
                         f"the {len(others)} other well-sequenced NEON farm soils.")
            if _compare(value, others) == "more than":
                c.implications.insert(0, imp(N, "More copper-resistance genes than in the other farm soils can point to "
                                                "copper building up (copper fungicides, manure), but is not proof of it."))
    if "root_health" in by:
        by["root_health"].who = [f"Stress relief (ACC deaminase): {', '.join(_who(key, ['K01505'])) or 'too few genes'}"]
    if not len(mods):
        return []
    out: list[DecisionCard] = []
    pathways = mods[mods["class_a"] == "Pathway modules"]

    # ---- breakdown of aromatic and man-made compounds (KEGG: Xenobiotics biodegradation)
    xen = pathways[pathways["class_b"] == "Xenobiotics biodegradation"]
    done = xen[xen["completeness"] == 1]
    if len(xen):
        ref = core.table("kegg_module_completeness")
        mg = _metagenomes()
        others = set(mg.loc[mg["ko_depth_ok"], "metagenome_key"]) - {key}
        per_other = (ref[ref["metagenome_key"].isin(others) & ref["module"].isin(xen["module"]) & (ref["completeness"] == 1)]
                     .groupby("metagenome_key").size().reindex(list(others), fill_value=0))
        names = [_plain(x) for x in done.sort_values("name")["name"]]
        imps = [imp(U, "These are the routes soil bacteria use to break down plant lignin products and some pesticide, "
                       "fuel and plastic residues.")] if len(done) else []
        for mid in ("M00623", "M00636"):
            if complete(mid):
                imps.append(imp(U, f"One of them {MODULE_NOTES[mid][1]}."))
                break
        partial = xen[(xen["completeness"] >= 0.5) & (xen["completeness"] < 1)]
        if len(partial):
            imps.append(imp(N, "Partly present: " + ", ".join(_plain(x) for x in partial["name"].head(4)) + "."))
        out.append(DecisionCard(
            card="breakdown", title="Breakdown of aromatic and man-made compounds", status="info", flag=None,
            headline=(f"Microbes here can fully break down {len(done)} kinds of aromatic compound."
                      if len(done) else "No complete breakdown route for aromatic compounds found."),
            finding="Complete: " + (", ".join(names) if names else "none") + ".",
            implications=imps, basis="genes", confidence="low", section="microbes",
            context=(f"The other {len(per_other)} well-sequenced NEON farm soils have {int(per_other.median())} "
                     f"(range {int(per_other.min())}-{int(per_other.max())})." if len(per_other) else None),
            evidence=[f"KEGG modules in 'Xenobiotics biodegradation': {len(done)} complete, {len(partial)} at 50% or more, "
                      f"of {len(xen)}.", "A module counts as complete when every step has at least one gene copy."]))

    # ---- gases: methane and sulfur
    meth_module = complete("M00174")
    methanotrophs = _methanotroph_genes(key)
    meth_ox = meth_module and methanotrophs >= MIN_COUNT
    meth_made = [m_ for m_ in ("M00567", "M00357", "M00356", "M00563") if complete(m_)]
    sox = complete("M00595")
    imps = [imp(U, "Microbes here can consume methane, a greenhouse gas.") if meth_ox else
            imp(N, "The methane-oxidation genes found come from ammonia oxidisers, not methane eaters: no clear sign "
                   "of methane-consuming microbes.") if meth_module else
            imp(N, "No complete methane-consuming route found.")]
    imps.append(imp(N, "No complete route for making methane, as expected in well-aerated soil.") if not meth_made else
                imp(N, "A complete methane-making route is present: such microbes work in waterlogged, oxygen-poor spots."))
    if sox:
        imps.append(imp(U, "Microbes can turn reduced sulfur into sulfate, the form crops take up."))
    out.append(DecisionCard(
        card="gases", title="Methane and sulfur", status="info", flag=None,
        headline=("Can consume methane" if meth_ox else "No clear methane consumers") + (
            "; can turn sulfur into sulfate" if sox else "") + ".",
        finding="KEGG modules: methane oxidation " + ("complete" if meth_module else "incomplete")
                + (f" ({methanotrophs} genes from methanotrophs)" if meth_module else "")
                + f"; methane production {'complete' if meth_made else 'incomplete'}; sulfur oxidation (SOX) "
                + ("complete" if sox else "incomplete") + ".",
        implications=imps, basis="genes", confidence="low", section="microbes",
        who=[],
        context=None,
        evidence=["KEGG M00174 (methane oxidation), M00567/M00357/M00356/M00563 (methanogenesis), M00595 (SOX).",
                  "Methane eaters are counted only from soluble methane monooxygenase (mmoX-C) or particulate monooxygenase "
                  "genes whose closest relatives are methanotroph families: the same particulate genes also belong to "
                  "ammonia oxidisers in this annotation."]))

    # ---- what is unusual compared with the other well-sequenced farm soils
    if n_ref >= MIN_REFERENCE:
        eco = pathways[pathways["class_b"].isin(UNUSUAL_CLASSES)]
        rare = eco[(eco["completeness"] == 1) & (eco["ref_complete"] <= UNUSUAL_RARE)]
        missing = eco[(eco["completeness"] < 1) & (eco["ref_complete"] >= n_ref - 1)]
        # modules with a known plain meaning first, then the rarest
        prio = {mid: i for i, mid in enumerate(MODULE_NOTES)}           # MODULE_NOTES order = relevance
        rare = (rare.assign(_prio=rare["module"].map(prio).fillna(len(prio)))
                .sort_values(["_prio", "ref_complete", "name"]))
        dup = eco["name"].map(_plain).duplicated(keep=False)
        label = lambda r: (r.name if dup.get(r.Index, False) else _plain(r.name)) + (  # noqa: E731
            f" ({MODULE_NOTES[r.module][1]})" if r.module in MODULE_NOTES else "")
        noted = [r for r in rare.itertuples() if r.module in MODULE_NOTES][:2]
        rest = [r for r in rare.itertuples() if r not in noted]
        if noted:
            headline = ("Microbes here can make " + " and ".join(f"{MODULE_NOTES[r.module][0]} "
                                                               f"({MODULE_NOTES[r.module][1]})" for r in noted)
                        + ", which few of the other farm soils can.")
        elif len(rare):
            headline = "A few less common pathways, none with a clear meaning for crops."
        elif len(missing):
            headline = "Nothing extra; a few pathways common elsewhere look incomplete here."
        else:
            headline = "Nothing stands out against the other farm soils."
        imps = []
        if rest:
            imps.append(imp(N, ("Also uncommon: " if noted else "Uncommon here: ")
                            + "; ".join(label(r) for r in rest[:5]) + "."))
        if len(missing):
            imps.append(imp(N, "Usual elsewhere but incomplete here: "
                               + "; ".join(label(r) for r in missing.head(5).itertuples()) + "."))
        if len(rare) or len(missing):
            imps.append(imp(N, "Deeper-sequenced samples complete more pathways, so part of a difference can be depth."))
        who = [f"{MODULE_NOTES[r.module][0][:1].upper()}{MODULE_NOTES[r.module][0][1:]}: "
               f"{', '.join(_who(key, _module_kos(r.definition))[:2]) or 'too few genes to tell'}" for r in noted]
        shown = noted or list(rare.itertuples())
        out.append(DecisionCard(
            card="unusual", title="Unusual for these soils", status="info", flag=None,
            headline=headline, who=who,
            finding=f"Pathways for energy and nutrient cycling, breakdown of compounds and natural products (antibiotics, "
                    f"siderophores, pigments), compared with the {n_ref} other well-sequenced NEON farm soils: complete "
                    f"here but in at most {UNUSUAL_RARE} of them, or incomplete here but complete in at least {n_ref - 1}.",
            implications=imps, basis="genes", confidence="low", section="microbes",
            context=(f"Complete in {_count_range([r.ref_complete for r in shown])} of the {n_ref} other well-sequenced "
                     "NEON farm soils." if shown else f"Compared with {n_ref} other well-sequenced NEON farm soils."),
            evidence=[f"{r.module} {r.name}: complete here, in {r.ref_complete} of {n_ref} others"
                      for r in rare.head(8).itertuples()]
                     + [f"{r.module} {r.name}: {r.steps_found}/{r.n_steps} steps here, complete in {r.ref_complete} of "
                        f"{n_ref} others" for r in missing.head(8).itertuples()]
                     + ["A small reference: differences can also come from sequencing depth or chance."]))
    return out


def _gene_cards(copies: dict[str, int], pathways: list[Pathway], fungi: Fungi | None, m: Measured | None,
                deep: bool, guilds: pd.DataFrame, bacteria: microbe_roles.RollUp | None,
                bacteria_reads: int) -> list[DecisionCard]:
    U, R, N = "upside", "risk", "neutral"
    imp = lambda kind, text: Implication(kind=kind, text=text)  # noqa: E731
    c = lambda *genes: sum(copies.get(x, 0) for x in genes)  # noqa: E731
    P = {p.name: p for p in pathways}
    cards: list[DecisionCard] = []

    # ---- measured: nitrogen available now (soil nitrate test)
    if m and m.nitrate_n_mgkg is not None:
        no3 = m.nitrate_n_mgkg
        st = "good" if no3 >= NITRATE_ENOUGH else "watch" if no3 >= NITRATE_LOW else "act"
        cards.append(DecisionCard(
            card="n_now", title="Nitrogen available now", status=st,
            headline=f"{no3:.1f} mg/kg nitrate · {m.ammonium_n_mgkg or 0:.1f} mg/kg ammonium",
            flag=None if st == "good" else f"Below the {NITRATE_ENOUGH:.0f} mg/kg soil-test level for corn"
            + (f" (and below {NITRATE_LOW:.0f})" if st == "act" else ""),
            finding=f"Soil nitrate is {no3:.1f} mg N/kg (ammonium {m.ammonium_n_mgkg or 0:.1f}).",
            implications=[
                imp(U, "Above the 25 mg/kg level of the soil nitrate test: for corn, the soil alone usually covers "
                       "the rest of the season's nitrogen.") if st == "good" else
                imp(R, "Between 10 and 25 mg/kg: for corn, the soil alone is usually not enough for the rest of the "
                       "season.") if st == "watch" else
                imp(R, "Below 10 mg/kg: for corn, the soil supplies little of the nitrogen the crop still needs."),
                imp(R if no3 >= NITRATE_LOW else N, "Nitrate moves with water: heavy rain can wash part of it below the "
                                                    "roots." if no3 >= NITRATE_LOW else
                    "Little nitrate means little to wash out with heavy rain."),
            ],
            basis="measured", confidence="medium",
            evidence=[f"Nitrate {no3:.2f} and ammonium {m.ammonium_n_mgkg or 0:.2f} mg N/kg, {m.date}",
                      "Rule: late-spring soil nitrate test for corn (25 and 10 mg/kg; 0-30 cm, corn 15-30 cm tall). "
                      "NEON's timing and depth are close to, not exactly, that protocol, and the test is calibrated "
                      "for corn, not for other crops."]))
    else:
        cards.append(DecisionCard(card="n_now", title="Nitrogen available now", status="unknown",
                                  headline="Not measured at this visit", flag=None, finding="NEON did not measure soil nitrate within a week of this sample.",
                                  implications=[], basis="measured", confidence="low", evidence=[]))

    # ---- measured: nitrogen from organic matter (net mineralisation, C:N)
    if m and (m.net_n_min_mgkg_d is not None or m.cn_ratio is not None):
        nm, cn = m.net_n_min_mgkg_d, m.cn_ratio
        locking = (nm is not None and nm < 0) or (cn is not None and cn > CN_IMMOBILISE)
        parts = ([f"net mineralisation {nm:+.2f} mg N/kg/day"] if nm is not None else []) + (
            [f"C:N {cn:.1f}"] if cn is not None else [])
        cards.append(DecisionCard(
            card="n_release", title="Nitrogen from organic matter", status="watch" if locking else "good",
            headline="Microbes are locking nitrogen up" if locking else "Organic matter is releasing nitrogen",
            flag=("Negative net mineralisation" if nm is not None and nm < 0 else f"C:N above {CN_IMMOBILISE:.0f}")
            if locking else None,
            finding=("Microbes were taking nitrogen up rather than releasing it" if locking else
                     "Microbes were releasing nitrogen from organic matter") + f" ({', '.join(parts)}).",
            implications=[imp(R, "While microbes lock nitrogen up, little of the crop's nitrogen comes from the soil "
                                 "itself; the crop depends more on fertiliser or manure in that period.")
                          if locking else
                          imp(U, "Organic matter is turning into plant-available nitrogen: part of the crop's need is "
                                 "met by the soil itself."),
                          imp(N, "This is one incubation at one visit: it changes with season, moisture and fresh "
                                 "residues.")],
            basis="measured", confidence="medium",
            evidence=parts + ["Rule: negative net mineralisation, or C:N above 20, means nitrogen lock-up."]))

    # ---- measured: soil character against textbook ranges
    if m and (m.ph_water is not None or m.organic_c_pct is not None):
        facts, imps, risks, short = [], [], [], []
        if m.ph_water is not None:
            name, kind, text = _band(m.ph_water, PH_BANDS)
            facts.append(f"pH {m.ph_water:.1f} ({name})")
            short.append(f"pH {m.ph_water:.1f}")
            imps.append(imp(kind, f"pH {m.ph_water:.1f}: {text}."))
            if kind == "risk":
                risks.append(f"pH {m.ph_water:.1f} is {name}")
        if m.organic_c_pct is not None:
            name, kind, text = _band(m.organic_c_pct, OC_BANDS)
            facts.append(f"organic carbon {m.organic_c_pct:.2f}% ({name})")
            short.append(f"organic carbon {m.organic_c_pct:.2f}% ({name})")
            imps.append(imp(kind, f"Organic carbon {m.organic_c_pct:.2f}%: {text}."))
            if kind == "risk":
                risks.append(f"organic carbon is {name}")
        if m.cn_ratio is not None and m.cn_ratio <= CN_IMMOBILISE:
            imps.append(imp(N, f"C:N {m.cn_ratio:.1f} is usual for arable soil: residues break down without locking "
                               "much nitrogen up."))
        cards.append(DecisionCard(
            card="soil", title="Soil character", status="watch" if risks else "info", headline=" · ".join(short),
            flag=("; ".join(risks)[:1].upper() + "; ".join(risks)[1:]) if risks else None, finding="Measured: " + ", ".join(facts) + ".",
            implications=imps, basis="measured", confidence="medium",
            evidence=["Ranges for arable topsoils from general soil fertility texts (pH 6-7 most nutrients "
                      "available; organic carbon below 1% low, above 2% high). Approximate, not crop-specific."]))

    # ---- fungi (ITS, FUNGuild roles) - independent of metagenome depth
    if fungi:
        R_ = {x.role: x for x in fungi.roles}
        share = lambda role: R_[role].pct if role in R_ else 0.0  # noqa: E731
        top_role = fungi.roles[0]
        finding = (f"Of the fungal DNA with a genus name, {_p(share('saprotroph'))} is from decomposers, "
                   f"{_p(share('plant_pathogen'))} from genera that include plant pathogens, "
                   f"{_p(share('arbuscular_mycorrhizal') + share('other_mycorrhizal'))} from mycorrhizal fungi and "
                   f"{_p(share('fungal_parasite'))} from parasites of other fungi.")
        imps = []
        if "plant_pathogen" in R_:
            imps.append(imp(R, f"Genera that include crop pathogens are present ({', '.join(R_['plant_pathogen'].top[:3])}). "
                               "Disease also needs a susceptible crop and suitable weather, and these genera hold "
                               "harmless species too."))
        enemies = []
        if len(guilds):
            fp = guilds[guilds["can_parasitise_fungi"]].index
            for role in fungi.roles:
                enemies += [t for t in role.top if t.split(" ")[0] in fp]
        if enemies:
            imps.append(imp(U, f"Fungi that attack other fungi, some of them pathogens, are present ({', '.join(enemies[:3])})."))
        if share("arbuscular_mycorrhizal") > 0:
            imps.append(imp(U, f"Arbuscular mycorrhizal fungi are present ({_p(share('arbuscular_mycorrhizal'))} of fungal "
                               "DNA, an under-count with this method): they extend roots' reach for phosphorus and water."))
        else:
            imps.append(imp(N, "No arbuscular mycorrhizal fungi detected; the ITS method misses most of them, so this "
                               "says little."))
        if top_role.role == "saprotroph":
            imps.append(imp(U, "Decomposers dominate: crop residues and organic matter are being broken down, "
                               "releasing nutrients."))
        if share("other_mycorrhizal") >= 5:
            imps.append(imp(N, f"{share('other_mycorrhizal'):.0f}% of fungal DNA is from fungi that partner with trees: "
                               "unusual for a field, possibly from field edges or earlier land use."))
        flags = []
        if share("plant_pathogen") > share("saprotroph"):
            flags.append(f"Pathogen-including genera ({_p(share('plant_pathogen'))}) outweigh decomposers "
                         f"({_p(share('saprotroph'))})")
        if "plant_pathogen" in R_:
            name, pct = R_["plant_pathogen"].top[0].rsplit(" ", 1)
            value = float(pct.strip("<%"))
            if value >= PATHOGEN_GENUS_FLAG:
                flags.append(f"{name} alone is {value:.0f}% of fungal DNA")
        ev = [f"{x.label}: {x.pct:.1f}% ({', '.join(x.top)})" for x in fungi.roles[:6]]
        ev.append(f"Coloured when genera that include plant pathogens outweigh decomposers, or one of them makes up "
                  f"{PATHOGEN_GENUS_FLAG:.0f}% or more of the fungal DNA with a genus name.")
        ev.append(f"Roles from FUNGuild at genus level; {fungi.named_pct:.0f}% of fungal reads have a genus name"
                  + (f"; {fungi.reads:,} fungal reads" if fungi.reads else "") + ". "
                  + ("Same soil cores as the gene data." if fungi.same_cores else
                     f"From the NEON visit on {fungi.date}, not the exact cores of the gene data."))
        few = fungi.reads is not None and fungi.reads < MIN_FUNGAL_READS
        headline = (f"{_p(share('saprotroph'))} decomposers · {_p(share('plant_pathogen'))} pathogen-including genera"
                    f" · {_p(share('arbuscular_mycorrhizal') + share('other_mycorrhizal'))} mycorrhizal")
        cards.append(DecisionCard(card="fungi", title="Fungi in this soil", status="notice" if flags else "info",
                                  headline=headline, flag="; ".join(flags) or None, finding=finding,
                                  implications=imps, basis="fungi", confidence="low", evidence=ev
                                  + (["Few fungal reads: small shares may be noise."] if few else [])))

    if bacteria is not None and len(bacteria.genera):     # names, not genes: independent of gene depth too
        cards.append(_bacteria_pathogen_card(bacteria, bacteria_reads))

    if not deep:
        for card, title in [("nitrogen", "Nitrogen cycle microbes"), ("p_release", "Phosphorus release by microbes"),
                            ("root_health", "Root protection and stress relief")]:
            cards.append(DecisionCard(card=card, title=title, status="unknown", headline="Too few genes to tell",
                                      flag=None, finding="Too few genes were assembled from this sample to describe its microbes.",
                                      implications=[], basis="genes", confidence="low", evidence=[]))
        return cards

    # ---- genes: the nitrogen story, pathway by pathway
    den, dnra, nit, fix, urea = (P["Denitrification"], P["Nitrate kept as ammonium (DNRA)"], P["Nitrification"],
                                 P["Nitrogen fixation"], P["Urea breakdown"])
    has = lambda p, i: p.steps[i].status == "found"  # noqa: E731
    carried = []
    if den.complete:
        carried.append("the full denitrification pathway (nitrate to N2)")
    elif any(s.status == "found" for s in den.steps):
        carried.append("denitrification up to " + next(s.step.split(" → ")[1] for s in reversed(den.steps) if s.status == "found"))
    if has(dnra, 1):
        carried.append("nitrate-to-ammonium (DNRA)")
    if has(nit, 0):
        carried.append("ammonia (or methane) oxidation")
    if has(urea, 0):
        carried.append("urea breakdown")
    missing = [p.name.lower() for p in (fix,) if not any(s.status == "found" for s in p.steps)]
    finding = ("Microbes here carry " + ", ".join(carried) + "." if carried else "Few nitrogen-cycle genes found.") + (
        f" No {', '.join(missing)} genes found." if missing else "")
    imps, nflag = [], None
    makers, cleaners, keepers, gas = c("norB"), c("nosZ"), c("nrfA"), c("nirK", "nirS")
    if makers >= MIN_COUNT and cleaners == 0:
        nflag = "N2O-making genes but no N2O-removing gene found"
    elif cleaners and makers / cleaners >= N2O_FLAG_RATIO:
        nflag = f"{makers / cleaners:.0f}× more N2O-making than N2O-removing genes"
    short = (["full denitrification" if den.complete else "partial denitrification"]
             if any(s.status == "found" for s in den.steps) else []) + (
        ["nitrate kept as ammonium"] if has(dnra, 1) else []) + (["nitrification"] if has(nit, 0) else []) + (
        ["urea breakdown"] if has(urea, 0) else []) + (["no N fixation found"] if missing else [])
    if makers + cleaners >= MIN_RATIO_GENES:
        if cleaners:
            per = makers / cleaners
            imps.append(imp(R if per > 1 else U,
                            f"About {per:.0f} genes that make N2O for every gene that removes it: when the soil is wet "
                            "and holds nitrate, part of the nitrogen lost as gas can leave as N2O, a greenhouse gas."
                            if per > 1 else "N2O made here can largely be turned into harmless N2."))
        else:
            imps.append(imp(R, "Genes that make N2O but none that remove it: nitrogen lost as gas can leave as N2O."))
    if keepers:
        imps.append(imp(U, f"Some microbes can keep nitrate in the soil as ammonium instead (about 1 such gene per "
                           f"{gas / keepers:.0f} that start turning nitrate into gas)."))
    if has(nit, 0):
        imps.append(imp(N, "Ammonium from fertiliser or manure can be turned into nitrate, which crops use but water "
                           "can wash away (if these genes are from ammonia rather than methane oxidisers)."))
    if has(urea, 0) and m and m.ph_water is not None and m.ph_water >= 7.0:
        imps.append(imp(R, f"Urea is quickly turned into ammonium; at pH {m.ph_water:.1f}, urea left on the surface can "
                           "lose part of its nitrogen to the air as ammonia."))
    if m and m.nitrate_n_mgkg is not None and m.nitrate_n_mgkg >= NITRATE_LOW and makers:
        imps.append(imp(N, f"At this visit the soil held {m.nitrate_n_mgkg:.1f} mg/kg nitrate: the raw material for "
                           "denitrification is there; whether it runs depends on how wet the soil gets."))
    if missing:
        imps.append(imp(N, "Nitrogen-fixation genes are rare and easily missed; legume nodule bacteria are not "
                           "covered either, so this does not mean no fixation."))
    cards.append(DecisionCard(
        card="nitrogen", title="Nitrogen cycle microbes", status="notice" if nflag else "info",
        headline=(" · ".join(short)[:1].upper() + " · ".join(short)[1:]) or "Few nitrogen-cycle genes", flag=nflag,
        finding=finding,
        implications=imps,
        basis="genes", confidence="low",
        evidence=[f"{p.name} (KEGG {p.kegg_module}): " + ", ".join(f"{s.step} {s.copies}" for s in p.steps)
                  for p in pathways]
                 + ["Gene copies found in this sample; capacity, not activity.",
                    f"Coloured when N2O-making genes (norB) are found with no N2O-removing gene (nosZ), or outnumber "
                    f"them {N2O_FLAG_RATIO}:1 or more."]))

    # ---- genes: phosphorus from organic matter vs minerals
    org, mineral = c("phoD", "phoA", "appA"), c("gcd", "pqqC")
    if org + mineral >= MIN_RATIO_GENES:
        share = 100 * org / (org + mineral)
        imps = [imp(N, f"About {share:.0f}% of the phosphorus-freeing genes target organic phosphorus (phosphatases, "
                       f"phytase) and {100 - share:.0f}% phosphorus bound in minerals (acids that dissolve it).")]
        if m and m.organic_c_pct is not None:
            name, _, _ = _band(m.organic_c_pct, OC_BANDS)
            imps.append(imp(R if name == "low" else U if name == "high" else N,
                            f"Organic phosphorus release draws on organic matter, which is {name} here "
                            f"({m.organic_c_pct:.2f}% organic carbon)."))
        if m and m.ph_water is not None and m.ph_water >= 7.5:
            imps.append(imp(U, "In alkaline soil phosphorus binds to calcium; microbes that dissolve mineral phosphate "
                               "are the ones that can free it."))
        imps.append(imp(N, "NEON does not measure plant-available phosphorus in these samples, so only a soil P test "
                           "can say whether there is enough."))
        cards.append(DecisionCard(
            card="p_release", title="Phosphorus release by microbes", status="info", flag=None,
            headline="Microbes here can free phosphorus from organic matter and from minerals, "
                     + ("about equally." if 40 <= share <= 60 else
                        f"mostly from {'organic matter' if share > 60 else 'minerals'}."),
            finding=f"Genes for freeing phosphorus: {org} copies for organic phosphorus, {mineral} for mineral phosphorus.",
            implications=imps, basis="genes", confidence="low",
            evidence=[f"Organic-P genes (phoD, phoA, appA) {org}, mineral-P genes (gcd, pqqC) {mineral} copies"]))

    # ---- genes: copper resistance (presence of mobile resistance genes)
    plasmid, pumps = c("pcoB/copB", "pcoC/copC", "pcoD/copD"), c("cusA", "cusB", "cusC", "cusF")
    if plasmid + pumps >= MIN_COUNT:
        cards.append(DecisionCard(
            card="copper", title="Copper resistance", status="info", flag=None,
            headline="Some soil bacteria carry copper-resistance genes.",
            finding=f"Copper-resistance genes found: {plasmid} copies of pco/cop genes (often carried on plasmids) and "
                    f"{pumps} of the cus copper pump.",
            implications=[imp(N, "Resistance genes on plasmids can pass between bacteria and spread where copper builds "
                                 "up (copper fungicides, some manures); they also occur in soils without extra copper."),
                          imp(N, "NEON does not measure soil copper here, so a soil test is the way to check it.")],
            basis="genes", confidence="low",
            evidence=["Only resistance genes (pco, cus) are counted, not the copper handling every bacterium has."]))

    # ---- genes: root protection and stress relief (presence)
    protect = [n for n, g in (("DAPG", "phlD"), ("hydrogen cyanide", "hcnA")) if c(g) > 0]
    imps = [imp(U, f"Genes for disease-suppressing compounds found: {', '.join(protect)}.") if protect else
            imp(R, "No genes for DAPG or hydrogen cyanide were found: no sign of the Pseudomonas groups that make some "
                   "soils suppress root diseases such as take-all.")]
    if c("acdS") >= MIN_COUNT:
        imps.append(imp(U, "Microbes with ACC deaminase are present: they can ease plant stress from drought, heat or "
                           "salt by lowering the stress hormone ethylene in roots."))
    if c("chiA") >= MIN_COUNT:
        imps.append(imp(N, "Chitin-digesting microbes are present; chitinases can attack fungal walls but are common "
                           "and not a sign of disease control on their own."))
    cards.append(DecisionCard(
        card="root_health", title="Root protection and stress relief", status="info", flag=None,
        headline=("Disease-suppressing genes found" if protect else "No disease-suppressing genes")
        + (" · stress-relief genes present" if c("acdS") >= MIN_COUNT else ""),
        finding="Disease-suppressing genes " + ("found" if protect else "not found") + "; stress-relief genes "
                + ("present." if c("acdS") >= MIN_COUNT else "not found."),
        implications=imps, basis="genes", confidence="low",
        evidence=[f"phlD {c('phlD')}, hcnA {c('hcnA')}, acdS {c('acdS')}, chiA {c('chiA')} copies",
                  "Not found means not found at this sequencing depth, not absent."]))
    return cards


CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def _rank(cards: list[DecisionCard]) -> list[DecisionCard]:
    """One list, most trustworthy first: by confidence, cards without data last; rule order within a rank."""
    return sorted(cards, key=lambda c: (c.status == "unknown", CONF_RANK.get(c.confidence, 3)))


# ---------------------------------------------------------------- routes
router = APIRouter(prefix="/api")


@router.get("/plots/{plot_id}/functions", response_model=list[FunctionSample])
def plot_functions(plot_id: str):
    """Metagenomes of the plot that have a gene panel, oldest first."""
    core.plot_rows("plot_geometry", plot_id)            # 404 for an unknown plot
    mg = _metagenomes()
    mg = mg[mg["plotID"] == plot_id]
    return [FunctionSample(sample_id=r.sample_id, date=r.date, year=r.date.year, n_genes=r.n_ko_genes,
                           deep_enough=r.ko_depth_ok) for r in mg.itertuples()]


@router.get("/functions/{sample_id}", response_model=FunctionProfile)
def function_profile(sample_id: str):
    mg = _metagenomes()
    hit = mg[mg["sample_id"] == sample_id]              # looked up in the tables, never parsed into a path
    if hit.empty:
        raise HTTPException(404, f"unknown metagenome sample {sample_id}")
    r = next(hit.itertuples())
    deep = bool(r.ko_depth_ok)
    panel = core.table("ko_panel")
    mine = panel[panel["metagenome_key"] == r.metagenome_key]
    copies = mine.groupby("gene")["count"].sum().astype(int).to_dict()

    rules = core.ROOT / "rules" / "ko_panel.csv"
    caveats = {}
    if rules.exists():
        k = pd.read_csv(rules)
        caveats = {g: (c if isinstance(c, str) else None) for g, c in zip(k["gene"], k["caveat"])}
    onto = microbe_roles.load_ontology()
    groups = []
    for g, (title, meaning, theme) in GROUPS.items():
        genes = mine[mine["function_group"] == g]
        groups.append(FunctionGroup(group=g, title=title, meaning=meaning, theme=theme,
                                    status=_status(int(genes["count"].sum()), deep),
                                    term_id=next(iter(microbe_roles.terms_for_ko_group(onto, g)), None),
                                    genes=[GeneCount(gene=x.gene, ko=x.ko, count=int(x.count),
                                                     caveat=caveats.get(x.gene)) for x in genes.itertuples()]))

    pathways = _pathways(copies, deep)
    fungi = _fungi(r)
    guilds = core.table("fungal_guilds").set_index("genus") if _has("fungal_guilds") else pd.DataFrame()
    measured = _measured(r.plotID, r.date)
    ru, bacteria_reads = _bacteria_rollup(r)
    carriers = _carriers(ru, groups) if ru is not None else []
    notes = [f"This sample on its own: {r.n_ko_genes:,} genes were assembled from its DNA. Genes show what the "
             "microbes are equipped to do, not how active they are."]
    if not deep:
        notes.insert(0, "Too few genes were assembled from this sample to say which functions are missing: most "
                        "genes are never found at this depth.")
    notes.append(f"Fewer than {MIN_COUNT} gene copies count as a trace. Not found means not found at this depth, "
                 "never absent.")
    if fungi is None:
        notes.append("No NEON fungal (ITS) data for this soil within a week of the sample.")
    elif not _has("fungal_guilds"):
        notes.append("Fungal roles need FUNGuild: run scripts/16_fetch_funguild.py.")
    if carriers:
        notes.append("Who may carry it: genera of this sample's bacteria and archaea known for the role (AI "
                     "annotation, medium or high confidence); shares are of the classified bacterial and archaeal reads.")
    return FunctionProfile(sample_id=r.sample_id, plot_id=r.plotID, date=r.date, n_genes=r.n_ko_genes,
                           deep_enough=deep, cards=_rank(_cards(copies, pathways, fungi, measured, deep, guilds, ru,
                                                                bacteria_reads, key=r.metagenome_key)),
                           pathways=pathways, fungi=fungi, groups=groups, measured=measured, notes=notes,
                           carriers=carriers)
