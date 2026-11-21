"""GUI API: crop disease risk of one plot (see risk.py). Mounted by api.create_app().

Scores are computed on demand for a site-year (about 1-2 s the first time, cached afterwards) from
its_core_genus.parquet and the knowledge-base tables, never from the precomputed crop_risk_* files (they carry no
metadata and go stale). A *unit* is one plot-year-ITS product, keyed `YYYY-00N` (e.g. `2016-002`). Peers of a unit
are the units of the same site, year and ITS product: the scorer never mixes the two ITS products.
"""
from __future__ import annotations

import threading
from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import api as core
from . import kb as kbmod
from . import config, neon, risk

MIN_UNIT_READS = 2000           # risk.compute_crop_risk default; below this a unit is not scored
CURRENT_PRODUCT = ".002"
MAX_SKIPPED_GENERA = 15
MAX_SPECIES = 10

CROP_LABELS = {"winter_wheat": "Winter wheat", "spring_wheat": "Spring wheat", "barley_oats": "Barley and oats",
               "corn": "Corn", "sorghum": "Sorghum", "millet": "Millet", "soybean": "Soybean",
               "dry_bean": "Dry bean", "sunflower": "Sunflower", "alfalfa": "Alfalfa"}
REASON_LABELS = {
    "insufficient_depth_unit": "Sample too shallow to score",
    "insufficient_depth": "Too few reads to tell if present",
    "excluded_by_filter": "Not a plant pathogen (FungalTraits)",
    "oomycete": "Oomycete, not measured by fungal ITS",
    "non_fungal": "Not a fungus",
    "not_in_fungaltraits": "Not in FungalTraits",
    "no_usda_host_records": "Plant pathogen without USDA host records",
    "not_detected_in_reference": "Never detected at this site with this method",
    "reference_too_small": "Too few comparison samples",
}
KB_NAMES = {"fungaltraits": "FungalTraits", "usda_fungus_host": "USDA Fungus-Host"}
METHOD_LABELS = {"current": "current ITS method (.002)",
                 "older": "older ITS method (.001), not comparable with .002"}

_lock = threading.Lock()


# ---------------------------------------------------------------- response models
class RiskUnitRef(BaseModel):
    unit: str
    year: int
    product: str
    method: str
    method_label: str
    collect_dates: list[str]
    total_reads: int
    n_cores: int
    low_depth: bool


class Peer(BaseModel):
    plot_id: str
    risk_index: float


class CropRiskRow(BaseModel):
    crop: str
    label: str
    status: str
    risk_index: float | None
    from_detected: float | None
    from_not_detected: float | None
    rank: int | None
    n_peers: int
    n_peers_too_shallow: int
    percentile: float | None
    peers: list[Peer]
    top_genus: str | None
    n_genera_contributing: int
    n_genera_not_detected: int
    small_reference: bool
    same_as: str | None


class SkippedGenus(BaseModel):
    genus: str | None
    reads: int | None
    detail: str | None


class SkippedGroup(BaseModel):
    reason: str
    label: str
    n: int
    genera: list[SkippedGenus]
    more: int


class KbSource(BaseModel):
    name: str
    source_version: str | None
    retrieved_utc: str | None
    url: str | None


class PlotCropRisk(RiskUnitRef):
    plot_id: str
    site: str
    n_units_in_group: int
    crops: list[CropRiskRow]
    skipped: list[SkippedGroup]
    caveats: list[str]
    notes: list[str]
    kb: list[KbSource]
    parameters: dict[str, float]
    index_type: str


class Contribution(BaseModel):
    genus: str
    members: list[str]
    detected: bool
    reads: int
    share_pct: float
    a: float
    percentile: float
    reference_n: int
    small_reference: bool
    h: float
    n_species_on_crop: int
    n_species_documented: int
    species_on_crop: list[str]
    n_species_more: int
    n_records_on_crop: int
    lifestyle: str | None
    passed_by: str | None
    contribution: float


