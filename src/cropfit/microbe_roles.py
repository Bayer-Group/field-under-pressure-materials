"""Microbe roles: what the genera of a soil sample are likely to do for a crop (contract: docs/microbe_roles.md).

Three inputs, all optional on disk so the module degrades to "role unknown" instead of failing:
  * rules/microbe_ontology.csv     the small GO-style term tree (depth-first order is the display order);
  * rules/microbe_annotations.csv  LLM annotations genus -> term, many-to-many, with confidence and evidence;
  * FungalTraits + FUNGuild        curated fungal roles computed here at load time and merged over the LLM rows
                                   where they speak (section 4 of the contract).

Pure functions over DataFrames, no FastAPI. Only rows with confidence high or medium are *counted*; low rows stay
in the files for review. A genus gets exactly one summary class (a partition, so the shares add up); terms
overlap on purpose (a genus counts once per term, but can count in several terms).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

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
ORGAN_TERMS = ("root_soilborne_pathogen", "foliar_pathogen")
CURATED_TERMS = PATHOGEN_AXIS + ("mycorrhizal_partner", "tree_mycorrhizal", "mycoparasite", "decomposer", "endophyte")
UNKNOWN_TERMS = ("unknown", "doubtful_assignment")

_SAPROTROPH = ["soil_saprotroph", "litter_saprotroph", "wood_saprotroph", "unspecified_saprotroph",
               "unsepcified_saprotroph",   # typo in the FungalTraits source
               "dung_saprotroph", "nectar/tap_saprotroph", "pollen_saprotroph", "fungal_decomposer",
               "animal_decomposer", "algal_decomposer"]
FT_LIFESTYLE_TERM: dict[str, str] = {
    "plant_pathogen": "plant_pathogen",     # pathogen axis: the organ term comes from the capacity column
    "arbuscular_mycorrhizal": "mycorrhizal_partner",
    "ectomycorrhizal": "tree_mycorrhizal", "ericoid_mycorrhizal": "tree_mycorrhizal",
    "mycoparasite": "mycoparasite",
    **{v: "decomposer" for v in _SAPROTROPH},
    "foliar_endophyte": "endophyte", "root_endophyte": "endophyte", "root_endophyte_dark_septate": "endophyte",
}
FT_CAPACITY_TERM: dict[str, str] = {
    "root_pathogen": "root_soilborne_pathogen", "leaf/fruit/seed_pathogen": "foliar_pathogen",
    "wood_pathogen": "plant_pathogen", "other_plant_pathogen": "plant_pathogen",
    "unspecified_plant_pathogen": "plant_pathogen",
}   # algal_parasite, moss_parasite, root-associated, moss-associated: ignored (absent)
FUNGUILD_CATEGORY_TERM: dict[str, str] = {
    "arbuscular_mycorrhizal": "mycorrhizal_partner", "other_mycorrhizal": "tree_mycorrhizal",
    "fungal_parasite": "mycoparasite", "plant_pathogen": "plant_pathogen", "endophyte": "endophyte",
    "saprotroph": "decomposer",
}
FUNGUILD_CONFIDENCE = {"Highly Probable": "high", "Probable": "medium", "Possible": "low"}
CAPPED = "capped: curated sources do not list it as a plant pathogen; "
SYNTHETIC_NOTE = "not in the annotation files"


# ---------------------------------------------------------------- files
@lru_cache(maxsize=16)
def _read_csv(path: Path, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _csv(path: Path) -> pd.DataFrame | None:
    """A CSV as strings ('' for empty), re-read only when the file changed; None when missing. Shared: don't mutate."""
    path = Path(path)
    return _read_csv(path.resolve(), path.stat().st_mtime) if path.exists() else None


