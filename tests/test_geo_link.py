"""Event registry, footprint weights, weather windows, satellite masks and the event linking operators.
No network, no data."""
import numpy as np
import pandas as pd
from affine import Affine

from cropfit import daymet, events, link, satellite, stac, terrain


def test_assign_events_merges_visits_within_gap():
    o = pd.DataFrame({"plotID": ["A", "A", "A", "B"], "date": ["2022-06-07", "2022-06-09", "2022-06-20", "2022-06-08"]})
    e = events.assign_events(o)
    assert list(e.event_id) == ["A_20220607", "A_20220607", "A_20220620", "B_20220608"]


def test_build_events_flags_sources():
    mg = pd.DataFrame({"plotID": ["A", "A"], "date": ["2022-06-07", "2022-06-07"]})
    its = pd.DataFrame({"plotID": ["A"], "collectDate": [pd.Timestamp("2022-06-08").date()]})
    chem = pd.DataFrame({"plotID": ["A", "B"], "collectDate": [pd.Timestamp("2022-06-07").date()] * 2})
    ev = events.build_events(mg, its, chem).set_index("event_id")
    a = ev.loc["A_20220607"]
    assert a.has_metagenome and a.has_its and a.has_chem and a.n_metagenomes == 2 and a.site == "A"[:4]
    assert not ev.loc["B_20220607"].has_metagenome


def test_footprint_weights_are_area_fractions():
    t = Affine(30, 0, 0, 0, -30, 300)                     # 30 m pixels, origin top-left (0, 300)
    (c, r, w, h), wts = stac.footprint_window(t, 60, 240, 20)   # 40 m square centred on a pixel corner
    assert (c, r, w, h) == (1, 1, 2, 2)
    assert np.allclose(wts, (20 / 30) ** 2) and np.isclose(wts.sum() * 900, 1600)
    (_, _, w, h), wts = stac.footprint_window(t, 75, 225, 20)   # centred on a pixel centre: 3x3, edges partial
    assert (w, h) == (3, 3) and np.isclose(wts.sum() * 900, 1600) and wts[1, 1] == 1.0
    assert stac.majority(np.array([[1, 1, 2], [1, 5, 2], [2, 2, 2]]), wts)[0] == 5


def test_wmean_ignores_invalid():
    a = np.array([[1.0, np.nan], [3.0, 100.0]])
    w = np.ones((2, 2))
    assert stac.wmean(a, w, np.array([[True, True], [True, False]])) == 2.0
    assert np.isnan(stac.wmean(a, w, np.zeros((2, 2), bool)))


def _daily(start="2021-01-01", end="2022-12-31"):
    d = pd.DataFrame({"date": pd.date_range(start, end)})
    d["tmax"], d["tmin"], d["prcp"] = 20.0, 10.0, 0.0
    return d


def test_event_windows():
    d = _daily()
    d.loc[d.date == "2022-06-03", "prcp"] = 12.0          # 4 days before sampling
    d.loc[d.date == "2022-05-01", "prcp"] = 3.0
    d.loc[d.date == "2022-06-07", "prcp"] = 99.0          # sampling day itself is excluded
    d.loc[d.date == "2022-05-20", "tmin"] = -1.0
    w = daymet.event_windows(d, "2022-06-07")
    assert w["prcp_7d_mm"] == 12.0 and w["prcp_30d_mm"] == 12.0 and w["prcp_90d_mm"] == 15.0
    assert w["days_since_rain5"] == 4 and w["frost_days_30d"] == 1 and w["tmean_7d_c"] == 15.0
    assert w["gdd10_ytd"] == 5.0 * 157                    # (20 + 10) / 2 - 10 for 1 Jan .. 6 Jun
    short = daymet.event_windows(d[d.date >= "2022-05-20"], "2022-06-07")
    assert short["prcp_7d_mm"] == 12.0 and np.isnan(short["prcp_30d_mm"]) and np.isnan(short["gdd10_ytd"])


def test_satellite_scaling_and_masks():
    old = satellite.to_reflectance("sentinel2", [0, 2000], {"s2:processing_baseline": "03.00"})
    new = satellite.to_reflectance("sentinel2", [0, 3000], {"s2:processing_baseline": "05.09"})
    assert np.isnan(old[0]) and old[1] == 0.2 and new[1] == 0.2
    assert np.isclose(satellite.to_reflectance("landsat", [10000], {})[0], 0.075)
    assert list(satellite.clear_mask("sentinel2", np.array([4, 5, 8, 9, 3, 11]))) == [True, True, False, False, False, False]
    clear, cloud, shadow, fill = 21824, 22280, 23888, 1
    assert list(satellite.clear_mask("landsat", np.array([clear, cloud, shadow, fill]))) == [True, False, False, False]
    i = satellite.indices(dict(red=0.1, nir=0.5, blue=0.05, swir1=0.2))
    assert np.isclose(i["ndvi"], 4 / 6) and np.isnan(i["ndre"])