class CropContributions(BaseModel):
    plot_id: str
    unit: str
    crop: str
    label: str
    row: CropRiskRow
    contributions: list[Contribution]
    n_scored_zero_h: int


# ---------------------------------------------------------------- helpers
def _num(v, nd: int = 4) -> float | None:
    if v is None or pd.isna(v):
        return None
    return round(float(v), nd)


def _int(v) -> int:
    return 0 if v is None or pd.isna(v) else int(v)


def _str(v) -> str | None:
    return None if v is None or pd.isna(v) or v == "" else str(v)


def _core_path():
    return core.PROCESSED / "its_core_genus.parquet"


def _light_plots() -> tuple[str, ...] | None:
    """Light-mode plots (data/light_mode.txt next to the processed folder), or None when light mode is off.
    Read relative to core.PROCESSED (not config.LIGHT_FILE) so the API and its tests follow the same data dir."""
    f = core.PROCESSED.parent / "light_mode.txt"
    if not f.exists():
        return None
    plots = {config.normalise_plot(line.split("#")[0]) for line in f.read_text().splitlines()}
    return tuple(sorted(p for p in plots if p))


def _core_df() -> pd.DataFrame:
    """its_core_genus; in light mode only the light-mode plots, so they are scored against each other only."""
    f = _core_path()
    if not f.exists():
        raise HTTPException(503, "its_core_genus.parquet missing: run scripts/02b_build_neon_features.py")
    df = core.table("its_core_genus")
    if "product" not in df.columns:
        raise HTTPException(503, "its_core_genus.parquet is stale (no `product` column): "
                                 "run scripts/02b_build_neon_features.py")
    lp = _light_plots()
    return df if lp is None else df[df["plotID"].isin(lp)]


def _core_mtime() -> tuple:
    """Cache key of the core input: file mtime plus the light-mode plot list (switching it changes the data)."""
    _core_df()
    return (_core_path().stat().st_mtime, _light_plots())


def _kb_mtimes() -> tuple:
    p = core.PROCESSED
    try:
        return tuple((p / n).stat().st_mtime for n in (kbmod.GENERA_TABLE, kbmod.HOST_TABLE, kbmod.META_FILE))
    except FileNotFoundError:
        raise HTTPException(503, "Knowledge base not built: run scripts/14_build_kb.py")


@lru_cache(maxsize=2)
def _load_kb(processed, mtimes) -> kbmod.KB:
    return kbmod.load_kb(processed)


def _kb(mtimes) -> kbmod.KB:
    try:
        return _load_kb(core.PROCESSED, mtimes)
    except FileNotFoundError:
        raise HTTPException(503, "Knowledge base not built: run scripts/14_build_kb.py")


@lru_cache(maxsize=8)
def _result(site: str, year: int, core_mtime: tuple, kb_mtimes: tuple) -> risk.CropRiskResult:
    # core_mtime and kb_mtimes are cache keys: the tables themselves are loaded here at request time
    with _lock:
        return risk.compute_crop_risk(site, year, core=_core_df(), kb=_kb(kb_mtimes))


@lru_cache(maxsize=16)
def _site_units(site: str, core_mtime: tuple) -> pd.DataFrame:
    sc = _core_df()
    units, _ = risk.build_units(sc[sc["site"] == site], {})
    units = units.copy()
    units["unit"] = units["year"].astype(str) + "-" + units["product"].str[-3:]
    return units


def _plot_site(plot_id: str) -> str | None:
    c = _core_df()
    s = c.loc[c["plotID"] == plot_id, "site"]
    return None if s.empty else str(s.iloc[0])


def _ref(r) -> RiskUnitRef:
    method = "current" if str(r.product).endswith(CURRENT_PRODUCT) else "older"
    return RiskUnitRef(unit=r.unit, year=int(r.year), product=r.product, method=method,
                       method_label=METHOD_LABELS[method],
                       collect_dates=[d for d in str(r.collect_dates).split("; ") if d],
                       total_reads=int(r.total_reads), n_cores=int(r.n_cores),
                       low_depth=bool(r.total_reads < MIN_UNIT_READS))