def _stamp(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else -1.0


def _split(text: object, sep: str) -> list[str]:
    return [x.strip() for x in text.split(sep) if x.strip()] if isinstance(text, str) else []


# ---------------------------------------------------------------- ontology
@lru_cache(maxsize=4)
def _ontology(path: Path, mtime: float) -> pd.DataFrame:
    raw = _read_csv(path, mtime)
    rows, seen = [], {}
    for r in raw.itertuples():
        parent = r.parent_id or None
        if r.term_id in seen:
            raise ValueError(f"ontology: duplicate term {r.term_id}")
        if parent is None:
            if r.term_id not in POLARITIES:
                raise ValueError(f"ontology: root {r.term_id} is not one of {POLARITIES}")
            depth, root = 0, r.term_id
        elif parent not in seen:
            raise ValueError(f"ontology: parent {parent} of {r.term_id} is missing or comes later (or a cycle)")
        else:
            depth, root = seen[parent]["depth"] + 1, seen[parent]["root"]
        if r.polarity != root:
            raise ValueError(f"ontology: polarity of {r.term_id} is {r.polarity}, its root is {root}")
        seen[r.term_id] = dict(depth=depth, root=root)
        rows.append(dict(term_id=r.term_id, parent_id=parent, label=r.label, polarity=r.polarity,
                         ko_groups=_split(r.ko_group, ";"), description=r.description, depth=depth, root=root))
    df = pd.DataFrame(rows)
    df["parent_id"] = df["parent_id"].astype(object).where(df["parent_id"].notna(), None)   # None, not NaN
    return df


def load_ontology(path: Path | None = None) -> pd.DataFrame:
    """Terms in CSV (depth-first) order. Columns: term_id, parent_id (None for roots), label, polarity,
    ko_groups (list[str]), description, depth (int), root (str). Raises ValueError when a parent is missing or
    comes later, the graph has a cycle, polarity differs from the root id, or a root is not one of POLARITIES."""
    path = Path(path or ONTOLOGY_FILE)
    return _ontology(path.resolve(), path.stat().st_mtime)


def subtree(onto: pd.DataFrame, term_id: str) -> list[str]:
    """The term and all its descendants, in ontology order."""
    keep = {term_id}
    for t, p in zip(onto["term_id"], onto["parent_id"]):     # parents come first, one pass is enough
        if p in keep:
            keep.add(t)
    return [t for t in onto["term_id"] if t in keep]


def terms_for_ko_group(onto: pd.DataFrame, group: str) -> list[str]:
    """Terms whose ko_group lists `group` ("phlD" -> ["antibiotic_producer"]); [] when none."""
    return [t for t, g in zip(onto["term_id"], onto["ko_groups"]) if group in g]


def _ancestors(onto: pd.DataFrame) -> dict[str, list[str]]:
    """term -> [term, parent, ..., root]."""
    parent = dict(zip(onto["term_id"], onto["parent_id"]))
    out = {}
    for t in onto["term_id"]:
        chain, x = [], t
        while isinstance(x, str):
            chain.append(x)
            x = parent[x]
        out[t] = chain
    return out


# ---------------------------------------------------------------- annotations
def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=str) for c in ANNOTATION_COLUMNS})


def load_llm_annotations(path: Path | None = None) -> pd.DataFrame:
    """rules/microbe_annotations.csv as ANNOTATION_COLUMNS (strings, '' for empty). Empty frame with those
    columns when the file is missing."""
    raw = _csv(path or ANNOTATIONS_FILE)
    if raw is None:
        return _empty()
    return raw.reindex(columns=ANNOTATION_COLUMNS, fill_value="").copy()


def _present(*values: object) -> bool:
    return all(isinstance(v, str) and v.strip() not in ("", "nan") for v in values)


def _pathogen_terms(capacity: object) -> tuple[list[str], bool]:
    """Pathogen-axis terms of a FungalTraits capacity string, and whether it only says wood/tree pathogen."""
    vals = _split(capacity, ",")
    organs = [t for t in ORGAN_TERMS if any(FT_CAPACITY_TERM.get(v) == t for v in vals)]
    generic = [v for v in vals if FT_CAPACITY_TERM.get(v) == "plant_pathogen"]
    if organs:
        return organs, False
    return (["plant_pathogen"], generic == ["wood_pathogen"]) if generic else ([], False)


