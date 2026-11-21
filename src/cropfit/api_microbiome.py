"""GUI API: soil microbiome composition of one plot and sample (bacteria + archaea from NMDC metagenomes,
fungi from NEON ITS). Mounted by api.create_app(); reads the tables of scripts/05 and 02b.

A *sample* is what one composition is computed from:
  bacteria  one NMDC metagenome (up to 3 pooled soil cores), Kraken2 read classification   -> taxa_lineage
  fungi     one NEON plot-date: mean of per-core ITS shares over the cores that passed QC  -> its_genus

Shares are of the reads that could be placed in the group (bacteria + archaea, or fungi). Reads that have no
name at the chosen rank (Kraken2 stops higher up; ITS placeholders such as `Hypocreales_gen_Incertae_sedis`
or `unclassified_Fungi`) are reported together as `unassigned_pct`, never spread over named taxa.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import api as core
from . import microbe_roles

Kind = Literal["bacteria", "fungi"]
Rank = Literal["phylum", "class", "genus"]
SummaryClassId = Literal["useful", "mixed", "harmful", "context", "background", "unknown"]
Polarity = Literal["useful", "harmful", "context", "background", "unknown"]
Confidence = Literal["high", "medium", "low"]
Evidence = Literal["curated_db", "well_known_genus", "some_species", "inferred"]

MIN_BACTERIA_READS = 10_000     # classified bacterial + archaeal reads; below this a composition is shaky
MIN_FUNGI_READS = 5_000         # fungal ITS reads summed over the passing cores
OLD_ITS_PIPELINE = "DP1.10081.001"


# ---------------------------------------------------------------- response models
class MicrobiomeSample(BaseModel):
    sample_id: str
    kind: Kind
    date: dt.date
    year: int
    reads: int                       # reads the composition is computed from (see module docstring)
    n_cores: int                     # soil cores behind the sample
    low_depth: bool                  # too few reads to trust small shares


class Taxon(BaseModel):
    name: str
    phylum: str | None               # the taxon's phylum (itself at phylum rank); used to colour it
    pct: float                       # share of the group's reads, 0-100
    reads: int
    description: str | None = None   # rank genus only: rules/microbe_genera.csv via microbe_roles.describe(); else None


class Composition(BaseModel):
    sample_id: str
    kind: Kind
    plot_id: str
    date: dt.date
    rank: Rank
    reads: int
    n_taxa: int                      # named taxa at this rank, including the ones folded into "other"
    taxa: list[Taxon]                # largest first: all of them, or the `top` largest when asked
    other_pct: float                 # named taxa beyond `top` (0 without `top`)
    unassigned_pct: float            # reads without a name at this rank
    notes: list[str]                 # plain-language caveats for this sample


class RoleSummary(BaseModel):
    class_id: SummaryClassId
    label: str                       # section 2 labels of docs/microbe_roles.md, exact
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
    terms: list[RoleTerm]            # all terms, ontology (depth-first) order, empty ones included
    annotated_pct: float             # share of the group's reads from genera with >= 1 annotation row
    unassigned_pct: float            # reads without a genus name, as Composition at rank genus
    sources: list[str]               # distinct sources behind the counted rows of this sample
    notes: list[str]


# ---------------------------------------------------------------- samples
def _has(name: str) -> bool:
    return (core.PROCESSED / f"{name}.parquet").exists()


def _bacteria_samples() -> pd.DataFrame:
    if not (_has("metagenomes") and _has("taxa_lineage")):
        return pd.DataFrame()
    lin = core.table("taxa_lineage")
    reads = lin[lin["rank"] == "domain"].groupby("metagenome_key")["reads"].sum()
    mg = core.table("metagenomes")
    mg = mg[mg["metagenome_key"].isin(reads.index)]
    return pd.DataFrame({
        "sample_id": "mg-" + mg["metagenome_key"].str.replace("nmdc:", "", regex=False),
        "kind": "bacteria", "plotID": mg["plotID"], "date": pd.to_datetime(mg["date"]).dt.date,
        "reads": mg["metagenome_key"].map(reads).astype(int), "n_cores": mg["n_biosamples"],
        "key": mg["metagenome_key"], "unclassified_pct": mg["kraken_unclassified_pct"],
        "product": "", "below_share": 0.0,
    })


def _fungi_samples() -> pd.DataFrame:
    if not _has("its_genus"):
        return pd.DataFrame()
    g = core.table("its_genus")
    s = (g.groupby(["plotID", "collectDate"])
         .agg(reads=("total_reads", "first"), n_cores=("n_cores", "first"), product=("product", "first"),
              below_share=("its_below_threshold_share", "first")).reset_index())
    date = pd.to_datetime(s["collectDate"])
    return pd.DataFrame({
        "sample_id": "its-" + s["plotID"] + "-" + date.dt.strftime("%Y%m%d"),
        "kind": "fungi", "plotID": s["plotID"], "date": date.dt.date, "reads": s["reads"].astype(int),
        "n_cores": s["n_cores"], "key": "", "unclassified_pct": float("nan"),
        "product": s["product"].fillna(""), "below_share": s["below_share"].fillna(0.0),
    })


def _samples() -> pd.DataFrame:
    parts = [p for p in (_bacteria_samples(), _fungi_samples()) if len(p)]
    if not parts:
        raise HTTPException(503, "no microbiome tables: run scripts/02b_build_neon_features.py and "
                                 "scripts/05_build_biology.py (see AGENT.md)")
    s = pd.concat(parts, ignore_index=True)
    s["low_depth"] = s["reads"] < s["kind"].map({"bacteria": MIN_BACTERIA_READS, "fungi": MIN_FUNGI_READS})
    return s.sort_values(["date", "kind"]).reset_index(drop=True)


def _to_sample(r) -> MicrobiomeSample:
    return MicrobiomeSample(sample_id=r.sample_id, kind=r.kind, date=r.date, year=r.date.year, reads=int(r.reads),
                            n_cores=int(r.n_cores), low_depth=bool(r.low_depth))


# ---------------------------------------------------------------- composition
def _unnamed(names: pd.Series) -> pd.Series:
    """ITS placeholder names that stand for 'no name at this rank'."""
    n = names.astype("string")
    return n.isna() | n.str.contains("Incertae_sedis", regex=False) | n.str.startswith("unclassified")


def _bacteria_taxa(key: str, rank: Rank) -> pd.DataFrame:
    lin = core.table("taxa_lineage")
    lin = lin[(lin["metagenome_key"] == key) & (lin["rank"] == rank)]
    t = lin.groupby(["name", "phylum"], dropna=False, as_index=False)["reads"].sum()
    total = core.table("taxa_lineage")
    total = total[(total["metagenome_key"] == key) & (total["rank"] == "domain")]["reads"].sum()
    t["pct"] = 100 * t["reads"] / total if total else 0.0
    return t


def _fungi_taxa(plot_id: str, date: dt.date, rank: Rank) -> pd.DataFrame:
    g = core.table("its_genus")
    g = g[(g["plotID"] == plot_id) & (pd.to_datetime(g["collectDate"]).dt.date == date)]
    lin = core.table("its_genus_lineage") if _has("its_genus_lineage") else pd.DataFrame(columns=["genus", "phylum", "class"])
    g = g.merge(lin, on="genus", how="left")
    g["name"] = g[rank]
    g.loc[_unnamed(g["phylum"]), "phylum"] = None
    g = g[~_unnamed(g["name"])]
    return (g.groupby(["name", "phylum"], dropna=False, as_index=False)
            .agg(reads=("reads", "sum"), pct=("rel_abund_pct", "sum")))


def _find(sample_id: str):
    """The sample row of `sample_id`, looked up in the tables (never parsed into a path); 404 when unknown."""
    s = _samples()
    hit = s[s["sample_id"] == sample_id]
    if hit.empty:
        raise HTTPException(404, f"unknown microbiome sample {sample_id}")
    return next(hit.itertuples())


def _notes(r) -> list[str]:
    notes = []
    if r.low_depth:
        notes.append(f"Few DNA reads ({int(r.reads):,}): small shares may be noise, compare with care.")
    if r.kind == "bacteria":
        if pd.notna(r.unclassified_pct):
            notes.append(f"About {r.unclassified_pct:.0f}% of all DNA reads in this sample matched no known organism; "
                         "shares are of the bacterial and archaeal reads that did.")
        notes.append("Fungi are not covered by this method: see the fungi view.")
    else:
        if OLD_ITS_PIPELINE in r.product:
            notes.append("Processed with NEON's older method (up to 2017): not directly comparable with later years.")
        if r.below_share > 0:
            notes.append(f"{r.below_share:.0%} of the soil cores from this visit had too few reads and were left out.")
    if r.n_cores > 1:
        notes.append(f"Based on {int(r.n_cores)} soil cores from the plot.")
    return notes


# ---------------------------------------------------------------- routes
router = APIRouter(prefix="/api")


@router.get("/plots/{plot_id}/microbiome", response_model=list[MicrobiomeSample])
def plot_microbiome(plot_id: str):
    """Microbiome samples of the plot, oldest first (bacteria before fungi on the same day)."""
    core.plot_rows("plot_geometry", plot_id)            # 404 for an unknown plot
    s = _samples()
    return [_to_sample(r) for r in s[s["plotID"] == plot_id].itertuples()]


@router.get("/microbiome/{sample_id}", response_model=Composition)
def composition(sample_id: str, rank: Rank = "phylum", top: int | None = Query(None, ge=1)):
    """Composition of one sample at `rank`: every named taxon, largest first (or only the `top` largest, the
    rest summed in `other_pct`)."""
    r = _find(sample_id)
    t = _bacteria_taxa(r.key, rank) if r.kind == "bacteria" else _fungi_taxa(r.plotID, r.date, rank)
    t = t[t["reads"] > 0].sort_values(["pct", "name"], ascending=[False, True])
    head, rest = (t, t.iloc[:0]) if top is None else (t.head(top), t.iloc[top:])
    named = float(t["pct"].sum())
    desc = microbe_roles.load_descriptions() if rank == "genus" else {}
    taxa = [Taxon(name=x.name, phylum=None if pd.isna(x.phylum) else x.phylum, pct=round(float(x.pct), 4),
                  reads=int(x.reads), description=microbe_roles.describe(r.kind, x.name, desc) if desc else None)
            for x in head.itertuples()]
    return Composition(sample_id=r.sample_id, kind=r.kind, plot_id=r.plotID, date=r.date, rank=rank,
                       reads=int(r.reads), n_taxa=len(t), taxa=taxa, other_pct=round(float(rest["pct"].sum()), 2),
                       unassigned_pct=round(max(0.0, 100 - named), 2), notes=_notes(r))


def _role_notes(r, ru: microbe_roles.RollUp) -> list[str]:
    ai = "Roles come from an AI (LLM) annotation of each genus, checked by a second AI review only for harmful and abundant genera."
    if r.kind == "fungi":
        have = [(core.PROCESSED / t).exists() for t in (microbe_roles.FUNGALTRAITS_TABLE, microbe_roles.FUNGUILD_TABLE)]
        ai += (" For fungi, FUNGuild and FungalTraits are used wherever they give a role." if any(have) else
               " FUNGuild and FungalTraits tables are missing here, so fungal roles are from the AI annotation only.")
    notes = _notes(r) + ["Roles are given per genus: a genus marked as including pathogens usually also holds "
                         "harmless species, and one genus can have several roles.", ai,
                         "Only roles given with medium or high confidence are counted."]
    if ru.named_pct - ru.annotated_pct >= 0.5:
        notes.append(f"{ru.named_pct - ru.annotated_pct:.0f}% of the reads are from genera not yet annotated; "
                     "they count as Role unknown.")
    if not microbe_roles.ANNOTATIONS_FILE.exists():
        notes.append("Role annotations are not available yet (rules/microbe_annotations.csv is missing), so "
                     "every genus counts as Role unknown.")
    return notes


def _role_genus(x) -> RoleGenus:
    return RoleGenus(name=x.name, domain=x.domain if isinstance(x.domain, str) else None,
                     phylum=None if pd.isna(x.phylum) else x.phylum, pct=round(float(x.pct), 4), reads=int(x.reads),
                     term_id=x.row_term_id, confidence=x.confidence, evidence=x.evidence, source=x.source,
                     species_examples=list(x.species_examples), note=x.note or None, summary_class=x.summary_class,
                     description=x.description if isinstance(x.description, str) else None)


@router.get("/microbiome/{sample_id}/roles", response_model=RoleComposition)
def roles(sample_id: str, genera_per_term: int = Query(50, ge=1, le=5000)):
    """What the named genera of one sample are likely to do (docs/microbe_roles.md): the six-class summary (a
    partition of the named reads), and every role term with the genera that carry it (terms overlap)."""
    r = _find(sample_id)
    t = _bacteria_taxa(r.key, "genus") if r.kind == "bacteria" else _fungi_taxa(r.plotID, r.date, "genus")
    ru = microbe_roles.roll_up(t, r.kind, ann=microbe_roles.load_annotations(core.PROCESSED))
    by_term = {k: v for k, v in ru.term_genera.groupby("term_id")}
    terms = []
    for x in ru.terms.itertuples():
        g = by_term.get(x.term_id, ru.term_genera.iloc[:0])
        terms.append(RoleTerm(
            term_id=x.term_id, parent_id=x.parent_id, label=x.label, description=x.description, polarity=x.polarity,
            depth=int(x.depth), ko_groups=list(x.ko_groups), pct=round(float(x.pct), 2), n_genera=int(x.n_genera),
            genera=[_role_genus(y) for y in g.head(genera_per_term).itertuples()],
            other_genera_pct=round(float(g["pct"].iloc[genera_per_term:].sum()), 2)))
    summary = [RoleSummary(class_id=x.class_id, label=x.label, pct=round(float(x.pct), 2),
                           pct_of_named=round(float(x.pct_of_named), 2), n_genera=int(x.n_genera), top=list(x.top))
               for x in ru.summary.itertuples()]
    return RoleComposition(sample_id=r.sample_id, kind=r.kind, plot_id=r.plotID, date=r.date, reads=int(r.reads),
                           n_genera=len(ru.genera), summary=summary, terms=terms,
                           annotated_pct=round(ru.annotated_pct, 2), unassigned_pct=round(max(0.0, 100 - ru.named_pct), 2),
                           sources=ru.sources, notes=_role_notes(r, ru))
