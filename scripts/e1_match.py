"""E1 step 1-2: match ITS points to LUCAS harmonised 2018 and build crop-history labels."""
import sys, json
sys.path.insert(0, "src")
import numpy as np, pandas as pd
from sklearn.neighbors import BallTree
from pathlib import Path
R = Path("."); OUT = R / "outputs/e1"; OUT.mkdir(parents=True, exist_ok=True)

its = pd.read_csv("resources/lucas_fungi_genus.csv")
its = its[(its.paper_ID == "Labouyrie_2023_BBS") & (its.environment_type == "cropland")].reset_index(drop=True)
h = pd.read_csv("data/raw/lucas/lucas_harmo_slim.csv", dtype={"lc1": str})
h18 = h[h.year == 2018].copy()
okg = h18.gps_lat.between(30, 75) & h18.gps_long.between(-35, 45)
okt = h18.th_lat.between(30, 75) & h18.th_long.between(-35, 45)
print("2018 rows", len(h18), "valid GPS", okg.sum(), "valid th", okt.sum())

def nearest(lat, lon):
    t = BallTree(np.radians(np.c_[lat, lon]), metric="haversine")
    d, i = t.query(np.radians(its[["latitude", "longitude"]].values), k=1)
    return d[:, 0] * 6371008.8, i[:, 0]

g = h18[okg].reset_index(drop=True); th = h18[okt].reset_index(drop=True)
dg, ig = nearest(g.gps_lat.values, g.gps_long.values)
dt, it = nearest(th.th_lat.values, th.th_long.values)
its["dist_gps_m"] = dg; its["pid_gps"] = g.point_id.values[ig]
its["dist_th_m"] = dt; its["pid_th"] = th.point_id.values[it]
q = lambda x: {f"p{p}": float(np.percentile(x, p)) for p in (10, 50, 75, 90, 95, 100)}
print("GPS dist m", q(dg)); print("theoretical dist m", q(dt))
for thr in (1, 10, 100, 1000): print(thr, "m: gps", (dg <= thr).mean().round(3), "th", (dt <= thr).mean().round(3))
# rule: GPS first (fallback to theoretical when GPS fails)
best_is_gps = dg <= dt
d = np.where(best_is_gps, dg, dt)
its["match_dist_m"] = d; its["match_via"] = np.where(best_is_gps, "gps", "theoretical")
its["point_id"] = np.where(best_is_gps, its.pid_gps, its.pid_th)
cov1 = float((d <= 1).mean())
thr = 1.0 if cov1 >= 0.90 else 100.0
flag = thr > 1
its["matched"] = d <= thr
print("coverage <=1 m", cov1, "threshold", thr, "matched", int(its.matched.sum()))
# duplicate point ids?
print("dup point_id among matched:", its[its.matched].point_id.duplicated().sum())
m = its[its.matched].sort_values("match_dist_m")
ndup = int(m.point_id.duplicated().sum())
m = m[~m.point_id.duplicated()].sort_index().copy()  # a point_id may be claimed by 2 ITS rows: keep closest

# LC1 per year
piv = h[h.point_id.isin(m.point_id) & h.year.isin([2009, 2012, 2015, 2018])]
piv = piv.drop_duplicates(["point_id", "year"]).pivot(index="point_id", columns="year", values="lc1")
piv.columns = [f"lc1_{c}" for c in piv.columns]
m = m.merge(piv, left_on="point_id", right_index=True, how="left")
yrs = ["lc1_2009", "lc1_2012", "lc1_2015", "lc1_2018"]
# Cereals B11-B19 by LUCAS C3 legend (B11 common wheat ... B19 other cereals); B16 = maize.
# (rules/lucas_lc1_groups.csv does not exist; defined here.)
def is_cer(x): return isinstance(x, str) and x[:2] == "B1" and x[:3] in {f"B1{i}" for i in range(1, 10)}
obs = m[yrs].notna()
m["n_obs"] = obs.sum(axis=1)
cer = m[yrs].apply(lambda c: c.map(is_cer)) & obs
m["maize_legacy"] = np.where(m[["lc1_2009", "lc1_2012", "lc1_2015"]].notna().any(axis=1),
                             m[["lc1_2009", "lc1_2012", "lc1_2015"]].apply(lambda r: any(x == "B16" for x in r), axis=1).astype(float), np.nan)
m["cereal_frac"] = np.where(m.n_obs >= 3, cer.sum(axis=1) / m.n_obs.replace(0, np.nan), np.nan)
m["cereal_dominance"] = np.where(m.n_obs >= 3, (m.cereal_frac >= 0.75).astype(float), np.nan)
print(m.n_obs.value_counts().sort_index().to_dict())
print("maize_legacy", m.maize_legacy.value_counts(dropna=False).to_dict())
print("cereal_dom", m.cereal_dominance.value_counts(dropna=False).to_dict())
print(m.lc1_2018.value_counts().head(12).to_dict())
m.to_csv(OUT / "e1_matched.csv", index=False)
json.dump({"n_its": len(its), "n_matched": int(its.matched.sum()), "coverage_le_1m": cov1, "threshold_m": thr,
           "flag_100m": bool(flag), "n_dropped_dup_point_id": ndup, "n_final": len(m), "dist_gps_m": q(dg), "dist_theoretical_m": q(dt), "dist_used_m": q(d),
           "via": its.match_via.value_counts().to_dict(),
           "n_valid_2018_gps": int(okg.sum()), "n_obs_years": m.n_obs.value_counts().sort_index().to_dict()},
          open(OUT / "match_stats.json", "w"), indent=1)
