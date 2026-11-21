"""NEON data-portal pulls (neonutilities) and ITS / chemistry / qPCR processing. Token comes from .env, never logged."""
from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import RAW, PROCESSED, light_filter, sites

SITES = sites()
RAW_NEON = RAW / "neon"

GENERA = ["Fusarium", "Macrophomina", "Gaeumannomyces", "Rhizoctonia", "Thanatephorus", "Ceratobasidium",
          "Sclerotinia", "Pythium", "Phytophthora", "Glomus", "Rhizophagus", "Funneliformis", "Trichoderma",
          "Mortierella", "Alternaria", "Bipolaris", "Cochliobolus", "Pyrenophora"]
RHIZ = ["Rhizoctonia", "Thanatephorus", "Ceratobasidium"]

# Second depth field is optional: from 2022 NEON core IDs carry one (e.g. KONA_001-M-21-20240409-GEN-DNA1).
_ID_RE = re.compile(r"^(?P<site>[A-Z]{4})_(?P<plotnum>\d{3})-(?P<hz>[MO])-[\d.]+(?:-[\d.]+)?-(?P<date>\d{8})")

# ITS taxonomy products, in order of preference when a DNA sample is in both:
# .002 (current pipeline, ~2016+, mct_* tables) and .001 (old pipeline, 2014-2018, mcc_* tables).
# The two pipelines differ (reference DB, OTU vs sequence variant): keep `product` as a covariate.
ITS_PRODUCTS = {"DP1.10081.002": "mct_soilSampleMetadata_ITS",
                "DP1.10081.001": "mcc_soilSeqVariantMetadata_ITS"}


def get_token() -> str | None:
    from dotenv import load_dotenv
    from .config import ROOT
    load_dotenv(ROOT / ".env")
    return os.environ.get("NEON_API_TOKEN") or os.environ.get("NEON_TOKEN") or None


def parse_sample_id(s: str) -> dict:
    """STER_026-M-8-11.5-20130716-GEN-DNA1 -> site, plotID, horizon, date (Timestamp). Empty dict if no match."""
    m = _ID_RE.match(str(s))
    if not m:
        return {}
    return {"site": m["site"], "plotID": f"{m['site']}_{m['plotnum']}", "horizon": m["hz"],
            "date": pd.to_datetime(m["date"], format="%Y%m%d")}


def percentile_rank(values: pd.Series, ref: pd.Series) -> pd.Series:
    """Mid-rank percentile (0-100): 100*(#ref<v + 0.5*#ref==v)/n; ties share the average rank."""
    ref = np.sort(np.asarray(ref.dropna(), dtype=float))
    n = len(ref)
    out = []
    for v in values:
        if pd.isna(v) or n == 0:
            out.append(np.nan)
            continue
        lo = np.searchsorted(ref, v, side="left")
        hi = np.searchsorted(ref, v, side="right")
        out.append(100.0 * (lo + 0.5 * (hi - lo)) / n)
    return pd.Series(out, index=values.index)


class IncompleteFetch(RuntimeError):
    """A pull did not get everything it asked for; nothing was written. Message never contains the token."""


def _write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".part")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def fetch_product(dpid: str, sites=SITES, tabl="all", package="basic",
                  allow_partial: bool = False) -> dict[str, pd.DataFrame]:
    """Pull one product for all sites, concatenating per table; saves parquet under data/raw/neon/<dpid>/.

    Each table file holds every site, so if any site fails nothing is written (the existing raw files stay
    as they were) and IncompleteFetch is raised. allow_partial=True writes the sites that succeeded.
    In light mode (config.light_plots) rows of other plots are dropped before saving: NEON serves whole
    sites, so the pull itself is not smaller, but the ITS per-sample files are fetched for these plots only."""
    import neonutilities as nu
    token = get_token()
    parts: dict[str, list[pd.DataFrame]] = {}
    failed = []
    for site in sites:
        try:
            res = nu.load_by_product(dpid, site=site, startdate=None, enddate=None, package=package,
                                     release="current", tabl=tabl, check_size=False, include_provisional=True,
                                     token=token, progress=False)
        except Exception as e:  # noqa: BLE001 - never echo token-bearing details
            print(f"  {dpid} {site}: FAILED {type(e).__name__}")
            failed.append(site)
            continue
        for name, df in res.items():
            if isinstance(df, pd.DataFrame) and len(df):
                parts.setdefault(name, []).append(light_filter(df))
    if failed and not allow_partial:
        raise IncompleteFetch(f"{dpid}: sites failed {failed}; raw files left unchanged")
    out = {}
    d = RAW_NEON / dpid
    d.mkdir(parents=True, exist_ok=True)
    for name, dfs in parts.items():
        df = pd.concat(dfs, ignore_index=True)
        _write_parquet_atomic(df, d / f"{name}.parquet")
        out[name] = df
    return out


