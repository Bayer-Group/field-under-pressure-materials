"""Product recommendations for one plot-unit and crop: which plant protection products, fertilisers and
biologicals are worth considering before planting and during growth, given what was found in the soil.

Each recommendation is tied to one row of rules/products.csv and one trigger:

- pathogen_high:  a catalogued genus is high for the site and reliably detected (crop risk, see risk.py). ITS
                  cannot tell species apart, so the item names the follow-up tests that would confirm it.
- confirm_first:  the genus was found, but weakly (one of several cores, or very few reads): test before buying.
- site_favoured:  an organism no dataset here measures (oomycetes), on a site that favours it (wet). Without
                  that context nothing is recommended for an unmeasured organism.
- soil_signal:    a soil measurement, a gene group or the crop history of the same plot (the `signals` dict).

Rows of category `no_product` say that no product works and what to do instead; `caution` and `note` rows change
how a product choice should be read. Nematodes are left to the follow-up tests (followup.py).

The catalogue is hand-written and NOT verified (`verified` = no): items name product classes, never brands or
rates, and are prompts for a talk with an agronomist. Registration differs by country and the label is binding.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import followup
from .config import RULES
from .followup import HIGH_A, MIN_CORES, WEAK_READS
from .kb import SCORED_CROPS

CATALOGUE_COLUMNS = ["product_id", "kind", "category", "product_class", "timing", "stage", "crops", "genus", "tests",
                     "signal", "favoured_by", "works_because", "caution", "source", "verified"]
KINDS = ("pathogen", "blind_spot", "soil")
CATEGORIES = ("fungicide_seed", "fungicide_foliar", "biocontrol", "fertiliser", "inhibitor", "inoculant",
              "amendment", "no_product", "caution", "note")
TIMINGS = ("before_planting", "during_growth")
RECOMMENDATION_KEYS = ["product_id", "category", "product_class", "timing", "stage", "trigger", "priority", "basis",
                       "confidence", "genus", "reason", "works_because", "caution", "confirm_with", "source",
                       "verified"]

# Thresholds on the soil sample; the same values as the soil functions cards (api_functions.py), kept equal by a test.
NITRATE_ENOUGH, NITRATE_LOW = 25.0, 10.0   # mg/kg nitrate-N, late-spring soil nitrate test for corn
CN_IMMOBILISE = 20.0                       # C:N above this: microbes lock up nitrogen
PH_STRONGLY_ACIDIC, PH_ALKALINE = 5.5, 7.5
PH_LEGUME = 6.0                            # below this, legume nodules fix less nitrogen
OC_LOW = 1.0                               # % organic carbon
LOW_GENUS_PCT = 0.25                       # Bradyrhizobium read share in the lowest quarter of the site-year
CONFIRM_BASE, SITE_PRIORITY, CONTEXT_BONUS = 0.4, 0.5, 0.1
NO_DATA = object()                         # a soil rule that could not be evaluated


def _val(signals: dict | None, key: str):
    v = (signals or {}).get(key)
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def _status(signals, key):
    """A gene group's status; 'too_few_genes' and missing both mean it cannot be read."""
    v = _val(signals, key)
    return None if v in (None, "too_few_genes") else v


def _nitrate_low(sig, ctx):
    v = _val(sig, "nitrate_n_mgkg")
    if v is None:
        return NO_DATA
    if v >= NITRATE_ENOUGH:
        return None
    how = "well below" if v < NITRATE_LOW else "below"
    return (0.9 if v < NITRATE_LOW else 0.6,
            f"Soil nitrate-N is {v:g} mg/kg, {how} the {NITRATE_ENOUGH:g} mg/kg at which corn needs no more nitrogen.")


def _cn_high(sig, ctx):
    v = _val(sig, "cn_ratio")
    if v is None:
        return NO_DATA
    if v <= CN_IMMOBILISE:
        return None
    return 0.5, f"The soil's C:N ratio is {v:.0f}, above {CN_IMMOBILISE:g}: microbes tend to lock up nitrogen."


def _ph_rule(test, strength, text):
    def rule(sig, ctx):
        v = _val(sig, "ph")
        if v is None:
            return NO_DATA
        return (strength, f"Soil pH is {v:.1f}: {text}.") if test(v) else None
    return rule


def _oc_low(sig, ctx):
    v = _val(sig, "organic_c_pct")
    if v is None:
        return NO_DATA
    return (0.4, f"Organic carbon is {v:.1f}%, below {OC_LOW:g}%: little organic matter.") if v < OC_LOW else None


def _gene_found(key, strength, text):
    def rule(sig, ctx):
        s = _status(sig, key)
        if s is None:
            return NO_DATA
        return (strength, text) if s == "found" else None
    return rule


def _n_loss(sig, ctx):
    flag, nitr = _val(sig, "n2o_flag"), _status(sig, "nitrification")
    if flag is None and nitr is None:
        return NO_DATA
    if flag:
        return 0.5, "This soil's bacteria carry far more genes that make N2O than genes that remove it."
    wet = followup._context_reason("wet", ctx)
    if nitr == "found" and wet:
        return 0.4, f"Nitrification genes were found and {wet}, so nitrate is easily lost."
    return None