def _ft_rows(ft: pd.DataFrame) -> list[dict]:
    rows = []
    for r in ft.to_dict("records"):
        genus = r.get("genus")
        if not _present(genus):
            continue
        prim, sec = _split(r.get("primary_lifestyle"), "|"), _split(r.get("secondary_lifestyle"), "|")
        cap_text = r.get("plant_pathogenic_capacity")
        organ, wood_only = _pathogen_terms(cap_text)

        def add(term: str, conf: str, note: str) -> None:
            rows.append(dict(domain="Fungi", genus=genus, term_id=term, confidence=conf, evidence="curated_db",
                             source="fungaltraits", species_examples="", note=note))

        for field, values, conf in (("primary_lifestyle", prim, "high"), ("secondary_lifestyle", sec, "medium")):
            for v in values:
                term = FT_LIFESTYLE_TERM.get(v)
                if term is None:
                    continue
                note = f"FungalTraits {field}={v}"
                if term != "plant_pathogen":
                    add(term, conf, note)
                elif field == "primary_lifestyle":      # organ rows from the capacity; wood alone is low
                    for t in organ or ["plant_pathogen"]:
                        add(t, "low" if wood_only else "high", note + ("; wood/tree pathogen" if wood_only else ""))
                else:
                    for t in organ or ["plant_pathogen"]:
                        add(t, "low", note)
        if organ and "plant_pathogen" not in prim and "plant_pathogen" not in sec:
            for t in organ:                             # a capacity on a genus not listed as a plant pathogen
                add(t, "low", f"FungalTraits plant_pathogenic_capacity={cap_text}")
    return rows


def _guild_rows(guilds: pd.DataFrame) -> list[dict]:
    rows = []
    for r in guilds.to_dict("records"):
        term = FUNGUILD_CATEGORY_TERM.get(r.get("category"))
        if term is None or not _present(r.get("genus")):
            continue
        rows.append(dict(domain="Fungi", genus=r["genus"], term_id=term,
                         confidence=FUNGUILD_CONFIDENCE.get(r.get("confidence"), "low"), evidence="curated_db",
                         source="funguild", species_examples="",
                         note=f"FUNGuild primary guild={r.get('primary_guild') if _present(r.get('primary_guild')) else ''}"))
    return rows


def curated_fungal_rows(fungaltraits: pd.DataFrame | None, guilds: pd.DataFrame | None) -> pd.DataFrame:
    """Section 4.1 for every genus in the two tables: ANNOTATION_COLUMNS rows, domain 'Fungi', within-curated
    duplicates already resolved. Either table may be None or empty."""
    rows = (_ft_rows(fungaltraits) if fungaltraits is not None and len(fungaltraits) else []) + (
        _guild_rows(guilds) if guilds is not None and len(guilds) else [])
    if not rows:
        return _empty()
    df = pd.DataFrame(rows)
    df["_rk"] = df["confidence"].map(CONFIDENCE_RANK)
    df["_src"] = (df["source"] != "fungaltraits").astype(int)             # tie: fungaltraits wins
    df = (df.sort_values(["genus", "term_id", "_rk", "_src"]).drop_duplicates(["genus", "term_id"]))
    organ_genera = set(df.loc[df["term_id"].isin(ORGAN_TERMS), "genus"])
    df = df[~((df["term_id"] == "plant_pathogen") & df["genus"].isin(organ_genera))]
    return df[ANNOTATION_COLUMNS].sort_values(["genus", "term_id"]).reset_index(drop=True)


def curated_record_genera(fungaltraits: pd.DataFrame | None, guilds: pd.DataFrame | None) -> set[str]:
    """Fungal genera that have a curated record (section 4.2)."""
    out: set[str] = set()
    if fungaltraits is not None and len(fungaltraits):
        ok = fungaltraits["primary_lifestyle"].map(lambda v: _present(v))
        out |= set(fungaltraits.loc[ok, "genus"].dropna())
    if guilds is not None and len(guilds):
        out |= set(guilds.loc[~guilds["category"].isin(["other", "unknown"]), "genus"].dropna())
    return out


