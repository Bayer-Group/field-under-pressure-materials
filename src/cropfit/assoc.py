"""Association scan between microbiome columns and environmental columns of the event table.

What it can and cannot say. The data are observations of 28 plots at two sites, not experiments, so nothing
here proves cause. The scan instead asks, for every pair, a ladder of harder questions:

1. Is there any dependence, of any shape?            distance correlation + permutation test
2. Is it monotonic or does it have an optimum?        Spearman rho; quadratic fit on sqrt(share), which is the
                                                      Gaussian-optimum ("bell") response when concave
3. Does it survive removing batch differences?        everything is computed within site x year: values are
                                                      centred per batch and permuted only inside a batch, so a
                                                      difference between sites, years or sequencing pipelines
                                                      cannot produce it
4. Does it survive removing constant plot differences? rho on values centred per plot (plots sampled >= 2 times)
5. Could the environment variable be the cause at all? `timing`: measured before sampling, at sampling,
                                                      or (partly) after it

A pair that passes 1-4 with a `before` predictor is a candidate worth an experiment, no more. Events of one
plot are not independent, so p-values are optimistic; q-values (Benjamini-Hochberg) limit false discoveries
across the many pairs tested.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

RESPONSE_PREFIXES = ("its_share_", "bac_share_", "ko_")
# total abundance (qPCR copies per ng DNA) is a property of the community too: used as response and predictor
EXTRA_RESPONSES = ("microbial_abundance__fungal_copies__at_sample", "microbial_abundance__bacterial_copies__at_sample")
SKIP_VARIABLES = ("lag_days", "gsd_m", "n_clear_gs", "mukey_share", "peak_doy", "greenup_doy", "senescence_doy")
BEFORE = ("antecedent_", "last_before", "prior_t", "year_to_date")
MIN_N = 20


def timing(col: str) -> str:
    """When the predictor was fixed relative to the sampling date (from the window part of its name)."""
    w = col.rsplit("__", 1)[-1]
    if w == "static":
        return "constant"
    if w.startswith(BEFORE):
        return "before"
    if w in ("season", "anomaly", "nearest_flight", "nearest_survey"):
        return "around (may be after)"
    return "at sampling"


def centre(v: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Subtract the group mean; members of single-member groups become NaN (no within-group information)."""
    s = pd.Series(v)
    g = s.groupby(groups)
    out = s - g.transform("mean")
    out[g.transform("size") < 2] = np.nan
    return out.to_numpy()


def _dc(v: np.ndarray) -> np.ndarray:
    d = np.abs(v[:, None] - v[None, :])
    return d - d.mean(0) - d.mean(1)[:, None] + d.mean()


def dcor(x: np.ndarray, y: np.ndarray) -> float:
    """Distance correlation (0 = independent, 1 = one is a function of the other); sees any shape of
    dependence, including a hump that leaves the ordinary correlation near zero."""
    a, b = _dc(np.asarray(x, float)), _dc(np.asarray(y, float))
    den = np.sqrt((a * a).mean() * (b * b).mean())
    return float(np.sqrt(max((a * b).mean(), 0) / den)) if den > 0 else 0.0


def dcor_perm(x, y, groups=None, n_perm: int = 199, n_more: int = 1999, rng=None) -> tuple[float, float]:
    """(dcor, permutation p). y is shuffled only within `groups`. Pairs that look promising after n_perm
    shuffles (p <= 0.02) get n_more for a finer p."""
    rng = rng or np.random.default_rng(0)
    x, y = np.asarray(x, float), np.asarray(y, float)
    a, b = _dc(x), _dc(y)
    den = np.sqrt((a * a).mean() * (b * b).mean())
    if den <= 0:
        return 0.0, 1.0
    obs = (a * b).mean()
    idx = np.arange(len(x))
    blocks = [idx] if groups is None else [idx[groups == g] for g in pd.unique(groups)]

    def run(k):
        hits = 0
        for _ in range(k):
            p = idx.copy()
            for bl in blocks:
                p[bl] = rng.permutation(bl)
            hits += (a * b[np.ix_(p, p)]).mean() >= obs
        return hits
    hits, total = run(n_perm), n_perm
    if (hits + 1) / (total + 1) <= 0.02 and n_more > n_perm:
        hits, total = hits + run(n_more - n_perm), n_more
    return float(np.sqrt(max(obs, 0) / den)), (hits + 1) / (total + 1)


