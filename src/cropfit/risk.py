"""Crop-risk calculator from NEON ITS fungi: risk(unit, crop) = sum_g A(unit, g) * H(g, crop).

- unit = (site, plotID, year, product): all QC-passing horizon-M cores of one plot-year-ITS product.
- A = mid-rank percentile (0-1) of the genus share against a reference set (same site and ITS product, all years,
  depth-OK units, target included).
- H = share of the genus's USDA-documented species with a host record on the crop (see kb.py).

Everything is explainable: per-genus contributions plus a skip table. The index is relative, not a probability.
All functions are pure; `compute_crop_risk` loads data from disk only when core / kb are not passed.
"""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import neon
from .config import PROCESSED
from .kb import (EXCLUDED_CROP_GROUPS, KB, NON_FUNGAL_PHYLA, OOMYCETE_GENERA, SCORED_CROPS, canonical_genus,
                 normalise_genus)

SCHEMA_VERSION = "crop_risk/1"
STALE_HINT = "re-run scripts/02b_build_neon_features.py"

SUMMARY_COLUMNS = ["site", "year", "plotID", "product", "unit_id", "crop", "risk_index", "status",
                   "risk_from_detected", "risk_from_not_detected", "h_sum_scored", "n_genera_scored",
                   "n_genera_contributing", "n_genera_not_detected", "n_genera_skipped_depth", "top_genus",
                   "top_contribution", "total_reads", "n_cores", "collect_dates", "reference_n_min",
                   "reference_n_max", "small_reference"]
CONTRIBUTION_COLUMNS = ["site", "year", "plotID", "product", "unit_id", "crop", "genus", "genus_members",
                        "detection_status", "reads", "total_reads", "share_pct", "n_cores", "n_cores_detected",
                        "s_typ_pct", "expected_reads", "percentile", "a", "reference_n", "reference_years",
                        "reference_definition", "small_reference", "h", "n_species_documented",
                        "n_species_on_crop", "species_on_crop", "n_records_on_crop",
                        "n_genus_only_records_on_crop", "ft_primary_lifestyle", "ft_secondary_lifestyle",
                        "ft_passed_by", "contribution"]
SKIPPED_COLUMNS = ["site", "year", "plotID", "product", "unit_id", "genus", "reason", "reads", "total_reads",
                   "expected_reads", "detail"]

FORMULA = "risk = sum_g A(p,g) * H(g,c)"
INDEX_TYPE = "relative risk index, not a probability of disease"
REFERENCE_DEFINITION = "same site, same ITS product, all years, depth-OK units incl. target"
SAME_HOST_TAXA_AS = {"spring_wheat": "winter_wheat"}

CAVEATS = [
    "The risk index is a relative score, not a probability of disease or of yield loss.",
    "Abundance is relative abundance at genus level from ITS amplicon reads (compositional, not absolute "
    "biomass or cell counts); species and pathogenic strains within a genus are not resolved.",
    "A USDA host record means a species of the genus can infect the crop somewhere in the world; it does not "
    "show disease in this field.",
    "Fungi only: bacteria and other non-fungal pathogens are out of scope.",
    "Pythium, Phytophthora and Aphanomyces are oomycete genera, not measured by fungal ITS primers, and are excluded.",
    "ITS products DP1.10081.001 and DP1.10081.002 (.001 and .002) are not comparable; references never mix them.",
    "Genera not detected in a unit but depth-adequate contribute their mid-rank percentile (a tie of zeros "
    "gets the average rank, so often about 0.4 to 0.5); see risk_from_not_detected. Genera never detected in "
    "the whole reference are not scored.",
    "USDA Fungus-Host snapshot dated 2021-11-05; records are worldwide (no country filter) and there is no "
    "species synonymy (dual names can double-count).",
    "Note that totals are comparable only within one site and ITS product (reference sets and scored genera "
    "differ between sites and products).",
]

_OK_STATUS = ("detected", "not_detected")


# --------------------------------------------------------------------------------------------- input

