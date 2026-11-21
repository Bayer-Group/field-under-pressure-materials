"""Developer data inspector: builds one self-contained HTML page from everything in data/processed/.

    .venv/bin/python scripts/10_inspect_data.py        ->  outputs/inspect/index.html  (open in a browser)

Not an app for users: a way to see what has been retrieved, how complete it is and how the pieces line up in
time. Offline, no server, no external libraries; aerial previews are referenced from data/raw/imagery/.
Re-run after any pipeline step to refresh.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pandas as pd
from cropfit import events
from cropfit.config import OUTPUTS, PROCESSED, RAW, ROOT

OUT = OUTPUTS / "inspect"
HEAD_ROWS = 60


def rd(name):
    f = PROCESSED / f"{name}.parquet"
    if not f.exists():
        return None
    if name == "fields":
        import geopandas as gpd
        return pd.DataFrame(gpd.read_parquet(f).drop(columns="geometry"))
    return pd.read_parquet(f)


def clean(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or v is pd.NaT:
        return None
    if isinstance(v, (np.floating, float)):
        return float(f"{float(v):.7g}")
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "isoformat"):
        return str(v)[:10]
    if isinstance(v, (list, tuple, np.ndarray, dict)):
        return str(v)[:80]
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v if isinstance(v, (int, str)) else str(v)


def records(df, cols=None):
    df = df if cols is None else df[[c for c in cols if c in df.columns]]
    return [[clean(v) for v in row] for row in df.itertuples(index=False, name=None)]


def dataset_summary(name, df, f):
    cols = []
    for c in df.columns:
        s = df[c]
        info = dict(name=c, dtype=str(s.dtype), nonnull=round(float(s.notna().mean()), 3) if len(s) else 0)
        try:
            if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
                info.update(min=clean(s.min()), max=clean(s.max()))
            elif pd.api.types.is_datetime64_any_dtype(s):
                info.update(min=clean(s.min()), max=clean(s.max()))
            else:
                info.update(distinct=int(s.astype(str).nunique()))
        except Exception:  # noqa: BLE001
            pass
        cols.append(info)
    plot_col = next((c for c in ("plotID", "unit_id") if c in df.columns), None)
    date_col = next((c for c in ("date", "collectDate", "bio_its_date", "bio_metagenome_date") if c in df.columns), None)
    d = pd.to_datetime(df[date_col], errors="coerce") if date_col else None
    return dict(name=name, rows=len(df), ncols=df.shape[1], kb=round(f.stat().st_size / 1024, 1),
                modified=pd.Timestamp(f.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M"),
                plots=int(df[plot_col].nunique()) if plot_col else None,
                date_min=clean(d.min()) if d is not None and d.notna().any() else None,
                date_max=clean(d.max()) if d is not None and d.notna().any() else None,
                columns=cols, head_cols=list(df.columns), head=records(df.head(HEAD_ROWS)))


def by_plot(df, key, cols):
    if df is None:
        return {}
    return {k: records(g, cols) for k, g in df.groupby(key)}


def main():
    data = {"generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "root": str(ROOT)}
    files = sorted(PROCESSED.glob("*.parquet"))
    data["datasets"] = []
    for f in files:
        df = rd(f.stem)
        data["datasets"].append(dataset_summary(f.stem, df, f))
    data["raw"] = [dict(name=str(m.parent.relative_to(RAW)), **{k: clean(v) for k, v in dict(
        rows=len(pd.read_parquet(m)), fetched_at=pd.read_parquet(m)["fetched_at"].iloc[0]).items()})
        for m in sorted(RAW.rglob("manifest.parquet"))]

    ev = rd("events")
    if ev is None:
        raise SystemExit("no events.parquet: run scripts/01_build_events.py first")
    ev["date"] = pd.to_datetime(ev["date"])
    data["event_cols"] = ["event_id", "site", "plotID", "date", "year", "has_metagenome", "has_its", "has_chem"]
    data["events"] = records(ev, data["event_cols"])

    geom, plots, terr = rd("plot_geometry"), rd("plots"), rd("plot_terrain")
    p = geom.copy()
    if plots is not None:
        keep = ["unit_id", "muname", "compname", "drainage_class", "ph_surface", "clay_pct", "om_pct", "awc100_mm",
                "mukey_share", "gdd10_may_sep", "prcp_apr_sep_mm", "frost_free_days", "history_source"]
        p = p.merge(plots[[c for c in keep if c in plots]], left_on="plotID", right_on="unit_id", how="left").drop(columns="unit_id")
    if terr is not None:
        p = p.merge(terr.drop(columns=[c for c in ("terrain_source",) if c in terr]), on="plotID", how="left")
    data["plot_cols"] = list(p.columns)
    data["plots"] = records(p)

    vi = rd("plot_vi_timeseries")
    if vi is not None:
        vi = vi[vi["clear"]]
        data["vi_cols"] = ["date", "sensor", "ndvi", "ndmi", "evi"]
        data["vi"] = by_plot(vi, "plotID", data["vi_cols"])
    season = rd("plot_season")
    if season is not None:
        data["season_cols"] = [c for c in season.columns if c != "plotID"]
        data["season"] = by_plot(season, "plotID", data["season_cols"])
    crops = rd("plot_crop_history")
    if crops is not None:
        data["crop_cols"] = ["year", "crop_group", "share", "source"]
        data["crops"] = by_plot(crops, "unit_id", data["crop_cols"])
    aer = rd("plot_aerial")
    if aer is not None:
        data["aerial_cols"] = ["date", "source", "date_precision", "gsd_m", "ndvi_mean", "ndvi_std", "exg_mean",
                               "exg_std", "green_frac", "preview"]
        data["aerial"] = by_plot(aer, "plotID", data["aerial_cols"])
    chem = rd("neon_chem")
    if chem is not None:
        data["chem_cols"] = ["collectDate", "ph_water", "organic_c_pct", "total_n_pct", "cn_ratio", "soil_moisture"]
        data["chem"] = by_plot(chem, "plotID", data["chem_cols"])
    inn = rd("neon_inorganic_n")
    if inn is not None:
        data["inorg_cols"] = ["collectDate", "ammonium_n_mgkg", "nitrate_n_mgkg", "net_n_min_mgkg_d", "net_nitrif_mgkg_d"]
        data["inorg"] = by_plot(inn, "plotID", data["inorg_cols"])

    mgmt = rd("neon_management_events")
    if mgmt is not None:
        data["mgmt_cols"] = ["date", "type", "what", "method", "scope", "date_quality"]
        data["mgmt"] = by_plot(mgmt, "plotID", data["mgmt_cols"])
    cover = rd("neon_plant_cover")
    if cover is not None:
        data["cover_cols"] = [c for c in cover.columns if c != "plotID"]
        data["cover"] = by_plot(cover, "plotID", data["cover_cols"])

    feats = rd("event_features")
    if feats is not None:
        data["feat_cols"] = ["modality", "role", "variable", "window", "value", "value_text", "obs_date", "lag_days", "source"]
        data["features"] = {k: records(g, data["feat_cols"]) for k, g in feats.groupby("event_id")}
        bio = set(ev.loc[ev.has_metagenome | ev.has_its, "event_id"])
        fb = feats[feats.event_id.isin(bio)]
        cov = fb.groupby(["modality", "role", "window"]).agg(n=("event_id", "nunique"), lag=("lag_days", "median")).reset_index()
        cov["share"] = cov["n"] / max(len(bio), 1)
        data["coverage"] = records(cov, ["modality", "role", "window", "n", "share", "lag"])
        data["n_bio_events"] = len(bio)
        # coverage per site-year for each modality (any window)
        e2 = ev[ev.event_id.isin(bio)][["event_id", "site", "year"]]
        m = fb[["event_id", "modality"]].drop_duplicates().merge(e2, on="event_id")
        sy = m.groupby(["modality", "site", "year"]).size().rename("n").reset_index()
        tot = e2.groupby(["site", "year"]).size().rename("tot").reset_index()
        sy = sy.merge(tot, on=["site", "year"])
        data["coverage_sy"] = records(sy, ["modality", "site", "year", "n", "tot"])
        data["site_years"] = records(tot, ["site", "year", "tot"])

    table = rd("event_table")
    if table is not None:
        num = [c for c in table.columns if pd.api.types.is_numeric_dtype(table[c]) and not pd.api.types.is_bool_dtype(table[c])
               and table[c].notna().sum() >= 5 and c not in ("year", "doy")]
        data["table_cols"] = ["event_id", "site", "plotID", "year"] + num
        data["table"] = records(table, data["table_cols"])

    its = rd("its_genus")
    if its is not None:
        its = events.assign_events(its.rename(columns={"collectDate": "date"}))
        top = (its[its["rel_abund_pct"] > 0].sort_values("rel_abund_pct", ascending=False)
               .groupby("event_id").head(12))
        data["its_top"] = {k: records(g, ["genus", "rel_abund_pct", "total_reads", "n_cores", "product"])
                           for k, g in top.groupby("event_id")}
    mg = rd("joined_metagenomes")
    if mg is not None:
        mg = events.assign_events(mg)
        cols = ["metagenome_key", "n_ko_genes", "ko_depth_ok", "kraken_total_reads", "pooling_check",
                "n_fungal_cores_ok"] + [c for c in mg.columns if c.startswith(("ko_", "bac_share_")) and c != "ko_depth_ok"]
        data["mg_cols"] = cols
        data["mg"] = {k: records(g, cols) for k, g in mg.groupby("event_id")}

    OUT.mkdir(parents=True, exist_ok=True)
    html = (Path(__file__).with_name("inspect_template.html")).read_text()
    html = html.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    (OUT / "index.html").write_text(html)
    print(f"wrote {OUT / 'index.html'} ({(OUT / 'index.html').stat().st_size / 1e6:.1f} MB), "
          f"{len(data['datasets'])} tables, {len(data['events'])} events")


if __name__ == "__main__":
    main()