def quadratic(x: np.ndarray, y: np.ndarray, groups: np.ndarray | None = None) -> dict:
    """y ~ [group intercepts] + x + x^2 by least squares. Returns p_curve (F-test of the x^2 term), the sign
    of the curvature, the turning point and whether it lies inside the central 80% of x, and the share of
    within-group variance explained by the line and by the curve (r2_line, r2_curve)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    g = np.zeros(n, int) if groups is None else pd.factorize(groups)[0]
    d = np.eye(g.max() + 1)[g]
    xs = (x - x.mean()) / (x.std() or 1.0)

    def rss(cols):
        m = np.column_stack([d] + cols)
        beta, *_ = np.linalg.lstsq(m, y, rcond=None)
        return float(((y - m @ beta) ** 2).sum()), beta, m.shape[1]
    r0, _, _ = rss([])
    r1, _, _ = rss([xs])
    r2, beta, k = rss([xs, xs ** 2])
    out = dict(r2_line=1 - r1 / r0 if r0 > 0 else np.nan, r2_curve=1 - r2 / r0 if r0 > 0 else np.nan,
               p_curve=np.nan, curvature=0.0, turning_point=np.nan, turning_inside=False)
    df = n - k
    if df > 0 and r2 > 0:
        out["p_curve"] = float(stats.f.sf((r1 - r2) / (r2 / df), 1, df))
        b1, b2 = beta[-2], beta[-1]
        out["curvature"] = float(b2)
        if b2 != 0:
            tp = -b1 / (2 * b2) * (x.std() or 1.0) + x.mean()
            lo, hi = np.percentile(x, [10, 90])
            out.update(turning_point=float(tp), turning_inside=bool(lo <= tp <= hi))
    return out


def shape(rho: float, q: dict, alpha: float = 0.05) -> str:
    """hump = optimum inside the observed range (bell-shaped response); valley = the opposite."""
    if q["p_curve"] < alpha and q["turning_inside"]:
        return "hump" if q["curvature"] < 0 else "valley"
    if not np.isfinite(rho) or abs(rho) < 0.1:
        return "none clear"
    return "rising" if rho > 0 else "falling"


def bh(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg q-values (NaN stays NaN)."""
    q = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    m = len(v)
    if m:
        adj = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
        q[adj.index] = adj
    return q


def responses(table: pd.DataFrame) -> list[str]:
    return [c for c in table.columns if (c.startswith(RESPONSE_PREFIXES) or c in EXTRA_RESPONSES)
            and c not in ("ko_depth_ok", "ko_marker") and pd.api.types.is_numeric_dtype(table[c])]


def predictors(table: pd.DataFrame) -> list[str]:
    return [c for c in table.columns if "__" in c and pd.api.types.is_numeric_dtype(table[c])
            and c.split("__")[1] not in SKIP_VARIABLES]


def scan_pair(d: pd.DataFrame, x: str, y: str, rng=None) -> dict | None:
    """All statistics for one pair on the rows of d (needs columns x, y, site, year, plotID).
    Returns None when there is too little to work with."""
    s = d[[x, y, "site", "year", "plotID"]].dropna(subset=[x, y])
    if len(s) < MIN_N or s[x].nunique() < 5 or (s[y] > 0).mean() < 0.2 or s[y].nunique() < 5:
        return None
    xv = s[x].to_numpy(float)
    yv = np.sqrt(s[y].clip(lower=0).to_numpy(float))            # shares and gene ratios: sqrt tames the skew
    batch = (s["site"] + "_" + s["year"].astype(str)).to_numpy()
    out = dict(response=y, predictor=x, timing=timing(x), n=len(s), n_plots=int(s["plotID"].nunique()),
               rho=float(stats.spearmanr(xv, yv)[0]))
    xc, yc = centre(xv, batch), centre(yv, batch)
    ok = np.isfinite(xc) & np.isfinite(yc)
    if ok.sum() < MIN_N or np.unique(xc[ok]).size < 5:
        return None                                             # predictor does not vary inside batches
    out["n_adj"] = int(ok.sum())
    out["rho_adj"] = float(stats.spearmanr(xc[ok], yc[ok])[0])
    out["dcor_adj"], out["p"] = dcor_perm(xc[ok], yc[ok], batch[ok], rng=rng)
    q = quadratic(xv[ok], yv[ok], batch[ok])
    out.update(q)
    out["shape"] = shape(out["rho_adj"], q)
    if out["shape"] not in ("hump", "valley"):
        out["turning_point"] = np.nan                           # only meaningful when there is an optimum
    plot = s["plotID"].to_numpy()
    xp, yp = centre(xv, plot), centre(yv, plot)
    okp = np.isfinite(xp) & np.isfinite(yp)
    if okp.sum() >= MIN_N and np.unique(np.round(xp[okp], 9)).size >= 5:
        out["rho_within_plot"], out["n_within_plot"] = float(stats.spearmanr(xp[okp], yp[okp])[0]), int(okp.sum())
    return out


def scan(table: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Every response x predictor pair, per site and for both sites together (scope). Adds q (per scope)."""
    rng = np.random.default_rng(seed)
    ys, xs = responses(table), predictors(table)
    rows = []
    for scope in list(sorted(table["site"].unique())) + ["both"]:
        d = table if scope == "both" else table[table["site"] == scope]
        for y in ys:
            dy = d if not y.startswith("ko_") else d[d["ko_depth_ok"] == True]  # noqa: E712 gene groups need depth
            for x in xs:
                if x.split("__")[0] == y.split("__")[0] and "__" in y:
                    continue                                    # qPCR against qPCR of the same extract
                r = scan_pair(dy, x, y, rng)
                if r:
                    rows.append(dict(scope=scope, **r))
    out = pd.DataFrame(rows)
    if len(out):
        out["q"] = out.groupby("scope")["p"].transform(bh)
        out = out.sort_values(["p", "dcor_adj"], ascending=[True, False]).reset_index(drop=True)
    return out