def load_core_genus(path: Path = PROCESSED / "its_core_genus.parquet") -> pd.DataFrame:
    """Read the core-level ITS table; raises with a re-run hint when it is missing or stale (no `product`)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; {STALE_HINT}")
    df = pd.read_parquet(path)
    if "product" not in df.columns:
        raise KeyError(f"{path} has no `product` column (stale file); {STALE_HINT}")
    return df


# --------------------------------------------------------------------------------------------- units

def _build(core: pd.DataFrame, synonyms: dict[str, str]):
    """Implementation of build_units; also returns info (notes, canonical -> member aliases)."""
    notes: list[str] = []
    df = core.copy()
    if "horizon" in df.columns and (df["horizon"] == "M").any():
        df = df[df["horizon"] == "M"]
    if "sequenceCountQF" in df.columns:
        df = df[df["sequenceCountQF"] != "Below threshold"]
    else:
        notes.append("sequenceCountQF column missing: all cores treated as QC-OK")
    if "product" not in df.columns:
        raise KeyError(f"core table has no `product` column; {STALE_HINT}")
    df = df.copy()
    df["year"] = pd.to_datetime(df["collectDate"]).dt.year.astype(int)
    df["_date"] = pd.to_datetime(df["collectDate"]).dt.date.astype(str)
    df["product"] = df["product"].fillna("").astype(str)

    cores = (df.drop_duplicates("dnaSampleID")[["site", "plotID", "year", "product", "dnaSampleID", "_date",
                                                "total_reads"]]
             .reset_index(drop=True))
    cores["unit_id"] = cores["plotID"] + "|" + cores["year"].astype(str) + "|" + cores["product"]

    df["canonical"] = [canonical_genus(g, synonyms) for g in df["genus"]]
    dropped = df[df["canonical"].isna()]
    if len(dropped):
        notes.append(f"{int(dropped['reads'].sum())} reads in {len(dropped)} core x genus rows have no usable "
                     "genus (unclassified/placeholder) and count only in total_reads")
    classified = df.dropna(subset=["canonical"])
    members: dict[str, list[str]] = {}
    for can, g in classified.groupby("canonical")["genus"]:
        members[can] = sorted({normalise_genus(x) for x in g if normalise_genus(x)})

    cg = (classified.groupby(["dnaSampleID", "canonical"])["reads"].sum().rename("reads").reset_index()
          .rename(columns={"canonical": "genus"}))
    cg = cg.merge(cores[["dnaSampleID", "unit_id", "total_reads"]], on="dnaSampleID")
    cg["core_share"] = np.where(cg["total_reads"] > 0, 100 * cg["reads"] / cg["total_reads"], 0.0)

    units = (cores.groupby(["site", "plotID", "year", "product", "unit_id"], sort=True)
             .agg(total_reads=("total_reads", "sum"), n_cores=("dnaSampleID", "nunique"),
                  collect_dates=("_date", lambda s: "; ".join(sorted(set(s)))))
             .reset_index())
    pos = cg[cg["reads"] > 0]
    shares = (pos.groupby(["unit_id", "genus"])
              .agg(reads=("reads", "sum"), core_share_sum=("core_share", "sum"),
                   n_cores_detected=("dnaSampleID", "nunique")).reset_index())
    shares = shares.merge(units[["unit_id", "n_cores"]], on="unit_id")
    shares["share_pct"] = shares["core_share_sum"] / shares["n_cores"]
    shares = shares[["unit_id", "genus", "reads", "share_pct", "n_cores_detected"]]
    return units, shares, {"notes": notes, "members": members}


def build_units(core: pd.DataFrame, synonyms: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate core-level reads into units (site, plotID, year, product).

    Keeps horizon M if present, drops "Below threshold" cores, merges synonyms before computing shares.
    Unit share = zero-filled mean of per-core shares. Returns (units, shares long [unit_id, genus, reads,
    share_pct, n_cores_detected])."""
    units, shares, _ = _build(core, synonyms)
    return units, shares


def _floor_units(units: pd.DataFrame, min_unit_reads: int) -> pd.DataFrame:
    return units[units["total_reads"] >= min_unit_reads]


# --------------------------------------------------------------------------------------------- depth