def _plot_units(plot_id: str) -> tuple[str | None, pd.DataFrame]:
    _core_df()
    site = _plot_site(plot_id)
    if site is None:                                    # peers may be missing from plot_geometry (light mode)
        core.plot_rows("plot_geometry", plot_id)        # 404 for an unknown plot
        return None, pd.DataFrame()
    u = _site_units(site, _core_mtime())
    u = u[u["plotID"] == plot_id].copy()
    u["_cur"] = u["product"].str.endswith(CURRENT_PRODUCT)
    return site, u.sort_values(["year", "_cur"], ascending=[False, False])


def _find_unit(plot_id: str, unit: str):
    site, u = _plot_units(plot_id)
    hit = u[u["unit"] == unit] if site is not None else u
    if hit.empty:
        raise HTTPException(404, f"unknown crop-risk unit {unit} for plot {plot_id}")
    return site, next(hit.itertuples())


def _crop_row(res: risk.CropRiskResult, crop: str, unit_id: str, product: str) -> CropRiskRow:
    s = res.summary
    s = s[(s["crop"] == crop) & (s["product"] == product)]
    me = s[s["unit_id"] == unit_id].iloc[0]
    ok = s[s["status"] == "ok"]
    peers = ok.sort_values(["risk_index", "plotID"], ascending=[False, True])
    status = str(me["status"])
    rank = pct = None
    if status == "ok":
        v = float(me["risk_index"])
        rank = 1 + int((ok["risk_index"] > v).sum())
        pct = _num(neon.percentile_rank(pd.Series([v]), ok["risk_index"]).iloc[0], 1)
    return CropRiskRow(
        crop=crop, label=CROP_LABELS.get(crop, crop), status=status, risk_index=_num(me["risk_index"]),
        from_detected=_num(me["risk_from_detected"]), from_not_detected=_num(me["risk_from_not_detected"]),
        rank=rank, n_peers=int(len(ok)), n_peers_too_shallow=int((s["status"] == "insufficient_depth").sum()),
        percentile=pct, peers=[Peer(plot_id=r.plotID, risk_index=round(float(r.risk_index), 4))
                               for r in peers.itertuples()],
        top_genus=_str(me["top_genus"]), n_genera_contributing=_int(me["n_genera_contributing"]),
        n_genera_not_detected=_int(me["n_genera_not_detected"]), small_reference=bool(me["small_reference"]),
        same_as=res.metadata.get("same_host_taxa_as", {}).get(crop))


def _skipped_groups(res: risk.CropRiskResult, unit_id: str) -> list[SkippedGroup]:
    sk = res.skipped
    sk = sk[sk["unit_id"] == unit_id]
    out = []
    for reason, label in REASON_LABELS.items():
        g = sk[sk["reason"] == reason]
        if g.empty:
            continue
        g = g.assign(_r=g["reads"].astype(float)).sort_values(["_r", "genus"], ascending=[False, True],
                                                              na_position="last")
        genera = [SkippedGenus(genus=_str(r.genus), reads=None if pd.isna(r.reads) else int(r.reads),
                               detail=_str(r.detail)) for r in g.head(MAX_SKIPPED_GENERA).itertuples()]
        out.append(SkippedGroup(reason=reason, label=label, n=int(len(g)), genera=genera, more=len(g) - len(genera)))
    return out


def _kb_sources(meta: dict) -> list[KbSource]:
    out = []
    for key, name in KB_NAMES.items():
        m = meta.get("kb", {}).get(key)
        if isinstance(m, dict):
            out.append(KbSource(name=name, source_version=_str(m.get("source_version")),
                                retrieved_utc=_str(m.get("retrieved_utc")), url=_str(m.get("url"))))
    return out


def _scored(plot_id: str, unit: str):
    """(site, unit row, result, unit_id) for a unit of the plot; 404/503 as the routes document."""
    site, u = _find_unit(plot_id, unit)
    res = _result(site, int(u.year), _core_mtime(), _kb_mtimes())
    return site, u, res, u.unit_id


