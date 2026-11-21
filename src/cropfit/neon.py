"""NEON data-portal pulls (neonutilities) and ITS / chemistry / qPCR processing. Token comes from .env, never logged."""
from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import RAW, PROCESSED

SITES = ["STER", "KONA"]
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


def fetch_product(dpid: str, sites=SITES, tabl="all", package="basic") -> dict[str, pd.DataFrame]:
    """Pull one product for all sites, concatenating per table; saves parquet under data/raw/neon/<dpid>/."""
    import neonutilities as nu
    token = get_token()
    parts: dict[str, list[pd.DataFrame]] = {}
    for site in sites:
        try:
            res = nu.load_by_product(dpid, site=site, startdate=None, enddate=None, package=package,
                                     release="current", tabl=tabl, check_size=False, include_provisional=True,
                                     token=token, progress=False)
        except Exception as e:  # noqa: BLE001 - never echo token-bearing details
            print(f"  {dpid} {site}: FAILED {type(e).__name__}")
            continue
        for name, df in res.items():
            if isinstance(df, pd.DataFrame) and len(df):
                parts.setdefault(name, []).append(df)
    out = {}
    d = RAW_NEON / dpid
    d.mkdir(parents=True, exist_ok=True)
    for name, dfs in parts.items():
        df = pd.concat(dfs, ignore_index=True)
        df.to_parquet(d / f"{name}.parquet", index=False)
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
def _site_from(df):
    c = _pick(df, "siteID")
    return df[c] if c else df["plotID"].str[:4]


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
        if key == "soilChemistry" and "soilMoisture" in df.columns:
            pass
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


def build_qpcr(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    name = next((n for n in tables if "qpcr" in n.lower() and "validation" not in n.lower()), None)
    if name is None:
        name = next(n for n in tables if "soilMicrobeGroup".lower() in n.lower() or "mga" in n.lower())
    df = tables[name].copy()
    return df  # reshaped in build_qpcr_plot once columns are inspected


def build_qpcr_plot(df: pd.DataFrame) -> pd.DataFrame:
    idc = _pick(df, "dnaSampleID", "sampleID")
    df = df.copy()
    pc = _pick(df, "plotID")
    dc = _pick(df, "collectDate")
    if dc:
        df["collectDate"] = pd.to_datetime(df[dc], errors="coerce").dt.normalize()
    if idc and (not pc or df[pc].isna().all()):
        p = df[idc].map(parse_sample_id)
        df["plotID"] = p.map(lambda d: d.get("plotID"))
        if "collectDate" not in df or df["collectDate"].isna().all():
            df["collectDate"] = p.map(lambda d: d.get("date"))
    elif pc:
        df = df.rename(columns={pc: "plotID"})
    return df


# ---------------------------------------------------------------- ITS per-sample files
def fetch_its_sample_files(product: str = "DP1.10081.002", workers: int = 8) -> pd.DataFrame:
    """ITS taxon tables come as per-sample CSVs (public storage URLs listed in the product's sample-metadata
    table: mct_soilSampleMetadata_ITS for .002, mcc_soilSeqVariantMetadata_ITS for .001). Download all of them
    (every run of re-sequenced samples; select_its_runs() picks one later), keep taxonomy + counts (no
    sequences), save one parquet at its_taxonomy_path(product)."""
    import io
    from concurrent.futures import ThreadPoolExecutor
    from . import http
    d = RAW_NEON / product
    meta = pd.read_parquet(d / f"{ITS_PRODUCTS[product]}.parquet")
    meta = meta[meta["downloadFileUrl"].notna()].drop_duplicates("downloadFileUrl")
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
    out = pd.concat(ok, ignore_index=True)
    out.to_parquet(its_taxonomy_path(product), index=False)
    return out
