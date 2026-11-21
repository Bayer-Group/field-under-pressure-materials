import pandas as pd
import pytest

from cropfit import config, events


@pytest.fixture
def light(tmp_path, monkeypatch):
    f = tmp_path / "light_mode.txt"
    monkeypatch.setattr(config, "LIGHT_FILE", f)
    return f


def test_off_by_default(light):
    assert config.light_plots() is None
    df = pd.DataFrame({"plotID": ["STER_006", "KONA_001"]})
    assert config.light_filter(df) is df
    assert config.sites() == list(config.regions()["windows"])


def test_plot_list_and_sites(light):
    light.write_text("# comment\nSTER 006\nster_010  # note\n\nSTER-011\n")
    assert config.light_plots() == ["STER_006", "STER_010", "STER_011"]
    assert config.sites() == ["STER"]


def test_filter_keeps_light_plots_and_site_rows(light):
    light.write_text("STER_006\nSTER_016\n")
    df = pd.DataFrame({
        "plotID": ["STER_006", None, "STER_007", None, None],
        "dnaSampleID": [None, "STER_016-M-8-20130716-GEN-DNA1", None, "KONA_001-M-1-20190619", None],
        "namedLocation": [None, None, None, None, "STER"],          # site-level row: kept
    })
    out = config.light_filter(df)
    assert list(out.index) == [0, 1, 4]


def test_default_plots_in_config():
    assert config.regions()["light_plots"] == ["STER_006", "STER_010", "STER_011", "STER_012", "STER_016"]
    geom = events.plot_geometry(config.regions()["light_plots"])     # all have coordinates
    assert len(geom) == 5


def test_build_events_restricted(light):
    light.write_text("STER_006\n")
    mg = pd.DataFrame({"plotID": ["STER_006", "STER_007"], "date": ["2022-06-07", "2022-06-07"]})
    its = pd.DataFrame({"plotID": ["KONA_001"], "collectDate": ["2019-06-19"]})
    chem = pd.DataFrame({"plotID": ["STER_006"], "collectDate": ["2022-06-08"]})
    ev = config.light_filter(events.build_events(mg, its, chem))
    assert ev["plotID"].tolist() == ["STER_006"]