def typical_share(shares: pd.DataFrame, units: pd.DataFrame, min_unit_reads: int) -> pd.DataFrame:
    """s_typ per (site, product, genus): median non-zero share over floor-passing units; NaN if < 3 units."""
    fl = _floor_units(units, min_unit_reads)[["unit_id", "site", "product"]]
    d = shares[shares["reads"] > 0].merge(fl, on="unit_id")
    out = (d.groupby(["site", "product", "genus"])["share_pct"]
           .agg(s_typ_pct="median", n_units_detected="count").reset_index())
    out.loc[out["n_units_detected"] < 3, "s_typ_pct"] = np.nan
    return out


def scored_genera(shares: pd.DataFrame, units: pd.DataFrame, allowed: set[str], min_unit_reads: int) -> pd.DataFrame:
    """G(site, product): allowed canonical genera with reads > 0 in >= 1 floor-passing unit. [site, product, genus]"""
    fl = _floor_units(units, min_unit_reads)[["unit_id", "site", "product"]]
    d = shares[(shares["reads"] > 0) & shares["genus"].isin(allowed)].merge(fl, on="unit_id")
    return d[["site", "product", "genus"]].drop_duplicates().sort_values(["site", "product", "genus"],
                                                                         ignore_index=True)


def depth_status(shares, units, s_typ, genera, min_unit_reads, min_expected_reads) -> pd.DataFrame:
    """Status of every (unit, genus in G(site, product)).

    status: insufficient_depth_unit (unit below floor), detected (reads > 0, never depth-skipped),
    insufficient_depth (reads 0 and expected reads < min_expected_reads), not_detected. `genera` is the
    [site, product, genus] table of scored genera."""
    base = units[["unit_id", "site", "plotID", "year", "product", "total_reads", "n_cores"]].merge(
        genera, on=["site", "product"])
    d = base.merge(shares[["unit_id", "genus", "reads", "share_pct", "n_cores_detected"]],
                   on=["unit_id", "genus"], how="left")
    d = d.fillna({"reads": 0, "share_pct": 0.0, "n_cores_detected": 0})
    d = d.merge(s_typ, on=["site", "product", "genus"], how="left")
    d["expected_reads"] = d["total_reads"] * d["s_typ_pct"] / 100
    status = np.where(d["total_reads"] < min_unit_reads, "insufficient_depth_unit",
                      np.where(d["reads"] > 0, "detected",
                               np.where(d["expected_reads"] < min_expected_reads, "insufficient_depth",
                                        "not_detected")))
    d["status"] = status
    d["n_cores_detected"] = d["n_cores_detected"].astype(int)
    return d.reset_index(drop=True)


# --------------------------------------------------------------------------------------------- A and H

def abundance_scores(shares, units, status, target_units, min_reference, hard_min_reference) -> pd.DataFrame:
    """A per (target unit, genus) with status detected / not_detected.

    Reference = depth-OK units (detected or not_detected for the genus) of the same site and product, all
    years, target included. Columns: unit_id, genus, percentile, a, reference_n, reference_years,
    small_reference, reference_too_small. A is NaN when reference_n < hard_min_reference."""
    ok = status[status["status"].isin(_OK_STATUS)]
    tgt = ok[ok["unit_id"].isin(set(target_units))]
    rows = []
    for key, tg in tgt.groupby(["site", "product", "genus"]):
        ref = ok[(ok["site"] == key[0]) & (ok["product"] == key[1]) & (ok["genus"] == key[2])]
        n = len(ref)
        years = "; ".join(str(y) for y in sorted(ref["year"].unique()))
        pct = neon.percentile_rank(tg["share_pct"], ref["share_pct"])
        for (_, r), p in zip(tg.iterrows(), pct):
            too_small = n < hard_min_reference
            rows.append({"unit_id": r["unit_id"], "genus": key[2],
                         "percentile": np.nan if too_small else float(p),
                         "a": np.nan if too_small else float(p) / 100.0,
                         "reference_n": n, "reference_years": years,
                         "small_reference": n < min_reference, "reference_too_small": too_small})
    cols = ["unit_id", "genus", "percentile", "a", "reference_n", "reference_years", "small_reference",
            "reference_too_small"]
    return pd.DataFrame(rows, columns=cols)


