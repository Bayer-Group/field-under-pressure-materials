import numpy as np
import pandas as pd

from cropfit.daymet import summarise_yearly, yearly_climate
from cropfit.ssurgo import compute_awc100


def _plot_id(name):
    return name.replace(".basePlot.bgc", "")


def test_plot_id_parsing():
    assert _plot_id("STER_026.basePlot.bgc") == "STER_026"
    assert _plot_id("KONA_003.basePlot.bgc") == "KONA_003"


def test_awc100_clips_to_100cm():
    hz = pd.DataFrame({"hzdept_r": ["0", "20", "80", "120"], "hzdepb_r": ["20", "80", "150", "200"],
                       "awc_r": ["0.10", "0.15", "0.20", "0.30"]})
    # 0.10*20*10 + 0.15*60*10 + 0.20*20*10 = 20 + 90 + 40
    assert abs(compute_awc100(hz) - 150.0) < 1e-9


def test_awc100_all_missing_is_nan():
    hz = pd.DataFrame({"hzdept_r": ["0"], "hzdepb_r": ["30"], "awc_r": [None]})
    assert np.isnan(compute_awc100(hz))


def _synthetic_year(y=2020):
    dates = pd.date_range(f"{y}-01-01", f"{y}-12-30" if y % 4 == 0 else f"{y}-12-31")
    df = pd.DataFrame({"date": dates})
    df["year"], df["yday"] = y, np.arange(1, len(df) + 1)
    df["tmax"], df["tmin"], df["prcp"] = 20.0, 5.0, 1.0
    # frost until 30 Apr and from 1 Oct
    df.loc[df.date <= f"{y}-04-30", "tmin"] = -2.0
    df.loc[df.date >= f"{y}-10-01", "tmin"] = -2.0
    # 3 hot days in July
    df.loc[df.date.isin(pd.to_datetime([f"{y}-07-10", f"{y}-07-11", f"{y}-07-12"])), "tmax"] = 40.0
    return df


def test_gdd_and_frost():
    yc = yearly_climate(_synthetic_year(2021))
    r = yc.iloc[0]
    # 153 days May-Sep; tmax 20 / tmin 5 -> (20+10)/2-10 = 5; 3 hot days (30+10)/2-10 = 10
    assert abs(r.gdd10_may_sep - (150 * 5 + 3 * 10)) < 1e-9
    last_spring = pd.Timestamp("2021-04-30").day_of_year
    first_fall = pd.Timestamp("2021-10-01").day_of_year
    assert r.frost_free_days == first_fall - last_spring - 1
    assert r.hot_days_jul_aug == 3
    s = summarise_yearly(yc)
    assert s["p_june_heat"] == 0.0 and s["p_wet_may"] == 0.0
