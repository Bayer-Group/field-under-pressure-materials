"""SSURGO via USDA Soil Data Access (SDA): point -> mukey, mukey -> properties."""
from __future__ import annotations

import math
from collections import Counter

import numpy as np
import pandas as pd

from . import http

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"


def sda_query(sql: str) -> pd.DataFrame:
    """Run a SQL query against SDA (cached). Returns an empty frame when no rows."""
    def fetch():
        r = http.post(SDA_URL, json={"query": sql, "format": "JSON+COLUMNNAME"})
        txt = r.text.strip()
        return r.json() if txt else {"Table": []}

    res = http.cached("sda", sql, fetch)
    rows = res.get("Table") or []
    if len(rows) < 1:
        return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=rows[0])


def point_mukey(lat: float, lon: float) -> str | None:
    sql = f"SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('POINT({lon:.7f} {lat:.7f})')"
    df = sda_query(sql)
    if df.empty:
        return None
    return str(df.iloc[0, 0])


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def compute_awc100(hz: pd.DataFrame) -> float:
    """AWC to 100 cm (mm) = sum awc_r * (min(hzdepb,100) - hzdept) * 10 over horizons with hzdept < 100.
    hz columns: hzdept_r, hzdepb_r (cm), awc_r (cm/cm). NaN if no horizon has awc."""
    h = hz[_num(hz["hzdept_r"]) < 100].copy()
    awc = _num(h["awc_r"])
    thick = np.minimum(_num(h["hzdepb_r"]), 100) - _num(h["hzdept_r"])
    contrib = awc * thick * 10
    if contrib.notna().sum() == 0:
        return float("nan")
    return float(contrib.sum(skipna=True))


def mukey_properties(mukeys: list[str]) -> pd.DataFrame:
    """One row per mukey: dominant major component's surface-horizon soil properties."""
    mukeys = sorted({str(m) for m in mukeys if m is not None})
    out = []
    for i in range(0, len(mukeys), 200):
        chunk = mukeys[i:i + 200]
        inlist = ",".join(f"'{m}'" for m in chunk)
        comp = sda_query(
            "SELECT mu.mukey, mu.muname, c.cokey, c.compname, c.comppct_r, c.drainagecl "
            "FROM mapunit mu INNER JOIN component c ON c.mukey = mu.mukey "
            f"WHERE mu.mukey IN ({inlist}) AND c.majcompflag = 'Yes'")
        if comp.empty:
            continue
        comp["comppct_r"] = _num(comp["comppct_r"])
        comp = (comp.sort_values(["mukey", "comppct_r"], ascending=[True, False])
                .drop_duplicates("mukey"))
        cokeys = ",".join(f"'{c}'" for c in comp["cokey"])
        hz = sda_query(
            "SELECT cokey, hzdept_r, hzdepb_r, awc_r, ph1to1h2o_r, claytotal_r, om_r, caco3_r, ec_r "
            f"FROM chorizon WHERE cokey IN ({cokeys}) ORDER BY cokey, hzdept_r")
        rows = {}
        if not hz.empty:
            for cokey, g in hz.groupby("cokey"):
                surf = g[_num(g["hzdept_r"]) == 0]
                s = surf.iloc[0] if len(surf) else None
                rows[cokey] = dict(
                    ph_surface=_num(pd.Series([s["ph1to1h2o_r"]])).iloc[0] if s is not None else np.nan,
                    clay_pct=_num(pd.Series([s["claytotal_r"]])).iloc[0] if s is not None else np.nan,
                    om_pct=_num(pd.Series([s["om_r"]])).iloc[0] if s is not None else np.nan,
                    caco3_pct=_num(pd.Series([s["caco3_r"]])).iloc[0] if s is not None else np.nan,
                    ec_dsm=_num(pd.Series([s["ec_r"]])).iloc[0] if s is not None else np.nan,
                    awc100_mm=compute_awc100(g),
                )
        for _, c in comp.iterrows():
            d = rows.get(c["cokey"], {})
            out.append(dict(
                mukey=str(c["mukey"]), muname=c["muname"], compname=c["compname"],
                drainage_class=c["drainagecl"] if c["drainagecl"] not in ("", None) else np.nan,
                ph_surface=d.get("ph_surface", np.nan), clay_pct=d.get("clay_pct", np.nan),
                om_pct=d.get("om_pct", np.nan), caco3_pct=d.get("caco3_pct", np.nan),
                ec_dsm=d.get("ec_dsm", np.nan), awc100_mm=d.get("awc100_mm", np.nan)))
    cols = ["mukey", "muname", "compname", "ph_surface", "clay_pct", "om_pct", "caco3_pct",
            "ec_dsm", "awc100_mm", "drainage_class"]
    return pd.DataFrame(out, columns=cols)


def offset_points(lat: float, lon: float, d_m: float = 15.0):
    dlat = d_m / 111320.0
    dlon = d_m / (111320.0 * math.cos(math.radians(lat)))
    return [(lat, lon), (lat + dlat, lon), (lat - dlat, lon), (lat, lon + dlon), (lat, lon - dlon)]


def plot_soil(lat: float, lon: float) -> dict:
    """Modal mukey over centroid + 4 points at +/-15 m; mukey_share = count/5."""
    keys = [point_mukey(a, b) for a, b in offset_points(lat, lon)]
    valid = [k for k in keys if k]
    if not valid:
        return {"mukey": None, "mukey_share": float("nan")}
    # tie-break: prefer the centroid's mukey
    cnt = Counter(valid)
    top = max(cnt.values())
    cands = [k for k, v in cnt.items() if v == top]
    mk = keys[0] if keys[0] in cands else cands[0]
    res = {"mukey": mk, "mukey_share": cnt[mk] / 5}
    props = mukey_properties([mk])
    if len(props):
        res.update({k: v for k, v in props.iloc[0].to_dict().items() if k != "mukey"})
    return res