# ---------------------------------------------------------------- ITS
def _pick(df: pd.DataFrame, *cands: str) -> str | None:
    low = {c.lower(): c for c in df.columns}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def its_taxonomy_path(product: str) -> Path:
    """Assembled per-sample ITS taxonomy written by fetch_its_sample_files()."""
    prefix = ITS_PRODUCTS[product].split("_")[0]  # mct / mcc
    return RAW_NEON / product / f"{prefix}_soilPerSampleTaxonomy_ITS.parquet"


def select_its_runs(raw: pd.DataFrame, preference=tuple(ITS_PRODUCTS)) -> pd.DataFrame:
    """One run per DNA sample: the deepest run within a product, then the preferred product.

    NEON re-sequences some samples (several metadata rows / sequencerRunIDs per dnaSampleID) and some
    DNA samples appear in both DP1.10081.002 and .001. Rows need dnaSampleID and individualCount;
    `product` and `sequencerRunID` are used when present."""
    df = raw.copy()
    if "product" not in df:
        df["product"] = preference[-1]
    if "sequencerRunID" not in df:
        df["sequencerRunID"] = ""
    df["sequencerRunID"] = df["sequencerRunID"].fillna("").astype(str)
    df["_cnt"] = pd.to_numeric(df["individualCount"], errors="coerce").fillna(0)
    depth = df.groupby(["product", "dnaSampleID", "sequencerRunID"])["_cnt"].sum().rename("_depth").reset_index()
    depth["_rank"] = depth["product"].map({p: i for i, p in enumerate(preference)}).fillna(len(preference))
    best = (depth.sort_values(["dnaSampleID", "_rank", "_depth"], ascending=[True, True, False])
            .drop_duplicates("dnaSampleID")[["product", "dnaSampleID", "sequencerRunID"]])
    out = df.merge(best, on=["product", "dnaSampleID", "sequencerRunID"], how="inner")
    return out.drop(columns=["_cnt"])


def load_its_raw(products=tuple(ITS_PRODUCTS)) -> pd.DataFrame:
    """Per-sample ITS taxonomy of all available products, one run per DNA sample (see select_its_runs)."""
    parts = []
    for p in products:
        f = its_taxonomy_path(p)
        if f.exists():
            df = pd.read_parquet(f)
            df["product"] = p
            parts.append(df)
    if not parts:
        raise FileNotFoundError(f"no ITS per-sample taxonomy under {RAW_NEON} (run scripts/02_fetch_neon.py)")
    return select_its_runs(pd.concat(parts, ignore_index=True), preference=tuple(products))