def host_scores(host: pd.DataFrame, genera, crops) -> pd.DataFrame:
    """H table for genera x crops. A documented genus without a row for a crop gets h = 0 (n_documented taken
    from its other rows); undocumented genera are absent from `host` and must not be passed in."""
    h = host[host["genus"].isin(set(genera)) & host["crop_group"].isin(set(crops))]
    documented = host.groupby("genus")["n_species_documented"].max()
    grid = pd.MultiIndex.from_product([sorted(set(genera)), list(crops)], names=["genus", "crop_group"]).to_frame(
        index=False)
    out = grid.merge(h.drop(columns=["source_version"], errors="ignore"), on=["genus", "crop_group"], how="left")
    miss = out["h"].isna()
    out.loc[miss, "h"] = 0.0
    out.loc[miss, "n_species_on_crop"] = 0
    out.loc[miss, "n_records_on_crop"] = 0
    out.loc[miss, "n_genus_only_records_on_crop"] = 0
    out["n_species_documented"] = out["n_species_documented"].fillna(out["genus"].map(documented))
    out["species_on_crop"] = out["species_on_crop"].fillna("")
    return out.rename(columns={"crop_group": "crop"})


def _genus_info(kb: KB) -> pd.DataFrame:
    """Per canonical genus: passes (any row), exclusion reason, lifestyles joined with '|'."""
    g = kb.genera.dropna(subset=["canonical_genus"])

    def join(s):
        return "|".join(dict.fromkeys(str(x) for x in s if pd.notna(x) and str(x) != ""))

    rows = []
    for can, grp in g.groupby("canonical_genus"):
        passes = bool(grp["passes_filter"].astype(bool).any())
        reasons = set(grp["exclusion_reason"].dropna())
        nonfungal = grp["phylum"].isin(NON_FUNGAL_PHYLA).all() or ("non_fungal" in reasons and not passes)
        rows.append({"genus": can, "passes": passes,
                     "excl_reason": None if passes else ("non_fungal" if nonfungal else "excluded_by_filter"),
                     "ft_primary_lifestyle": join(grp["primary_lifestyle"]),
                     "ft_secondary_lifestyle": join(grp["secondary_lifestyle"]),
                     "ft_passed_by": join(grp["passed_by"])})
    return pd.DataFrame(rows, columns=["genus", "passes", "excl_reason", "ft_primary_lifestyle",
                                       "ft_secondary_lifestyle", "ft_passed_by"]).set_index("genus", drop=False).rename_axis(None)


def combine(a: pd.DataFrame, h: pd.DataFrame, genera_tbl: pd.DataFrame, status: pd.DataFrame,
            units: pd.DataFrame, members: dict[str, list[str]], kb_info: pd.DataFrame) -> pd.DataFrame:
    """Contributions: one row per unit x crop x scored genus with finite A (H = 0 rows included)."""
    a = a[a["a"].notna()]
    st = status[["unit_id", "genus", "status", "reads", "share_pct", "n_cores_detected", "s_typ_pct",
                 "expected_reads"]]
    d = a.merge(st, on=["unit_id", "genus"]).merge(
        units[["unit_id", "site", "year", "plotID", "product", "total_reads", "n_cores"]], on="unit_id")
    d = d.merge(h, on="genus")
    d = d.rename(columns={"status": "detection_status"})
    d["reference_definition"] = ("same site (" + d["site"] + ") and ITS product (" + d["product"] +
                                 "), all years, units passing the depth floor and depth-OK for this genus, "
                                 "target included")
    d["genus_members"] = d["genus"].map(lambda g: "; ".join(members.get(g, [g])))
    d = d.merge(kb_info[["genus", "ft_primary_lifestyle", "ft_secondary_lifestyle", "ft_passed_by"]],
                on="genus", how="left")
    d["contribution"] = d["a"] * d["h"]
    for c in CONTRIBUTION_COLUMNS:
        if c not in d:
            d[c] = np.nan
    return d[CONTRIBUTION_COLUMNS].sort_values(["unit_id", "crop", "genus"], ignore_index=True)


# --------------------------------------------------------------------------------------------- skipped