# ---------------------------------------------------------------- routes
router = APIRouter(prefix="/api")


@router.get("/plots/{plot_id}/crop-risk", response_model=list[RiskUnitRef])
def crop_risk_units(plot_id: str):
    """ITS units (plot-year-method) of the plot that can be scored, newest year first."""
    site, u = _plot_units(plot_id)
    return [] if site is None else [_ref(r) for r in u.itertuples()]


@router.get("/plots/{plot_id}/crop-risk/{unit}", response_model=PlotCropRisk)
def crop_risk(plot_id: str, unit: str):
    """Risk index of every crop for one unit, ranked against the same site, year and ITS method."""
    site, u, res, uid = _scored(plot_id, unit)
    if res.summary.empty:
        raise HTTPException(404, f"unknown crop-risk unit {unit} for plot {plot_id}")
    md = res.metadata
    peers = res.summary[res.summary["product"] == u.product].drop_duplicates("unit_id")
    crops = [_crop_row(res, c, uid, u.product) for c in kbmod.SCORED_CROPS]
    notes = list(md.get("notes", []))
    lp = _light_plots()
    if lp is not None:
        notes.insert(0, f"Light mode is on: only plots {', '.join(lp)} are scored and compared with each other, "
                        "so comparison sets are small.")
    return PlotCropRisk(
        **_ref(u).model_dump(), plot_id=plot_id, site=site, n_units_in_group=int(len(peers)), crops=crops,
        skipped=_skipped_groups(res, uid), caveats=list(md.get("caveats", [])), notes=notes,
        kb=_kb_sources(md), parameters={k: float(v) for k, v in md.get("parameters", {}).items()},
        index_type=str(md.get("index_type", "")))


@router.get("/plots/{plot_id}/crop-risk/{unit}/{crop}", response_model=CropContributions)
def crop_contributions(plot_id: str, unit: str, crop: str):
    """The genera behind one crop's score for one unit (contribution above zero, largest first)."""
    if crop not in kbmod.SCORED_CROPS:
        raise HTTPException(404, f"unknown crop {crop}")
    site, u, res, uid = _scored(plot_id, unit)
    if res.summary.empty:
        raise HTTPException(404, f"unknown crop-risk unit {unit} for plot {plot_id}")
    c = res.contributions
    c = c[(c["unit_id"] == uid) & (c["crop"] == crop)]
    pos = c[c["contribution"] > 0].sort_values(["contribution", "genus"], ascending=[False, True])
    items = []
    for r in pos.itertuples():
        sp = [x for x in str(r.species_on_crop or "").split("; ") if x] if pd.notna(r.species_on_crop) else []
        items.append(Contribution(
            genus=r.genus, members=[m for m in str(r.genus_members).split("; ") if m],
            detected=r.detection_status == "detected", reads=_int(r.reads), share_pct=_num(r.share_pct, 4) or 0.0,
            a=_num(r.a, 3) or 0.0, percentile=_num(r.percentile, 1) or 0.0, reference_n=_int(r.reference_n),
            small_reference=bool(r.small_reference), h=_num(r.h, 3) or 0.0,
            n_species_on_crop=_int(r.n_species_on_crop), n_species_documented=_int(r.n_species_documented),
            species_on_crop=sp[:MAX_SPECIES], n_species_more=max(0, len(sp) - MAX_SPECIES),
            n_records_on_crop=_int(r.n_records_on_crop), lifestyle=_str(r.ft_primary_lifestyle),
            passed_by=_str(r.ft_passed_by), contribution=_num(r.contribution, 4) or 0.0))
    return CropContributions(plot_id=plot_id, unit=unit, crop=crop, label=CROP_LABELS.get(crop, crop),
                             row=_crop_row(res, crop, uid, u.product), contributions=items,
                             n_scored_zero_h=int((c["h"] == 0).sum()))