def _merge_genus(llm: list[dict], cur: list[dict]) -> list[dict]:
    """Section 4.2 for one fungal genus with a curated record."""
    cur_path = [r for r in cur if r["term_id"] in PATHOGEN_AXIS]
    llm_path = [r for r in llm if r["term_id"] in PATHOGEN_AXIS]
    cur_terms = {r["term_id"] for r in cur_path}
    if any(r["confidence"] in COUNTED for r in cur_path):          # curated_pathogen
        path = cur_path + [r for r in llm_path if r["term_id"] in ORGAN_TERMS and r["term_id"] not in cur_terms]
        if any(r["term_id"] in ORGAN_TERMS for r in path):
            path = [r for r in path if r["term_id"] != "plant_pathogen"]
    else:
        path = cur_path + [dict(r, confidence="low", note=CAPPED + r["note"]) for r in llm_path
                           if r["term_id"] not in cur_terms]
    other_cur = [r for r in cur if r["term_id"] not in PATHOGEN_AXIS and r["term_id"] in CURATED_TERMS]
    replaced = {r["term_id"] for r in other_cur}
    kept = [r for r in llm if r["term_id"] not in CURATED_TERMS or
            (r["term_id"] not in PATHOGEN_AXIS and r["term_id"] not in replaced)]
    rows = path + other_cur + kept
    if any(r["term_id"] not in UNKNOWN_TERMS for r in rows):
        rows = [r for r in rows if r["term_id"] != "unknown"]
    return rows


def merge_fungal(llm: pd.DataFrame, curated: pd.DataFrame, record_genera: set[str],
                 onto: pd.DataFrame | None = None) -> pd.DataFrame:
    """Section 4.2 applied to the Fungi rows of `llm`; Bacteria/Archaea rows pass through unchanged. Returns
    ANNOTATION_COLUMNS, sorted by domain, genus, ontology order."""
    onto = load_ontology() if onto is None else onto
    order = {t: i for i, t in enumerate(onto["term_id"])}
    is_fungus = llm["domain"] == "Fungi"
    by_llm = {g: s.to_dict("records") for g, s in llm[is_fungus].groupby("genus")}
    cur = curated[curated["genus"].isin(record_genera)]
    by_cur = {g: s.to_dict("records") for g, s in cur.groupby("genus")}
    out: list[dict] = []
    for genus in set(by_llm) | set(by_cur):
        rows_llm = by_llm.get(genus, [])
        out += _merge_genus(rows_llm, by_cur.get(genus, [])) if genus in record_genera else rows_llm
    merged = pd.concat([llm[~is_fungus], pd.DataFrame(out, columns=ANNOTATION_COLUMNS)], ignore_index=True)
    merged["_o"] = merged["term_id"].map(lambda t: order.get(t, len(order)))
    return (merged.sort_values(["domain", "genus", "_o"], kind="stable")[ANNOTATION_COLUMNS].reset_index(drop=True))


@lru_cache(maxsize=4)
def _merged(ann: Path, ann_t: float, onto: Path, onto_t: float, ft: Path, ft_t: float, gu: Path,
            gu_t: float) -> pd.DataFrame:
    llm = load_llm_annotations(ann)
    ft_df = pd.read_parquet(ft) if ft.exists() else None
    gu_df = pd.read_parquet(gu) if gu.exists() else None
    return merge_fungal(llm, curated_fungal_rows(ft_df, gu_df), curated_record_genera(ft_df, gu_df),
                        load_ontology(onto))


def load_annotations(processed: Path | None = None) -> pd.DataFrame:
    """LLM rows merged with curated fungal rows read from `processed` (default PROCESSED; tables optional).
    Cached. This is what every consumer uses. Shared: don't mutate."""
    processed = Path(processed or PROCESSED)
    ft, gu = processed / FUNGALTRAITS_TABLE, processed / FUNGUILD_TABLE
    ann, onto = Path(ANNOTATIONS_FILE), Path(ONTOLOGY_FILE)
    return _merged(ann.resolve(), _stamp(ann), onto.resolve(), _stamp(onto), ft.resolve(), _stamp(ft),
                   gu.resolve(), _stamp(gu))


