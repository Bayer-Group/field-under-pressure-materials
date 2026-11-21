"""Follow-up test suggestions for one plot-unit and crop: which measurement would best close a gap in the
crop-risk assessment (see risk.py).

Each suggestion is tied to one gap and one row of rules/followup_tests.csv:

- resolve_species:   a catalogued genus is high for the site and reliably detected; ITS cannot tell species apart.
- confirm_detection: a catalogued genus was found, but only in one of several cores or with very few reads.
- blind_spot:        organisms no dataset here measures (oomycetes, nematodes); always listed for the crop,
                     ranked higher on wet sites when the organism is favoured by wet soil.
- sampling:          the unit has a single core, or too few reads to be scored.

The catalogue is hand-written and its test rows are NOT verified (`verified` = no): suggestions are prompts for
what to ask a diagnostic lab, not validated protocols. No result thresholds are given.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .config import RULES
from .kb import SCORED_CROPS

CATALOGUE_COLUMNS = ["test_id", "kind", "genus", "target", "crops", "disease", "inoculum", "favoured_by", "method",
                     "sample", "tells_you", "source", "verified"]
KINDS = ("species_pcr", "inoculum_count", "blind_spot", "sampling")
HIGH_A = 0.75            # "high for the site": share above three quarters of the comparison samples
WEAK_READS = 10          # a detection with this many reads or fewer is weak
MIN_CORES = 2            # ... as is one seen in fewer cores than this, when the unit has at least this many
WET_P_MAY = 0.5          # share of years with a wet May above which "favoured by wet" tests are raised
WET_DRAINAGE = ("poorly drained", "somewhat poorly drained", "very poorly drained")
HOT_DRY_P = 0.2          # share of years with a hot, dry Jul-Aug above which "favoured by hot_dry" tests are raised
BLIND_BASE, CONTEXT_BONUS = 0.35, 0.25
SUGGESTION_KEYS = ["test_id", "kind", "trigger", "priority", "genus", "target", "disease", "method", "sample",
                   "tells_you", "reason", "inoculum", "source", "verified"]


def load_catalogue(path: Path = RULES / "followup_tests.csv") -> pd.DataFrame:
    """The test catalogue. Raises ValueError on unknown kinds or crops, or a pathogen test without a genus."""
    return _catalogue_cached(str(path)).copy()


@lru_cache(maxsize=4)
def _catalogue_cached(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in CATALOGUE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    df = df[CATALOGUE_COLUMNS].apply(lambda s: s.str.strip())
    if df["test_id"].duplicated().any():
        raise ValueError(f"{path}: duplicate test_id")
    bad = sorted(set(df["kind"]) - set(KINDS))
    if bad:
        raise ValueError(f"{path}: unknown kind {bad}")
    crops = {c for cs in df["crops"] for c in cs.split(";") if c}
    if crops - set(SCORED_CROPS):
        raise ValueError(f"{path}: unknown crops {sorted(crops - set(SCORED_CROPS))}")
    needs_genus = df["kind"].isin(["species_pcr", "inoculum_count"]) & (df["genus"] == "")
    if needs_genus.any():
        raise ValueError(f"{path}: {list(df.loc[needs_genus, 'test_id'])} need a genus")
    df["verified"] = df["verified"].str.lower() == "yes"
    return df


def _crops(row) -> set[str]:
    return {c for c in str(row["crops"]).split(";") if c}


def _context_reason(favoured_by: str, context: dict | None) -> str | None:
    """Why the site favours this organism, or None. context: p_wet_may, drainage_class, p_hot_dry_jul_aug."""
    c = context or {}

    def num(k):
        v = c.get(k)
        return None if v is None or pd.isna(v) else float(v)

    if favoured_by == "wet":
        drain = str(c.get("drainage_class") or "").lower()
        if drain in WET_DRAINAGE:
            return f"the soil map unit is {drain}"
        p = num("p_wet_may")
        if p is not None and p >= WET_P_MAY:
            return f"May is wet in {round(100 * p)}% of years here"
    if favoured_by == "hot_dry":
        p = num("p_hot_dry_jul_aug")
        if p is not None and p >= HOT_DRY_P:
            return f"July-August is hot and dry in {round(100 * p)}% of years here"
    return None


def _item(row, trigger: str, priority: float, reason: str) -> dict:
    d = {k: (row[k] if k in row.index else None) for k in SUGGESTION_KEYS}
    d.update(trigger=trigger, priority=round(min(1.0, max(0.0, priority)), 3), reason=reason,
             genus=row["genus"] or None, verified=bool(row["verified"]))
    for k in ("target", "disease", "inoculum"):
        d[k] = d[k] or None
    return d


def _cores(n: int) -> str:
    return f"{n} soil core" + ("" if n == 1 else "s")


def suggest(contributions: pd.DataFrame, summary: pd.DataFrame, unit_id: str, crop: str, *,
            catalogue: pd.DataFrame | None = None, context: dict | None = None) -> list[dict]:
    """Ranked follow-up tests (highest priority first) for one unit and crop.

    contributions / summary are the frames of a risk.CropRiskResult. context is optional site information
    (p_wet_may, drainage_class, p_hot_dry_jul_aug). Priority is 0-1 and only orders the list."""
    cat = load_catalogue() if catalogue is None else catalogue
    by_id = cat.set_index("test_id", drop=False)
    s = summary[(summary["unit_id"] == unit_id) & (summary["crop"] == crop)]
    if s.empty:
        return []
    s = s.iloc[0]
    n_cores = int(s["n_cores"])
    out: list[dict] = []

    if s["status"] == "insufficient_depth":
        if "resequence" in by_id.index:
            out.append(_item(by_id.loc["resequence"], "sampling", 1.0,
                             f"This sample has only {int(s['total_reads'])} fungal DNA reads, too few to score any "
                             "crop. Nothing else can be suggested from it."))
        return out
    if n_cores == 1 and "more_cores" in by_id.index:
        out.append(_item(by_id.loc["more_cores"], "sampling", 1.0,
                         "This plot was sampled with a single soil core, so no detection here could be checked "
                         "against a second core."))

    c = contributions[(contributions["unit_id"] == unit_id) & (contributions["crop"] == crop)]
    c = c.set_index("genus", drop=False)
    max_rec = float(c["n_records_on_crop"].astype(float).max()) if len(c) else 0.0

    for _, row in cat.iterrows():
        if crop not in _crops(row):
            continue
        ctx = _context_reason(row["favoured_by"], context)
        if row["kind"] == "blind_spot":
            reason = f"{ctx[0].upper()}{ctx[1:]}, which favours it." if ctx else ""
            out.append(_item(row, "blind_spot", BLIND_BASE + (CONTEXT_BONUS if ctx else 0.0), reason))
            continue
        if row["kind"] not in ("species_pcr", "inoculum_count") or row["genus"] not in c.index:
            continue
        g = c.loc[row["genus"]]
        if g["detection_status"] != "detected":
            continue
        reads, n_det, a = int(g["reads"]), int(g["n_cores_detected"]), float(g["a"])
        rec = float(g["n_records_on_crop"] or 0)
        evidence = math.log1p(rec) / math.log1p(max_rec) if max_rec > 0 else 0.0     # 0-1 within this crop
        soil = 1.0 if row["inoculum"] == "soil" else 0.8
        bonus = 0.1 if ctx else 0.0
        name = str(row["genus"]).replace("_", " ")
        weak = reads <= WEAK_READS or (n_cores >= MIN_CORES and n_det < MIN_CORES)
        if weak:
            reason = (f"{name} was found in {n_det} of {_cores(n_cores)} with {reads} "
                      f"read{'' if reads == 1 else 's'}: a weak detection that a targeted test can confirm or rule out.")
            out.append(_item(row, "confirm_detection", 0.5 * (0.5 + 0.5 * evidence) * soil + bonus, reason))
        elif a >= HIGH_A:
            reason = (f"{name} is high for this site (above {round(100 * a)}% of comparison samples), found in "
                      f"{n_det} of {_cores(n_cores)}. DNA sequencing here cannot tell its species apart; "
                      f"{int(g['n_species_on_crop'])} of its {int(g['n_species_documented'])} documented species "
                      "are recorded on this crop.")
            if ctx:
                reason += f" Also, {ctx}, which favours the disease."
            out.append(_item(row, "resolve_species", a * (0.5 + 0.5 * evidence) * soil + bonus, reason))
    # a weak sample limits every other suggestion, so it always comes first
    return sorted(out, key=lambda d: (d["trigger"] != "sampling", -d["priority"], d["test_id"]))