def _legume_new(sig, ctx):
    grown = _val(sig, "crop_in_history")
    if grown is None:
        return NO_DATA
    if grown:
        return None
    reason = "This crop does not appear in the plot's known crop history."
    pct = _val(sig, "bradyrhizobium_pct")
    if pct is not None and pct < LOW_GENUS_PCT and sig.get("crop") == "soybean":
        reason += f" Bradyrhizobium is also low for the site (above {round(100 * pct)}% of comparison samples)."
    return 0.7, reason


# signal name in the catalogue -> (what it rests on, rule). A rule returns (strength 0-1, reason), None when it
# does not fire, or NO_DATA when the values it needs are missing.
SIGNAL_RULES = {
    "nitrate_low": ("measured", _nitrate_low),
    "cn_high": ("measured", _cn_high),
    "ph_strongly_acidic": ("measured", _ph_rule(lambda v: v < PH_STRONGLY_ACIDIC, 0.8, "strongly acidic")),
    "ph_acidic_legume": ("measured", _ph_rule(lambda v: PH_STRONGLY_ACIDIC <= v < PH_LEGUME, 0.5,
                                              "acidic for a legume")),
    "ph_extreme_p": ("measured", _ph_rule(lambda v: v < PH_STRONGLY_ACIDIC or v >= PH_ALKALINE, 0.5,
                                          "outside the range where phosphorus stays available")),
    "ph_alkaline": ("measured", _ph_rule(lambda v: v >= PH_ALKALINE, 0.5, "alkaline")),
    "oc_low": ("measured", _oc_low),
    "urease_found": ("genes", _gene_found("urease", 0.3, "Genes that break down urea were found in this soil.")),
    "n_loss": ("genes", _n_loss),
    "legume_new": ("history", _legume_new),
    "copper_found": ("genes", _gene_found("copper_resistance", 0.2,
                                          "Copper resistance genes were found in this soil's bacteria.")),
    "dapg_found": ("genes", _gene_found("phlD", 0.2, "The DAPG gene phlD was found in this soil's bacteria.")),
}
CONFIDENCE = {"measured": "medium", "genes": "low", "history": "medium", "fungi": "low", "site": "low"}


def load_catalogue(path: Path = RULES / "products.csv") -> pd.DataFrame:
    """The product catalogue. Raises ValueError on unknown kinds, categories, timings, crops, signals or tests."""
    return _catalogue_cached(str(path)).copy()