def build_its_core(raw: pd.DataFrame) -> pd.DataFrame:
    """Per core (dnaSampleID) genus reads and share of the core's fungal reads; long format.

    Columns: site, plotID, horizon, collectDate, soilSampleID (core, = NMDC biosample name), dnaSampleID,
    product, sequenceCountQF, genus, reads, total_reads (fungal reads of the core), share_pct."""
    df = raw.copy()
    idc = _pick(df, "dnaSampleID", "sampleID")
    gc = _pick(df, "genus")
    cc = _pick(df, "individualCount")
    if None in (idc, gc, cc):
        raise KeyError(f"ITS columns missing: {list(df.columns)}")
    parsed = df[idc].map(parse_sample_id)
    df = df[parsed.map(bool)].copy()
    parsed = parsed[df.index]
    df["site"] = parsed.map(lambda d: d["site"])
    df["plotID"] = parsed.map(lambda d: d["plotID"])
    df["horizon"] = parsed.map(lambda d: d["horizon"])
    df["collectDate"] = parsed.map(lambda d: d["date"])
    kc = _pick(df, "kingdom")
    if kc:  # total_reads = fungal reads only (unassigned/non-fungal ASVs have empty kingdom)
        df = df[df[kc].astype("string").str.lower() == "fungi"].copy()
    df["dnaSampleID"] = df[idc].astype(str)
    df["soilSampleID"] = df["dnaSampleID"].str.replace(r"-GEN(-DNA\d+)?$", "", regex=True)
    # Downstream treats a DNA sample as a core (n_cores, per-core mean shares, the metagenome join by
    # soilSampleID). Two extracts of one core (-DNA1/-DNA2) would be counted twice and their shares summed.
    ext = df.groupby("soilSampleID")["dnaSampleID"].nunique()
    if (ext > 1).any():
        dup = ext[ext > 1]
        raise ValueError(f"{len(dup)} soil cores have more than one DNA extract, e.g. {dup.index[:3].tolist()}; "
                         "pick one extract per core before building per-core tables")
    df["_cnt"] = pd.to_numeric(df[cc], errors="coerce").fillna(0)
    df["genus"] = df[gc].astype("string").str.strip()
    # fungal reads without a genus stay visible (cores with only such reads would otherwise vanish)
    df["genus"] = df["genus"].mask(df["genus"].isna() | (df["genus"] == ""), "unclassified_Fungi")
    for col, default in (("product", ""), ("sequenceCountQF", "")):
        if col not in df:
            df[col] = default
    df["sequenceCountQF"] = df["sequenceCountQF"].fillna("")
    key = ["site", "plotID", "horizon", "collectDate", "soilSampleID", "dnaSampleID", "product", "sequenceCountQF"]
    total = df.groupby(key)["_cnt"].sum().rename("total_reads").reset_index()
    g = (df.dropna(subset=["genus"]).groupby(key + ["genus"])["_cnt"].sum().rename("reads").reset_index())
    g = g.merge(total, on=key)
    g["share_pct"] = np.where(g["total_reads"] > 0, 100 * g["reads"] / g["total_reads"], np.nan)
    return g.sort_values(["site", "plotID", "collectDate", "dnaSampleID", "genus"]).reset_index(drop=True)


def build_its_genus(raw: pd.DataFrame, qc_ok_only: bool = True) -> pd.DataFrame:
    """Per (plotID, collectDate) genus abundance from per-core ITS; long format incl. zeros for GENERA.

    rel_abund_pct is the MEAN of per-core shares (each core weighs equally, like the equal-mass cores pooled
    into a NEON composite); reads and total_reads are sums over the included cores. With qc_ok_only, cores
    flagged sequenceCountQF == "Below threshold" are excluded (missing flag counts as OK)."""
    core = build_its_core(raw)
    core = core[core["horizon"] == "M"] if (core["horizon"] == "M").any() else core
    if qc_ok_only:
        core = core[core["sequenceCountQF"] != "Below threshold"]
    grp = ["site", "plotID", "collectDate"]
    cores = core.drop_duplicates("dnaSampleID")
    per = cores.groupby(grp).agg(total_reads=("total_reads", "sum"), n_cores=("dnaSampleID", "nunique"),
                                 dnaSampleID=("dnaSampleID", lambda s: ";".join(sorted(s))),
                                 product=("product", lambda s: ";".join(sorted(set(s) - {""})))).reset_index()
    # every (core, genus) pair so cores without a genus contribute a 0 share to the mean
    ids = cores[grp + ["dnaSampleID"]]
    allg = ids.merge(pd.DataFrame({"genus": sorted(set(core["genus"]) | set(GENERA))}), how="cross")
    allg = allg.merge(core[["dnaSampleID", "genus", "reads", "share_pct"]], on=["dnaSampleID", "genus"],
                      how="left").fillna({"reads": 0, "share_pct": 0.0})
    g = allg.groupby(grp + ["genus"]).agg(reads=("reads", "sum"), rel_abund_pct=("share_pct", "mean")).reset_index()
    g = g[(g["reads"] > 0) | g["genus"].isin(GENERA)]
    g = g.merge(per, on=grp)
    g["year"] = pd.to_datetime(g["collectDate"]).dt.year
    g["collectDate"] = pd.to_datetime(g["collectDate"]).dt.date
    return g[["site", "plotID", "collectDate", "year", "dnaSampleID", "n_cores", "product", "genus", "reads",
              "total_reads", "rel_abund_pct"]].sort_values(["site", "plotID", "collectDate", "genus"]
                                                           ).reset_index(drop=True)


