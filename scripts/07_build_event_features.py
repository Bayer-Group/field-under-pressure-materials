"""Link every dataset in config/modalities.yaml to the sampling events.

Offline. Reads data/processed/events.parquet and the per-plot tables, writes
- event_features.parquet  long: event_id, modality, role, variable, window, value | value_text, obs_date,
                          lag_days, n_obs, source (see cropfit/link.py)
- event_table.parquet     wide: one row per event with biology (metagenome or ITS): event columns, biology
                          (joined_metagenomes, ITS plot-date shares) and every linked feature as
                          <modality>__<variable>__<window>.
Modalities whose table is missing are skipped and reported.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
import yaml
from cropfit import events, link
from cropfit.config import PROCESSED, ROOT

OPS = {"static": link.static, "nearest": link.nearest, "annual": link.annual, "weather": link.weather,
       "last_before": link.last_before}
OPTS = {"static": ["key"], "nearest": ["date", "max_lag_days", "direction", "window", "source_col"],
        "annual": ["key", "year", "offsets", "anomaly"], "weather": ["key"],
        "last_before": ["key", "date", "type_col", "max_days", "text_col"]}


def build_features(ev: pd.DataFrame, registry: dict) -> tuple[pd.DataFrame, list[str]]:
    parts, skipped = [], []
    for name, m in registry.items():
        f = PROCESSED / f"{m['table']}.parquet"
        if not f.exists():
            skipped.append(f"{name} ({m['table']}.parquet missing)")
            continue
        t = pd.read_parquet(f)
        for col, val in (m.get("where") or {}).items():
            t = t[t[col] == val]
        kw = {k: m[k] for k in OPTS[m["link"]] if k in m}
        if m["link"] in ("static", "nearest", "annual"):
            kw.update(variables=m.get("variables", []), text=m.get("text", []))
        if m["link"] == "nearest" and "key" in m:
            t = t.rename(columns={m["key"]: "plotID"})
        out = OPS[m["link"]](ev, t, modality=name, role=m["role"], **kw)
        if "source" in out and out["source"].isna().any():
            out["source"] = out["source"].where(out["source"].notna(), m.get("source"))
        parts.append(out)
    return pd.concat(parts, ignore_index=True), skipped


def biology(ev: pd.DataFrame) -> pd.DataFrame:
    """Per event: the metagenome row (first one when a visit has two) and ITS plot-date fungal shares."""
    out = ev.copy()
    f = PROCESSED / "joined_metagenomes.parquet"
    if f.exists():
        mg = events.assign_events(pd.read_parquet(f)).drop(columns=["event_date", "date", "site", "plotID", "year"])
        out = out.merge(mg.drop_duplicates("event_id"), on="event_id", how="left")
    f = PROCESSED / "plot_its_timeseries.parquet"
    if f.exists():
        its = pd.read_parquet(f)
        keep = ["plotID", "collectDate", "n_cores", "total_reads", "its_below_threshold_share"] + \
               [c for c in its.columns if c.startswith("bio_its_share_")]
        its = events.assign_events(its[keep].rename(columns={"collectDate": "date"}))
        its = its.drop(columns=["event_date", "date", "plotID"]).rename(
            columns={"n_cores": "its_n_cores", "total_reads": "its_total_reads"})
        its.columns = [c.replace("bio_its_share_", "its_share_") for c in its.columns]
        out = out.merge(its.drop_duplicates("event_id"), on="event_id", how="left")
    return out


if __name__ == "__main__":
    ev = events.load_events()
    registry = yaml.safe_load((ROOT / "config" / "modalities.yaml").read_text())["modalities"]
    feats, skipped = build_features(ev, registry)
    feats.to_parquet(PROCESSED / "event_features.parquet", index=False)
    bio = ev[ev.has_metagenome | ev.has_its]
    table = biology(bio).merge(link.wide(feats), on="event_id", how="left")
    table.to_parquet(PROCESSED / "event_table.parquet", index=False)

    # coverage: share of biology events with at least one value, and how far in time the observation was
    fb = feats[feats.event_id.isin(set(bio.event_id))]
    cov = fb.groupby(["modality", "window"]).agg(events=("event_id", "nunique"),
                                                 lag_median=("lag_days", "median"),
                                                 lag_min=("lag_days", "min"), lag_max=("lag_days", "max"))
    cov.insert(1, "share", (cov["events"] / len(bio)).round(2))
    print(f"{len(ev)} events, {len(bio)} with biology; {len(feats)} feature rows; event_table {table.shape}")
    print(cov.to_string())
    for s in skipped:
        print("SKIPPED", s)