@lru_cache(maxsize=4)
def _catalogue_cached(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in CATALOGUE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    df = df[CATALOGUE_COLUMNS].apply(lambda s: s.str.strip())
    if df["product_id"].duplicated().any():
        raise ValueError(f"{path}: duplicate product_id")
    for col, allowed in (("kind", KINDS), ("category", CATEGORIES), ("timing", TIMINGS)):
        bad = sorted(set(df[col]) - set(allowed))
        if bad:
            raise ValueError(f"{path}: unknown {col} {bad}")
    crops = {c for cs in df["crops"] for c in cs.split(";") if c}
    if crops - set(SCORED_CROPS):
        raise ValueError(f"{path}: unknown crops {sorted(crops - set(SCORED_CROPS))}")
    if (df["crops"] == "").any():
        raise ValueError(f"{path}: {list(df.loc[df['crops'] == '', 'product_id'])} need crops")
    needs_genus = (df["kind"] == "pathogen") & (df["genus"] == "")
    if needs_genus.any():
        raise ValueError(f"{path}: {list(df.loc[needs_genus, 'product_id'])} need a genus")
    soil = df["kind"] == "soil"
    bad = sorted(set(df.loc[soil, "signal"]) - set(SIGNAL_RULES))
    if bad:
        raise ValueError(f"{path}: unknown signal {bad}")
    blind = df["kind"] == "blind_spot"
    if ((df.loc[blind, "tests"] == "") | (df.loc[blind, "favoured_by"] == "")).any():
        raise ValueError(f"{path}: blind_spot rows need tests and favoured_by")
    tests = {t for ts in df["tests"] for t in ts.split(";") if t}
    known = set(followup.load_catalogue()["test_id"])
    if tests - known:
        raise ValueError(f"{path}: unknown tests {sorted(tests - known)}")
    df["verified"] = df["verified"].str.lower() == "yes"
    return df


def _item(row, trigger: str, priority: float, basis: str, reason: str, confirm_with: list[str]) -> dict:
    d = {k: (row[k] or None) if k in row.index else None for k in RECOMMENDATION_KEYS}
    d.update(trigger=trigger, priority=round(min(1.0, max(0.0, priority)), 3), basis=basis,
             confidence=CONFIDENCE[basis], reason=reason, confirm_with=confirm_with, verified=bool(row["verified"]))
    return d


def _tests_for(tests: pd.DataFrame, genus: str, crop: str) -> list[str]:
    """Follow-up tests that resolve this genus on this crop."""
    m = tests[(tests["genus"] == genus) & tests["crops"].map(lambda cs: crop in cs.split(";"))]
    return list(m["test_id"])


def _soil_rows(cat: pd.DataFrame, crop: str):
    for _, row in cat[cat["kind"] == "soil"].iterrows():
        if crop in followup._crops(row):
            yield row


def recommend(contributions: pd.DataFrame, summary: pd.DataFrame, unit_id: str, crop: str, *,
              signals: dict | None = None, context: dict | None = None,
              catalogue: pd.DataFrame | None = None) -> list[dict]:
    """Ranked product recommendations (highest priority first) for one unit and crop.

    contributions / summary are the frames of a risk.CropRiskResult. signals holds what is known about the soil
    of the same plot; every key is optional: nitrate_n_mgkg, cn_ratio, ph, organic_c_pct, the gene-group statuses
    urease, nitrification, copper_resistance and phlD ("found", "trace", "not_found", "too_few_genes"), n2o_flag,
    crop_in_history (was this crop grown here before) and bradyrhizobium_pct (0-1). context is site information
    (p_wet_may, drainage_class, p_hot_dry_jul_aug). Priority is 0-1 and only orders the list; a rule whose values
    are missing gives no item (see unanswered)."""
    cat = load_catalogue() if catalogue is None else catalogue
    s = summary[(summary["unit_id"] == unit_id) & (summary["crop"] == crop)]
    if s.empty:
        return []
    s = s.iloc[0]
    n_cores = int(s["n_cores"])
    tests = followup.load_catalogue()
    sig = {**(signals or {}), "crop": crop}
    out: list[dict] = []

    c = contributions[(contributions["unit_id"] == unit_id) & (contributions["crop"] == crop)]
    c = c.set_index("genus", drop=False)
    max_rec = float(c["n_records_on_crop"].astype(float).max()) if len(c) else 0.0
    scored = s["status"] != "insufficient_depth"      # too few fungal reads: no genus can be read at all

    for _, row in cat.iterrows():
        if crop not in followup._crops(row):
            continue
        ctx = followup._context_reason(row["favoured_by"], context)
        if row["kind"] == "blind_spot":
            if ctx:
                out.append(_item(row, "site_favoured", SITE_PRIORITY, "site",
                                 f"No dataset in this app measures this organism, but {ctx}, which favours it.",
                                 [t for t in row["tests"].split(";") if t]))
            continue
        if row["kind"] == "soil":
            basis, rule = SIGNAL_RULES[row["signal"]]
            hit = rule(sig, context)
            if hit is not None and hit is not NO_DATA:
                out.append(_item(row, "soil_signal", hit[0], basis, hit[1], []))
            continue
        if not scored or row["genus"] not in c.index:
            continue
        g = c.loc[row["genus"]]
        if g["detection_status"] != "detected":
            continue
        reads, n_det, a = int(g["reads"]), int(g["n_cores_detected"]), float(g["a"])
        rec = float(g["n_records_on_crop"] or 0)
        evidence = math.log1p(rec) / math.log1p(max_rec) if max_rec > 0 else 0.0     # 0-1 within this crop
        bonus = CONTEXT_BONUS if ctx else 0.0
        name = str(row["genus"]).replace("_", " ")
        found = f"found in {n_det} of {followup._cores(n_cores)}"
        confirm = _tests_for(tests, row["genus"], crop)
        if reads <= WEAK_READS or (n_cores >= MIN_CORES and n_det < MIN_CORES):
            reason = (f"{name} was {found} with {reads} read{'' if reads == 1 else 's'}: too weak a detection to "
                      "act on. Confirm it with a targeted test first.")
            out.append(_item(row, "confirm_first", CONFIRM_BASE * (0.5 + 0.5 * evidence) + bonus, "fungi", reason,
                             confirm))
        elif a >= HIGH_A:
            reason = (f"{name} is high for this site (above {round(100 * a)}% of comparison samples), {found}. "
                      "DNA sequencing here names the genus, not the species, so a test should confirm the "
                      "pathogen before a product is chosen.")
            if ctx:
                reason += f" Also, {ctx}, which favours the disease."
            out.append(_item(row, "pathogen_high", a * (0.5 + 0.5 * evidence) + bonus, "fungi", reason, confirm))
    return sorted(out, key=lambda d: (-d["priority"], d["product_id"]))


def unanswered(crop: str, signals: dict | None = None, context: dict | None = None, *,
               catalogue: pd.DataFrame | None = None) -> list[str]:
    """product_ids of the soil rules for this crop that could not be evaluated because their values are missing."""
    cat = load_catalogue() if catalogue is None else catalogue
    sig = {**(signals or {}), "crop": crop}
    return [row["product_id"] for row in _soil_rows(cat, crop)
            if SIGNAL_RULES[row["signal"]][1](sig, context) is NO_DATA]