def _skip_rows(units_row, genus, reason, reads, expected, detail) -> dict:
    return {"site": units_row["site"], "year": units_row["year"], "plotID": units_row["plotID"],
            "product": units_row["product"], "unit_id": units_row["unit_id"], "genus": genus, "reason": reason,
            "reads": reads, "total_reads": units_row["total_reads"], "expected_reads": expected, "detail": detail}


def skipped_table(target: pd.DataFrame, shares: pd.DataFrame, units: pd.DataFrame, status: pd.DataFrame,
                  abund: pd.DataFrame, kb_info: pd.DataFrame, host_genera: set[str], scored: pd.DataFrame,
                  min_unit_reads: int, min_expected_reads: float, watch_genera: set[str]) -> pd.DataFrame:
    """Per target unit (not per crop) list of everything left out and why."""
    rows = []
    fl = _floor_units(units, min_unit_reads)
    stt = status.set_index(["unit_id", "genus"])
    scored_set = set(map(tuple, scored[["site", "product", "genus"]].itertuples(index=False, name=None)))
    sh = {u: g for u, g in shares[shares["reads"] > 0].groupby("unit_id")}
    small = abund[abund["reference_too_small"]].set_index(["unit_id", "genus"])
    for _, u in target.iterrows():
        if u["total_reads"] < min_unit_reads:
            rows.append(_skip_rows(u, None, "insufficient_depth_unit", np.nan, np.nan,
                                   f"total_reads {int(u['total_reads'])} < unit floor {min_unit_reads}"))
            continue
        sp = fl[(fl["site"] == u["site"]) & (fl["product"] == u["product"])]
        # scored-genus skips
        s_u = status[(status["unit_id"] == u["unit_id"]) & (status["status"] == "insufficient_depth")]
        for _, r in s_u.iterrows():
            rows.append(_skip_rows(u, r["genus"], "insufficient_depth", 0, r["expected_reads"],
                                   f"0 reads; expected {r['expected_reads']:.2f} < {min_expected_reads} "
                                   f"(total_reads {int(u['total_reads'])} x typical share {r['s_typ_pct']:.3g}%)"))
        for (uid, g), r in small[small.index.get_level_values(0) == u["unit_id"]].iterrows():
            srow = stt.loc[(uid, g)]
            rows.append(_skip_rows(u, g, "reference_too_small", srow["reads"], srow["expected_reads"],
                                   f"reference_n {int(r['reference_n'])} below hard minimum"))
        # detected genera that are not scored
        d = sh.get(u["unit_id"])
        if d is not None:
            for _, r in d.iterrows():
                g = r["genus"]
                if g in OOMYCETE_GENERA:
                    reason, detail = "oomycete", "oomycete: not a fungus, ITS fungal primers do not measure it"
                elif g not in kb_info.index:
                    reason, detail = "not_in_fungaltraits", "genus not found in FungalTraits"
                elif not kb_info.at[g, "passes"]:
                    reason = kb_info.at[g, "excl_reason"] or "excluded_by_filter"
                    detail = (f"primary lifestyle {kb_info.at[g, 'ft_primary_lifestyle'] or 'NA'}; "
                              f"secondary {kb_info.at[g, 'ft_secondary_lifestyle'] or 'NA'}")
                elif g not in host_genera:
                    reason, detail = "no_usda_host_records", "plant-pathogen genus without USDA host records"
                else:
                    continue
                rows.append(_skip_rows(u, g, reason, r["reads"], np.nan, detail))
        # watched genera never seen in the reference
        seen = set(shares[shares["unit_id"].isin(sp["unit_id"]) & (shares["reads"] > 0)]["genus"])
        for g in sorted(watch_genera - seen):
            if g in OOMYCETE_GENERA or g not in kb_info.index or not kb_info.at[g, "passes"]:
                continue
            rows.append(_skip_rows(u, g, "not_detected_in_reference", 0, np.nan,
                                   f"not detected in any of {len(sp)} reference units"))
    out = pd.DataFrame(rows, columns=SKIPPED_COLUMNS)
    return out.sort_values(["unit_id", "reason", "genus"], na_position="first", ignore_index=True)


# --------------------------------------------------------------------------------------------- summary