def test_season_metrics_peak_and_min_obs():
    doy = np.arange(100, 300, 10)
    ndvi = 0.2 + 0.6 * np.exp(-((doy - 200) / 40.0) ** 2)
    ts = pd.DataFrame({"plotID": "A", "date": pd.Timestamp("2022-01-01") + pd.to_timedelta(doy - 1, unit="D"),
                       "ndvi": ndvi, "clear": True})
    few = ts.head(3).assign(plotID="B")
    s = satellite.season_metrics(pd.concat([ts, few])).set_index("plotID")
    assert s.loc["A", "peak_doy"] == 200 and 0.7 < s.loc["A", "ndvi_peak"] <= 0.8
    assert s.loc["A", "greenup_doy"] < 200 < s.loc["A", "senescence_doy"]
    assert s.loc["B", "n_clear"] == 3 and np.isnan(s.loc["B", "ndvi_peak"])


def _events():
    return pd.DataFrame({"event_id": ["A_1", "A_2"], "plotID": ["A", "A"], "site": ["S", "S"],
                         "date": pd.to_datetime(["2022-06-07", "2019-06-07"]), "year": [2022, 2019]})


def test_link_nearest_records_lag_and_respects_tolerance():
    obs = pd.DataFrame({"plotID": "A", "date": pd.to_datetime(["2022-06-01", "2022-06-10", "2019-07-30"]),
                        "ndvi": [0.3, 0.5, 0.9], "sensor": ["s2", "l8", "s2"]})
    f = link.nearest(_events(), obs, ["ndvi"], max_lag_days=10, source_col="sensor", modality="sat", role="response")
    assert len(f) == 1                                    # the 2019 event has nothing within 10 days: absent
    r = f.iloc[0]
    assert (r.event_id, r.value, r.lag_days, r.source, r.window) == ("A_1", 0.5, 3, "l8", "at_sample")
    b = link.nearest(_events(), obs, ["ndvi"], max_lag_days=10, direction="backward", modality="sat", role="r")
    assert b.iloc[0].value == 0.3 and b.iloc[0].lag_days == -6


def test_link_annual_offsets_and_anomaly():
    t = pd.DataFrame({"plotID": "A", "year": [2018, 2019, 2020, 2021, 2022], "peak": [0.4, 0.5, 0.6, 0.5, 0.9],
                      "crop": ["corn", "soy", "corn", "soy", "wheat"]})
    f = link.annual(_events(), t, ["peak"], ["crop"], offsets=(0, -1), anomaly=["peak"], modality="m", role="r")
    g = f.set_index(["event_id", "variable", "window"])
    assert g.loc[("A_1", "peak", "season"), "value"] == 0.9
    assert g.loc[("A_1", "crop", "prior_t-1"), "value_text"] == "soy"
    assert np.isclose(g.loc[("A_1", "peak", "anomaly"), "value"], 0.9 - 0.5)
    assert ("A_2", "peak", "prior_t-1") in g.index


def test_link_weather_and_last_before_and_wide():
    d = _daily("2021-01-01", "2022-12-31").assign(unit_id="A")
    w = link.weather(_events(), d, modality="weather", role="forcing")
    assert set(w.event_id) == {"A_1"}                     # no daily data in 2019: no rows, not zeros
    assert w[(w.variable == "prcp_mm") & (w.window == "antecedent_30d")].value.iloc[0] == 0.0
    log = pd.DataFrame({"plotID": ["A", "A"], "date": pd.to_datetime(["2022-05-01", "2022-07-01"]),
                        "type": ["tillage", "harvest"]})
    lb = link.last_before(_events(), log, "type", modality="mgmt", role="management")
    assert list(lb.variable) == ["days_since_tillage"] and lb.value.iloc[0] == 37
    wide = link.wide(pd.concat([w, lb]))
    assert "mgmt__days_since_tillage__last_before" in wide and len(wide) == 1


def test_terrain_metrics_on_a_tilted_plane():
    yy, xx = np.mgrid[0:31, 0:31]
    z = 100 + 0.1 * xx * 10 / 10.0                         # rises 0.1 m per 10 m pixel towards the east
    m = terrain.terrain_metrics(z, 10.0, 10.0, 2)
    assert np.isclose(m["slope_deg"], np.degrees(np.arctan(0.01)), atol=1e-6)
    assert np.isclose(m["aspect_deg"], 270.0) and abs(m["tpi_150m"]) < 1e-9   # faces west (downslope)