def its_genus_lineage(raw: pd.DataFrame) -> pd.DataFrame:
    """genus -> phylum, class for the fungal genera in the per-sample ITS taxonomy (both pipelines).

    A genus name that maps to several lineages (rare; reference updates) gets the one with most reads.
    Placeholder names (`<taxon>_cls_Incertae_sedis`) are kept as given: the viewer treats them as unnamed.
    `unclassified_Fungi` (build_its_core's name for reads without a genus) is not in the table."""
    cols = {k: _pick(raw, k) for k in ("kingdom", "phylum", "class", "genus", "individualCount")}
    if None in cols.values():
        raise KeyError(f"ITS lineage columns missing: {list(raw.columns)}")
    df = pd.DataFrame({k: raw[c] for k, c in cols.items()})
    df = df[df["kingdom"].astype("string").str.lower() == "fungi"]
    for c in ("phylum", "class", "genus"):
        df[c] = df[c].astype("string").str.strip().replace("", pd.NA)
    df = df.dropna(subset=["genus"])
    df["reads"] = pd.to_numeric(df["individualCount"], errors="coerce").fillna(0)
    best = (df.groupby(["genus", "phylum", "class"], dropna=False)["reads"].sum().reset_index()
            .sort_values(["genus", "reads"], ascending=[True, False]).drop_duplicates("genus"))
    return best[["genus", "phylum", "class"]].reset_index(drop=True)


def pooling_map(raw_dir: Path | None = None) -> pd.DataFrame:
    """Core -> metagenome composite from DP1.10086.001 sls_metagenomicsPooling (one row per pooled core).

    Columns: soilSampleID (core sampleID = NMDC biosample name), genomicsSampleID, plotID, collectDate."""
    f = (raw_dir or RAW_NEON / "DP1.10086.001") / "sls_metagenomicsPooling.parquet"
    if not f.exists():
        return pd.DataFrame(columns=["soilSampleID", "genomicsSampleID", "plotID", "collectDate"])
    p = pd.read_parquet(f)
    p = p[p["genomicsPooledIDList"].notna()]
    p = p.assign(soilSampleID=p["genomicsPooledIDList"].str.split("|")).explode("soilSampleID")
    p["soilSampleID"] = p["soilSampleID"].str.strip()
    p["collectDate"] = pd.to_datetime(p["collectDate"], errors="coerce").dt.tz_localize(None).dt.date
    return p[["soilSampleID", "genomicsSampleID", "plotID", "collectDate"]].drop_duplicates().reset_index(drop=True)


def _wide(g: pd.DataFrame) -> pd.DataFrame:
    """Plot-date wide table with raw shares incl. Rhizoctonia_complex."""
    key = ["site", "plotID", "collectDate", "n_cores", "total_reads"]
    gg = g[g["genus"].isin(GENERA)]
    sh = gg.pivot_table(index=key, columns="genus", values="rel_abund_pct", aggfunc="sum").reset_index()
    rd = gg.pivot_table(index=key, columns="genus", values="reads", aggfunc="sum").reset_index()
    for col in GENERA:
        for t in (sh, rd):
            if col not in t:
                t[col] = 0.0
    sh["Rhizoctonia_complex"] = sh[RHIZ].sum(axis=1)
    rd["Rhizoctonia_complex"] = rd[RHIZ].sum(axis=1)
    w = sh[key].copy()
    for c in GENERA + ["Rhizoctonia_complex"]:
        w[f"bio_its_share_{c}"] = sh[c].values
        w[f"bio_its_detected_{c}"] = (rd[c].values > 0)
    return w


def plot_its_timeseries(g: pd.DataFrame) -> pd.DataFrame:
    w = _wide(g)
    w["bio_its_date"] = pd.to_datetime(w["collectDate"])
    refs = {}
    for site, sub in w.groupby("site"):
        y0, y1 = pd.to_datetime(sub["collectDate"]).dt.year.agg(["min", "max"])
        refs[site] = f"{site} {y0}–{y1}, n={len(sub)} plot-dates"
        for c in GENERA + ["Rhizoctonia_complex"]:
            col = f"bio_its_share_{c}"
            # A genus never detected at the site has no meaningful percentile (all ties at 0):
            # leave NaN so the UI shows "not detected in this data" (never "absent").
            if (sub[col].fillna(0) > 0).any():
                w.loc[sub.index, f"bio_its_pct_{c}"] = percentile_rank(sub[col], sub[col]).values
            else:
                w.loc[sub.index, f"bio_its_pct_{c}"] = np.nan
    w["bio_its_ref"] = w["site"].map(refs)
    return w