def summarise(contrib: pd.DataFrame, units: pd.DataFrame, target_units: pd.DataFrame, crops,
              skipped: pd.DataFrame, min_unit_reads: int) -> pd.DataFrame:
    """One row per target unit x crop."""
    base = target_units.merge(pd.DataFrame({"crop": list(crops)}), how="cross")
    c = contrib.copy()
    c["_det"] = np.where(c["detection_status"] == "detected", c["contribution"], 0.0)
    c["_nd"] = np.where(c["detection_status"] == "not_detected", c["contribution"], 0.0)
    c["_pos"] = (c["contribution"] > 0).astype(int)
    c["_notdet"] = (c["detection_status"] == "not_detected").astype(int)
    agg = c.groupby(["unit_id", "crop"]).agg(
        risk_index=("contribution", "sum"), risk_from_detected=("_det", "sum"),
        risk_from_not_detected=("_nd", "sum"), h_sum_scored=("h", "sum"), n_genera_scored=("genus", "count"),
        n_genera_contributing=("_pos", "sum"), n_genera_not_detected=("_notdet", "sum"),
        reference_n_min=("reference_n", "min"), reference_n_max=("reference_n", "max"),
        small_reference=("small_reference", "any")).reset_index()
    top = (c[c["contribution"] > 0].sort_values("contribution", ascending=False)
           .drop_duplicates(["unit_id", "crop"])[["unit_id", "crop", "genus", "contribution"]]
           .rename(columns={"genus": "top_genus", "contribution": "top_contribution"}))
    d = base.merge(agg, on=["unit_id", "crop"], how="left").merge(top, on=["unit_id", "crop"], how="left")
    depth_skips = (skipped[skipped["reason"] == "insufficient_depth"].groupby("unit_id").size()
                   .rename("n_genera_skipped_depth"))
    d = d.merge(depth_skips, left_on="unit_id", right_index=True, how="left")
    below = d["total_reads"] < min_unit_reads
    no_g = d["n_genera_scored"].isna()
    no_k = ~no_g & (d["h_sum_scored"].fillna(0) <= 0)
    d["status"] = np.select([below, no_g, no_k], ["insufficient_depth", "no_scored_genera", "no_knowledge"], "ok")
    nan_rows = d["status"] != "ok"
    for col in ("risk_index", "risk_from_detected", "risk_from_not_detected"):
        d.loc[nan_rows, col] = np.nan
    for col in ("n_genera_scored", "n_genera_contributing", "n_genera_not_detected", "n_genera_skipped_depth"):
        d[col] = d[col].fillna(0).astype(int)
    d["small_reference"] = d["small_reference"].fillna(False).astype(bool)
    d.loc[no_g | below, "h_sum_scored"] = np.nan
    return d[SUMMARY_COLUMNS].sort_values(["unit_id", "crop"], ignore_index=True)


# --------------------------------------------------------------------------------------------- result

def _jsonable(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_jsonable(x) for x in (sorted(v) if isinstance(v, (set, frozenset)) else v)]
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, (pd.Timestamp, _dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, Path):
        return str(v)
    return v


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _jsonable(v) for k, v in r.items()} for r in df.astype(object).to_dict("records")]


@dataclass(frozen=True)
class CropRiskResult:
    site: str
    year: int
    summary: pd.DataFrame
    contributions: pd.DataFrame
    skipped: pd.DataFrame
    metadata: dict

    @property
    def empty(self) -> bool:
        return self.summary.empty

    def to_dict(self) -> dict:
        """JSON-safe dict (NaN -> None, numpy -> python, dates -> ISO); passes json.dumps(allow_nan=False)."""
        return {"schema_version": SCHEMA_VERSION, "site": self.site, "year": int(self.year),
                "metadata": _jsonable(self.metadata),
                "columns": {"summary": list(SUMMARY_COLUMNS), "contributions": list(CONTRIBUTION_COLUMNS),
                            "skipped": list(SKIPPED_COLUMNS)},
                "summary": _records(self.summary), "contributions": _records(self.contributions),
                "skipped": _records(self.skipped)}


