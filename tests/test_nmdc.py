import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import nmdc as N  # noqa: E402


def test_name_regex():
    p = N.parse_sample_name("KONA_001-M-16-31.5-20190619")
    assert p["plotID"] == "KONA_001" and p["date"] == "2019-06-19" and p["hz"] == "M"
    p = N.parse_sample_name("STER_026-O-3.5-10-20170601")
    assert p["hz"] == "O"
    # 2022 names carry a single depth field
    assert N.parse_sample_name("STER_006-M-21-20220607")["plotID"] == "STER_006"
    assert N.parse_sample_name("STER_6-M-1-2-20190101") is None
    assert N.parse_sample_name("garbage") is None


def _toy(tmp_path):
    txt = (
        " 90.00\t900\t900\tU\t0\tunclassified\n"
        " 10.00\t100\t0\tR\t1\troot\n"
        "  8.00\t80\t5\tD\t2\t  Bacteria\n"
        "  4.00\t40\t0\tP\t1224\t    Proteobacteria\n"
        "  2.00\t20\t20\tG\t375\t      Bradyrhizobium\n"
        "  1.00\t10\t10\tG\t286\t      Pseudomonas\n"
    )
    f = tmp_path / "k.tsv"
    f.write_text(txt)
    return f


def test_kraken_parse(tmp_path):
    rep = N.parse_kraken_report(_toy(tmp_path))
    assert len(rep) == 6 and rep["name"].iloc[2] == "Bacteria"
    s = N.kraken_summary(rep)
    assert s["kraken_total_reads"] == 1000
    assert s["kraken_bacteria_reads"] == 80
    assert abs(s["kraken_unclassified_pct"] - 90) < 1e-9
    g = N.kraken_genus(rep).set_index("genus")
    assert g.loc["Bradyrhizobium", "pct_of_bacteria"] == 25.0
    assert g.loc["Pseudomonas", "pct_of_bacteria"] == 12.5


def test_depth_gate():
    assert N.depth_gate(50_000, 20)
    assert not N.depth_gate(49_999, 500)
    assert not N.depth_gate(1_000_000, 19.9)
    assert not N.depth_gate(float("nan"), 30)


def test_ko_counts(tmp_path):
    f = tmp_path / "ko.tsv"
    f.write_text("a\t1\tKO:K00001\tx\nb\t2\tKO:K00001\tx\nc\t3\tKO:K00002\tx\n")
    assert N.parse_ko_counts(f) == {"K00001": 2, "K00002": 1}


def test_pct_within():
    df = pd.DataFrame({"site": ["A"] * 4, "year": [1] * 4, "v": [1, 2, 3, 4]})
    p, n = N.pct_within(df, "v", mask=pd.Series([True, True, True, False]))
    assert p.iloc[2] == 100 and n.iloc[0] == 3 and pd.isna(p.iloc[3])