# ---------------------------------------------------------------- descriptions
def load_descriptions(path: Path | None = None) -> dict[tuple[str, str], str]:
    """(domain, genus) -> description from rules/microbe_genera.csv; {} when the file is missing."""
    raw = _csv(path or GENERA_FILE)
    if raw is None:
        return {}
    return {(d, g): t for d, g, t in zip(raw["domain"], raw["genus"], raw["description"]) if t}


def describe(kind: str, genus: str, descriptions: dict | None = None) -> str | None:
    """Description for a genus of a 'bacteria' sample (tries Bacteria, then Archaea) or a 'fungi' sample."""
    descriptions = load_descriptions() if descriptions is None else descriptions
    return next((descriptions[(d, genus)] for d in KIND_DOMAINS[kind] if (d, genus) in descriptions), None)


# ---------------------------------------------------------------- summary class
def summary_class(polarities: Iterable[str]) -> str:
    """Rule of section 2 on the polarities of a genus's COUNTED rows; returns a class id."""
    p = set(polarities)
    if {"useful", "harmful"} <= p:
        return "mixed"
    return next((c for c in ("harmful", "useful", "context", "background") if c in p), "unknown")


def genus_summary(ann: pd.DataFrame, onto: pd.DataFrame) -> pd.DataFrame:
    """One row per annotated (domain, genus): domain, genus, summary_class, terms (list of counted term ids)."""
    pol = dict(zip(onto["term_id"], onto["polarity"]))
    order = {t: i for i, t in enumerate(onto["term_id"])}
    rows = []
    for (domain, genus), sub in ann.groupby(["domain", "genus"], sort=True):
        terms = sorted({t for t, c in zip(sub["term_id"], sub["confidence"]) if c in COUNTED and t in pol},
                       key=order.get)
        rows.append(dict(domain=domain, genus=genus, summary_class=summary_class(pol[t] for t in terms),
                         terms=terms))
    return pd.DataFrame(rows, columns=["domain", "genus", "summary_class", "terms"])


# ---------------------------------------------------------------- roll-up of one sample
@dataclass
class RollUp:
    genera: pd.DataFrame       # name, domain (None if unannotated), phylum, pct, reads, summary_class, annotated,
                               # description
    summary: pd.DataFrame      # SUMMARY_CLASSES order: class_id, label, pct, pct_of_named, n_genera, top
    terms: pd.DataFrame        # every ontology term: term_id, parent_id, label, description, polarity, depth,
                               # ko_groups, pct, n_genera
    term_genera: pd.DataFrame  # (term, genus) pairs with the representative row, sorted term, pct desc, name
    annotated_pct: float
    named_pct: float           # Σ pct of named genera (= 100 - unassigned_pct)
    sources: list[str]         # distinct `source` of counted rows of present genera, sorted


TERM_GENERA_COLUMNS = ["term_id", "name", "domain", "phylum", "pct", "reads", "row_term_id", "confidence", "evidence",
                       "source", "species_examples", "note", "summary_class", "description"]