def _metadata(site, year, kb, params, crops, units, notes, reason) -> dict:
    products = sorted(units["product"].unique()) if len(units) else []
    n_low = int((units["total_reads"] < params["min_unit_reads"]).sum()) if len(units) else 0
    return {"schema_version": SCHEMA_VERSION, "formula": FORMULA, "index_type": INDEX_TYPE,
            "parameters": dict(params), "crops_scored": list(crops), "crops_excluded": dict(EXCLUDED_CROP_GROUPS),
            "same_host_taxa_as": dict(SAME_HOST_TAXA_AS), "reference_definition": REFERENCE_DEFINITION,
            "products": products, "n_units": int(len(units)), "n_units_insufficient_depth": n_low,
            "kb": kb.meta, "synonyms": dict(kb.synonyms), "caveats": list(CAVEATS), "notes": list(notes),
            "reason": reason, "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}


def _empty_result(site, year, kb, params, crops, reason, notes) -> CropRiskResult:
    return CropRiskResult(site, int(year), pd.DataFrame(columns=SUMMARY_COLUMNS),
                          pd.DataFrame(columns=CONTRIBUTION_COLUMNS), pd.DataFrame(columns=SKIPPED_COLUMNS),
                          _metadata(site, year, kb, params, crops, pd.DataFrame(columns=["product", "total_reads"]),
                                    notes, reason))


def compute_crop_risk(site: str, year: int, *, core: pd.DataFrame | None = None, kb: KB | None = None,
                      crops=SCORED_CROPS, min_unit_reads: int = 2000, min_expected_reads: float = 3.0,
                      min_reference: int = 10, hard_min_reference: int = 5) -> CropRiskResult:
    """Score every crop x every sampled plot-unit of one site-year. Never raises for a site-year without data:
    returns an empty result whose metadata["reason"] says what is available."""
    if kb is None:
        from .kb import load_kb  # lazy: needs built KB tables
        kb = load_kb()
    if core is None:
        core = load_core_genus()
    elif "product" not in core.columns:
        raise KeyError(f"core table has no `product` column; {STALE_HINT}")
    crops = tuple(crops)
    params = {"min_unit_reads": min_unit_reads, "min_expected_reads": min_expected_reads,
              "min_reference": min_reference, "hard_min_reference": hard_min_reference}

    site_core = core[core["site"] == site]
    units, shares, info = _build(site_core, kb.synonyms) if len(site_core) else (None, None, None)
    if units is None or not (units["year"] == year).any():
        years = pd.to_datetime(core["collectDate"]).dt.year
        avail = sorted({f"{s} {y}" for s, y in zip(core["site"], years)})
        return _empty_result(site, year, kb, params, crops,
                             f"no ITS units for {site} {year}; available: {avail}", [])

    notes = list(info["notes"])
    target = units[units["year"] == year].reset_index(drop=True)

    kb_info = _genus_info(kb)
    host_genera = set(kb.host["genus"])
    allowed = {g for g in kb_info.index if kb_info.at[g, "passes"] and g not in OOMYCETE_GENERA
               and g in host_genera}
    scored = scored_genera(shares, units, allowed, min_unit_reads)
    s_typ = typical_share(shares, units, min_unit_reads)
    status = depth_status(shares, units, s_typ, scored, min_unit_reads, min_expected_reads)
    abund = abundance_scores(shares, units, status, set(target["unit_id"]), min_reference, hard_min_reference)
    h = host_scores(kb.host, set(scored["genus"]), crops)
    contrib = combine(abund, h, scored, status, units, info["members"], kb_info)

    watch = {canonical_genus(g, kb.synonyms) for g in neon.GENERA} | set(kb.synonyms.values())
    skipped = skipped_table(target, shares, units, status, abund, kb_info, host_genera, scored,
                            min_unit_reads, min_expected_reads, {w for w in watch if w})
    summary = summarise(contrib, units, target, crops, skipped, min_unit_reads)

    md = _metadata(site, year, kb, params, crops, units, notes, None)
    md["n_units"] = int(len(target))
    md["n_units_insufficient_depth"] = int((target["total_reads"] < min_unit_reads).sum())
    md["products"] = sorted(target["product"].unique())
    return CropRiskResult(site, int(year), summary, contrib, skipped, md)