def plot_its_latest(ts: pd.DataFrame) -> pd.DataFrame:
    ts = ts.sort_values(["plotID", "bio_its_date"])
    return ts.groupby("plotID").tail(1).reset_index(drop=True)


# ---------------------------------------------------------------- chemistry / qPCR
def build_chem(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per plotID x collectDate means from sls_soilChemistry, sls_soilpH, sls_soilMoisture (names matched loosely)."""
    out = None
    spec = {
        "soilChemistry": {"organicCPercent": "organic_c_pct", "nitrogenPercent": "total_n_pct", "CNratio": "cn_ratio"},
        "soilpH": {"soilInWaterpH": "ph_water", "soilInCaClpH": "ph_cacl2"},
        "soilMoisture": {"soilMoisture": "soil_moisture"},
    }
    for key, cols in spec.items():
        name = next((n for n in tables if key.lower() in n.lower() and "validation" not in n.lower()), None)
        if name is None:
            continue
        df = tables[name].copy()
        pc, dc = _pick(df, "plotID"), _pick(df, "collectDate")
        if not pc or not dc:
            continue
        df["collectDate"] = pd.to_datetime(df[dc], errors="coerce").dt.normalize()
        have = {k: v for k, v in cols.items() if k in df.columns}
        for k in have:
            df[k] = pd.to_numeric(df[k], errors="coerce")
        # horizon: keep mineral if the column exists
        hz = _pick(df, "horizon")
        if hz is not None and (df[hz] == "M").any():
            df = df[df[hz] == "M"]
        agg = df.groupby([pc, "collectDate"]).agg(**{v: (k, "mean") for k, v in have.items()},
                                                   **{f"n_cores_{key}": (pc, "size")}).reset_index()
        agg = agg.rename(columns={pc: "plotID"})
        out = agg if out is None else out.merge(agg, on=["plotID", "collectDate"], how="outer")
    if out is None:
        raise RuntimeError("no chemistry tables found")
    nc = [c for c in out.columns if c.startswith("n_cores_")]
    out["n_cores"] = out[nc].max(axis=1)
    out = out.drop(columns=nc)
    if {"organic_c_pct", "total_n_pct"} <= set(out.columns):
        calc = out["organic_c_pct"] / out["total_n_pct"]
        out["cn_ratio"] = out["cn_ratio"].combine_first(calc) if "cn_ratio" in out else calc
    out["collectDate"] = out["collectDate"].dt.date
    out["site"] = out["plotID"].str[:4]
    return out.sort_values(["plotID", "collectDate"]).reset_index(drop=True)


def build_inorganic_n(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """KCl-extractable inorganic N and net N transformation rates per plotID x collectDate (DP1.10086 ntr_*).

    Needs ntr_externalLab (extract concentrations, mg N/L), ntr_internalLab (fresh soil mass, KCl volume,
    incubation pairs), sls_soilMoisture (g water per g dry soil) and, when present, ntr_internalLabBlanks.
    Per sample: blank-corrected concentration (negatives set to 0) x KCl volume / dry soil mass = mg N per kg
    dry soil. Plot-date columns: ammonium_n_mgkg, nitrate_n_mgkg (initial cores, i.e. the field state),
    net_n_min_mgkg_d, net_nitrif_mgkg_d (final minus initial of an incubation pair, per day), n_cores, n_pairs.
    Rates are reported at the collect date of the initial core."""
    ext, lab, moist = tables["ntr_externalLab"].copy(), tables["ntr_internalLab"].copy(), tables["sls_soilMoisture"]
    for c in ("kclAmmoniumNConc", "kclNitrateNitriteNConc"):
        ext[c] = pd.to_numeric(ext[c], errors="coerce")
    conc = ext.groupby("kclSampleID")[["kclAmmoniumNConc", "kclNitrateNitriteNConc"]].mean()
    blank = pd.DataFrame(columns=["kclReferenceID", "b_nh4", "b_no3"])
    bl = tables.get("ntr_internalLabBlanks")
    if bl is not None and len(bl):
        b = bl.melt(id_vars="kclReferenceID", value_vars=[c for c in bl.columns if c.endswith("ID") and "Blank" in c],
                    value_name="kclSampleID").dropna(subset=["kclSampleID"])
        b = b.merge(conc, left_on="kclSampleID", right_index=True)
        blank = (b.groupby("kclReferenceID")[["kclAmmoniumNConc", "kclNitrateNitriteNConc"]].mean()
                 .rename(columns={"kclAmmoniumNConc": "b_nh4", "kclNitrateNitriteNConc": "b_no3"}).reset_index())
    m = moist[["sampleID", "soilMoisture"]].copy()
    m["soilMoisture"] = pd.to_numeric(m["soilMoisture"], errors="coerce")
    s = (lab.merge(conc, left_on="kclSampleID", right_index=True, how="inner")
         .merge(blank, on="kclReferenceID", how="left")
         .merge(m.groupby("sampleID", as_index=False)["soilMoisture"].mean(), on="sampleID", how="left"))
    for c in ("soilFreshMass", "kclVolume", "incubationLength"):
        s[c] = pd.to_numeric(s[c], errors="coerce")
    dry = s["soilFreshMass"] / (1 + s["soilMoisture"])
    s["nh4"] = (s["kclAmmoniumNConc"] - s["b_nh4"].fillna(0)).clip(lower=0) * s["kclVolume"] / dry
    s["no3"] = (s["kclNitrateNitriteNConc"] - s["b_no3"].fillna(0)).clip(lower=0) * s["kclVolume"] / dry
    s["collectDate"] = pd.to_datetime(s["collectDate"]).dt.tz_localize(None).dt.normalize()
    ini = s[s["nTransBoutType"] == "tInitial"]
    fin = s[s["nTransBoutType"] == "tFinal"]
    state = ini.groupby(["plotID", "collectDate"]).agg(ammonium_n_mgkg=("nh4", "mean"), nitrate_n_mgkg=("no3", "mean"),
                                                        n_cores=("sampleID", "nunique")).reset_index()
    pair = ini[["plotID", "collectDate", "incubationPairID", "nh4", "no3"]].merge(
        fin[["incubationPairID", "nh4", "no3", "incubationLength"]], on="incubationPairID", suffixes=("_i", "_f"))
    pair = pair[pair["incubationLength"] > 0]
    pair["net_n_min_mgkg_d"] = ((pair["nh4_f"] + pair["no3_f"]) - (pair["nh4_i"] + pair["no3_i"])) / pair["incubationLength"]
    pair["net_nitrif_mgkg_d"] = (pair["no3_f"] - pair["no3_i"]) / pair["incubationLength"]
    rates = pair.groupby(["plotID", "collectDate"]).agg(
        net_n_min_mgkg_d=("net_n_min_mgkg_d", "mean"), net_nitrif_mgkg_d=("net_nitrif_mgkg_d", "mean"),
        n_pairs=("net_n_min_mgkg_d", "count")).reset_index()
    out = state.merge(rates, on=["plotID", "collectDate"], how="outer")
    out["n_pairs"] = out["n_pairs"].fillna(0).astype(int)
    out["site"] = out["plotID"].str[:4]
    out["collectDate"] = out["collectDate"].dt.date
    return out.sort_values(["plotID", "collectDate"]).reset_index(drop=True)


# ---------------------------------------------------------------- management, baseline soil, plant cover
MGMT_TYPES = [("addition-seeds", "seeding"), ("cropHarvest", "harvest"), ("herbicide", "herbicide"),
              ("fungicide", "fungicide"), ("insecticide", "insecticide"), ("pesticide", "pesticide"),
              ("fertilizer", "fertilizer"), ("tillage", "tillage"), ("mowing", "mowing"), ("grazing", "grazing"),
              ("fire", "fire")]


def build_management(ev: pd.DataFrame, plot_ids) -> pd.DataFrame:
    """DP1.10111.001 sim_eventData -> one row per plot and reported management event.

    NEON lists the affected locations in `locationID`; base plots are picked out of it. An event reported for
    the whole site (location = the site code) is given to every plot in plot_ids of that site, scope='site'.
    Columns: plotID, site, date (start), end_date, type (seeding, harvest, herbicide, fungicide, fertilizer,
    tillage, mowing, grazing, other), method, what (product or species named), scope, date_quality, remarks."""
    plot_ids = sorted(set(plot_ids))
    rows = []
    for r in ev.itertuples():
        loc = str(r.locationID)
        plots = set(re.findall(r"([A-Z]{4}_\d{3})\.basePlot", loc))
        scope = "plot"
        if not plots and r.siteID in [x.strip() for x in loc.split(",")]:
            plots, scope = {p for p in plot_ids if p.startswith(r.siteID)}, "site"
        method = str(r.methodTypeChoice or "")
        typ = next((name for key, name in MGMT_TYPES if key.lower() in method.lower()), None)
        typ = typ or next((name for key, name in MGMT_TYPES if key.lower() in str(r.eventType).lower()), "other")
        what = str(r.scientificName or "").strip() or str(r.name or "").strip() or None
        for pl in plots & set(plot_ids):
            rows.append(dict(plotID=pl, site=r.siteID, date=r.startDate, end_date=r.endDate, type=typ,
                             method=method or r.eventType, what=what, scope=scope,
                             date_quality=getattr(r, "estimatedOrActualDate", None), remarks=r.remarks))
    out = pd.DataFrame(rows)
    for c in ("date", "end_date"):
        out[c] = pd.to_datetime(out[c], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    return out.dropna(subset=["date"]).sort_values(["plotID", "date"]).reset_index(drop=True)


def build_soil_baseline(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """DP1.10047.001 (one-time soil pit per plot) -> topmost horizon per plot: measured pH, C, N, CEC,
    carbonate, EC, texture, bulk density. Columns prefixed base_; base_top_cm/base_bottom_cm give the layer."""
    def top(df, depth, cols):
        d = df.copy()
        for c in [depth] + list(cols):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.sort_values(["plotID", depth]).drop_duplicates("plotID")
        return d.set_index("plotID")
    b = top(tables["spc_biogeochem"], "biogeoTopDepth",
            {"phH2o", "phCacl2", "carbonTot", "nitrogenTot", "cecdNh4", "caco3Conc", "ec12pre", "biogeoBottomDepth"})
    out = pd.DataFrame({"base_ph_water": b["phH2o"], "base_ph_cacl2": b["phCacl2"], "base_carbon_gkg": b["carbonTot"],
                        "base_nitrogen_gkg": b["nitrogenTot"], "base_cec": b["cecdNh4"], "base_caco3_gkg": b["caco3Conc"],
                        "base_ec": b["ec12pre"], "base_top_cm": b["biogeoTopDepth"], "base_bottom_cm": b["biogeoBottomDepth"],
                        "base_horizon": b["horizonName"]})
    if "spc_particlesize" in tables:
        s = top(tables["spc_particlesize"], "biogeoTopDepth", {"sandTotal", "siltTotal", "clayTotal"})
        out = out.join(s[["sandTotal", "siltTotal", "clayTotal"]].rename(
            columns={"sandTotal": "base_sand_pct", "siltTotal": "base_silt_pct", "clayTotal": "base_clay_pct"}))
    if "spc_bulkdensity" in tables:
        d = top(tables["spc_bulkdensity"], "bulkDensTopDepth", {"bulkDensOvenDry", "bulkDensThirdBar"})
        out = out.join(d["bulkDensOvenDry"].combine_first(d["bulkDensThirdBar"]).rename("base_bulk_density"))
    if "spc_perplot" in tables:
        pp = tables["spc_perplot"].drop_duplicates("plotID").set_index("plotID")
        out = out.join(pp[["collectDate", "soilSeries", "soilOrder"]].rename(
            columns={"collectDate": "base_date", "soilSeries": "base_soil_series", "soilOrder": "base_soil_order"}))
        out["base_date"] = pd.to_datetime(out["base_date"], errors="coerce", utc=True).dt.tz_localize(None).dt.date
    return out.reset_index()


def build_plant_cover(div: pd.DataFrame) -> pd.DataFrame:
    """DP1.10058.001 div_1m2Data (1 m2 quadrats) -> one row per plot and survey date: mean per quadrat of total
    plant cover, bare soil and litter cover (%), number of plant species seen, and the species with the highest
    mean cover (the crop, or the dominant weed in fallow). n_quadrats says how many squares were read."""
    d = div.copy()
    d["date"] = pd.to_datetime(d["endDate"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    d["percentCover"] = pd.to_numeric(d["percentCover"], errors="coerce")
    d = d.dropna(subset=["date"])
    key = ["plotID", "date"]
    nq = d.groupby(key)["subplotID"].nunique().rename("n_quadrats")
    sp = d[d["divDataType"] == "plantSpecies"]
    plant = sp.groupby(key)["percentCover"].sum().rename("s")
    ov = d[d["divDataType"] == "otherVariables"]

    def other(name):
        return ov[ov["otherVariables"] == name].groupby(key)["percentCover"].sum().rename(name)
    out = pd.concat([nq, plant, other("soil"), other("litter"), sp.groupby(key)["taxonID"].nunique().rename("n_species")],
                    axis=1).reset_index()
    for c, new in (("s", "plant_cover_pct"), ("soil", "bare_soil_pct"), ("litter", "litter_pct")):
        out[new] = out[c].fillna(0) / out["n_quadrats"]
    dom = (sp.groupby(key + ["scientificName"])["percentCover"].sum().reset_index()
           .sort_values("percentCover", ascending=False).drop_duplicates(key))
    out = out.merge(dom[key + ["scientificName"]].rename(columns={"scientificName": "dominant_species"}), on=key, how="left")
    out["n_species"] = out["n_species"].fillna(0).astype(int)
    return out[key + ["n_quadrats", "plant_cover_pct", "bare_soil_pct", "litter_pct", "n_species",
                      "dominant_species"]].sort_values(key).reset_index(drop=True)


# ---------------------------------------------------------------- ITS per-sample files
def fetch_its_sample_files(product: str = "DP1.10081.002", workers: int = 8,
                           allow_partial: bool = False) -> pd.DataFrame:
    """ITS taxon tables come as per-sample CSVs (public storage URLs listed in the product's sample-metadata
    table: mct_soilSampleMetadata_ITS for .002, mcc_soilSeqVariantMetadata_ITS for .001). Download all of them
    (every run of re-sequenced samples; select_its_runs() picks one later), keep taxonomy + counts (no
    sequences), save one parquet at its_taxonomy_path(product).

    If any file fails, nothing is written (the existing parquet stays) and IncompleteFetch is raised;
    allow_partial=True writes what was downloaded."""
    import io
    from concurrent.futures import ThreadPoolExecutor
    from . import http
    d = RAW_NEON / product
    meta = pd.read_parquet(d / f"{ITS_PRODUCTS[product]}.parquet")
    meta = light_filter(meta[meta["downloadFileUrl"].notna()].drop_duplicates("downloadFileUrl"))
    keep = ["dnaSampleID", "sequencerRunID", "kingdom", "phylum", "class", "order", "family", "genus",
            "specificEpithet", "scientificName", "individualCount"]

    def one(row):
        try:
            r = http.get(row["downloadFileUrl"], timeout=120)
            df = pd.read_csv(io.BytesIO(r.content), usecols=lambda c: c in keep, dtype=str)
        except Exception:  # noqa: BLE001
            return None
        df["individualCount"] = pd.to_numeric(df["individualCount"], errors="coerce")
        if "sequencerRunID" not in df or df["sequencerRunID"].isna().all():
            df["sequencerRunID"] = row.get("sequencerRunID")
        df["collectDate"] = row["collectDate"]
        df["sequenceCountQF"] = row["sequenceCountQF"]
        df["sampleFilteredReadNumber"] = row.get("sampleFilteredReadNumber")
        df["release"] = row.get("release")
        df["product"] = product
        return df

    rows = [r for _, r in meta.iterrows()]
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, rows))
    ok = [r for r in res if r is not None]
    failed = [row["downloadFileUrl"].rsplit("/", 1)[-1] for row, r in zip(rows, res) if r is None]
    print(f"  {product} ITS per-sample files: {len(ok)}/{len(res)} downloaded")
    if failed:
        print(f"  FAILED ({len(failed)}): {', '.join(failed[:10])}{' ...' if len(failed) > 10 else ''}")
        if not allow_partial:
            raise IncompleteFetch(f"{product}: {len(failed)}/{len(res)} ITS files failed; "
                                  f"{its_taxonomy_path(product).name} left unchanged")
    if not ok:
        raise IncompleteFetch(f"{product}: no ITS files downloaded")
    out = pd.concat(ok, ignore_index=True)
    _write_parquet_atomic(out, its_taxonomy_path(product))
    return out