def roll_up(taxa: pd.DataFrame, kind: str, ann: pd.DataFrame | None = None, onto: pd.DataFrame | None = None,
            descriptions: dict | None = None) -> RollUp:
    """`taxa`: the sample's genus-rank table as returned by api_microbiome._bacteria_taxa / _fungi_taxa
    (columns name, phylum, pct, reads; rows with reads <= 0 are dropped). `kind`: 'bacteria' | 'fungi'.
    Defaults: load_annotations(), load_ontology(), load_descriptions()."""
    onto = load_ontology() if onto is None else onto
    ann = load_annotations() if ann is None else ann
    descriptions = load_descriptions() if descriptions is None else descriptions
    order = {t: i for i, t in enumerate(onto["term_id"])}
    anc = _ancestors(onto)

    t = taxa[taxa["reads"] > 0]
    t = t.groupby("name", as_index=False).agg(phylum=("phylum", "first"), pct=("pct", "sum"), reads=("reads", "sum"))
    t["phylum"] = t["phylum"].astype(object).where(t["phylum"].notna(), None)

    domains = KIND_DOMAINS[kind]
    a = ann[ann["domain"].isin(domains) & ann["genus"].isin(t["name"]) & ann["term_id"].isin(order)].copy()
    a["_d"] = a["domain"].map({d: i for i, d in enumerate(domains)})
    a = a[a["_d"] == a.groupby("genus")["_d"].transform("min")]      # a genus name belongs to one domain
    a["_rk"] = a["confidence"].map(CONFIDENCE_RANK)
    a["_o"] = a["term_id"].map(order)

    gs = genus_summary(a, onto)
    g = t.merge(gs[["genus", "domain", "summary_class"]], left_on="name", right_on="genus", how="left")
    g["annotated"] = g["domain"].notna()
    g["domain"] = g["domain"].astype(object).where(g["annotated"], None)
    g["summary_class"] = g["summary_class"].fillna("unknown")
    g["description"] = [describe(kind, n, descriptions) for n in g["name"]]
    g = g.drop(columns="genus").sort_values(["pct", "name"], ascending=[False, True]).reset_index(drop=True)

    # one representative row per (term, genus): best confidence, then first in ontology order
    c = a[a["confidence"].isin(COUNTED)].copy()
    c["anc"] = c["term_id"].map(anc)
    c = c.explode("anc")
    c = c[c["anc"] != "unknown"]                       # the unknown root is the summary class, handled below
    rep = (c.sort_values(["anc", "genus", "_rk", "_o"]).drop_duplicates(["anc", "genus"])
           .rename(columns={"anc": "tid", "term_id": "row_term_id", "genus": "name"}))
    unk_rows = a[a["term_id"].isin(subtree(onto, "unknown"))].sort_values(["genus", "_rk", "_o"])
    unk_rows = unk_rows.drop_duplicates("genus").set_index("genus")
    unk = []
    for x in g[g["summary_class"] == "unknown"].itertuples():
        if x.name in unk_rows.index:
            r = unk_rows.loc[x.name]
            unk.append(dict(tid="unknown", name=x.name, domain=r["domain"], row_term_id=r["term_id"],
                            confidence=r["confidence"], evidence=r["evidence"], source=r["source"],
                            species_examples=r["species_examples"], note=r["note"]))
        else:
            unk.append(dict(tid="unknown", name=x.name, domain=None, row_term_id="unknown", confidence="low",
                            evidence="inferred", source="unannotated", species_examples="", note=SYNTHETIC_NOTE))
    cols = ["tid", "name", "domain", "row_term_id", "confidence", "evidence", "source", "species_examples", "note"]
    tg = pd.concat([rep[cols], pd.DataFrame(unk, columns=cols)], ignore_index=True)
    tg["species_examples"] = tg["species_examples"].map(lambda s: _split(s, ";"))
    tg = tg.rename(columns={"tid": "term_id"}).merge(
        g[["name", "phylum", "pct", "reads", "summary_class", "description"]], on="name", how="left")
    tg["_o"] = tg["term_id"].map(order)
    tg = tg.sort_values(["_o", "pct", "name"], ascending=[True, False, True])[TERM_GENERA_COLUMNS].reset_index(drop=True)

    per_term = tg.groupby("term_id")["pct"].agg(["sum", "count"])
    terms = onto[["term_id", "parent_id", "label", "description", "polarity", "depth", "ko_groups"]].copy()
    terms["pct"] = terms["term_id"].map(per_term["sum"]).fillna(0.0)
    terms["n_genera"] = terms["term_id"].map(per_term["count"]).fillna(0).astype(int)

    named = float(g["pct"].sum())
    rows = []
    for cid, label in SUMMARY_CLASSES:
        sub = g[g["summary_class"] == cid]
        pct = float(sub["pct"].sum())
        rows.append(dict(class_id=cid, label=label, pct=pct, pct_of_named=100 * pct / named if named > 0 else 0.0,
                         n_genera=len(sub), top=list(sub["name"].head(3))))
    return RollUp(genera=g, summary=pd.DataFrame(rows), terms=terms, term_genera=tg,
                  annotated_pct=float(g.loc[g["annotated"], "pct"].sum()), named_pct=named,
                  sources=sorted(set(a.loc[a["confidence"].isin(COUNTED), "source"])))
