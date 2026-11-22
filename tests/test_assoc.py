"""Association scan: non-linear dependence, optimum detection, batch confounding. No data needed."""
import numpy as np
import pandas as pd
from scipy import stats

from cropfit import assoc


def test_hump_is_seen_by_dcor_and_quadratic_but_not_by_rank_correlation():
    rng = np.random.default_rng(1)
    x = rng.uniform(5, 8, 120)
    y = np.exp(-((x - 6.5) / 0.5) ** 2) + rng.normal(0, 0.05, 120)       # bell-shaped response to pH
    assert abs(stats.spearmanr(x, y)[0]) < 0.2
    d, p = assoc.dcor_perm(x, y, rng=np.random.default_rng(0))
    assert d > 0.4 and p < 0.01
    q = assoc.quadratic(x, y)
    assert q["p_curve"] < 0.001 and q["curvature"] < 0 and q["turning_inside"] and abs(q["turning_point"] - 6.5) < 0.2
    assert assoc.shape(0.0, q) == "hump"
    noise = assoc.dcor_perm(x, rng.normal(size=120), rng=np.random.default_rng(0))
    assert noise[1] > 0.05


def test_batch_difference_alone_gives_no_adjusted_association():
    rng = np.random.default_rng(2)
    t = pd.DataFrame({"site": "S", "year": np.repeat([2017, 2022], 40), "plotID": np.tile(np.arange(20), 4).astype(str)})
    shift = (t.year == 2022) * 5.0                                       # both variables jump between years
    t["env__x__at_sample"] = shift + rng.normal(size=80)
    t["its_share_A"] = (shift + rng.normal(size=80) + 3).clip(lower=0.01)
    r = assoc.scan_pair(t, "env__x__at_sample", "its_share_A", np.random.default_rng(0))
    assert r["rho"] > 0.6 and abs(r["rho_adj"]) < 0.25 and r["p"] > 0.05
    t["its_share_B"] = (2 * t["env__x__at_sample"] + rng.normal(0, 0.3, 80) + 6).clip(lower=0.01)
    r = assoc.scan_pair(t, "env__x__at_sample", "its_share_B", np.random.default_rng(0))
    assert r["rho_adj"] > 0.7 and r["p"] < 0.01 and r["shape"] == "rising" and r["rho_within_plot"] > 0.5


def test_scan_pair_skips_thin_data_and_timing_labels():
    t = pd.DataFrame({"site": "S", "year": 2020, "plotID": "p", "a__x__static": [1.0] * 30, "its_share_A": np.arange(30.0)})
    assert assoc.scan_pair(t, "a__x__static", "its_share_A") is None      # predictor does not vary
    assert assoc.timing("weather__prcp_mm__antecedent_30d") == "before"
    assert assoc.timing("season__ndvi_peak__prior_t-1") == "before"
    assert assoc.timing("soil_map__ph_surface__static") == "constant"
    assert assoc.timing("greenness__ndvi__at_sample") == "at sampling"
    assert assoc.timing("season__ndvi_peak__season").startswith("around")


def test_bh():
    q = assoc.bh(pd.Series([0.01, 0.04, 0.03, np.nan, 0.5]))
    assert np.allclose(q.dropna().values, [0.04, 0.04 * 4 / 3, 0.04 * 4 / 3, 0.5]) and np.isnan(q[3])
