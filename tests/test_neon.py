import numpy as np
import pandas as pd

from cropfit import neon


def test_parse_sample_id():
    d = neon.parse_sample_id("STER_026-M-8-11.5-20130716-GEN-DNA1")
    assert d["plotID"] == "STER_026" and d["site"] == "STER" and d["horizon"] == "M"
    assert d["date"] == pd.Timestamp("2013-07-16")
    assert neon.parse_sample_id("KONA_048-M-0-26.5-20170815-GEN")["plotID"] == "KONA_048"
    assert neon.parse_sample_id("garbage") == {}


def test_percentile_rank():
    ref = pd.Series([0, 0, 1, 2, 3])
    p = neon.percentile_rank(pd.Series([0, 3, 10]), ref)
    assert p[0] == 100 * (0 + 0.5 * 2) / 5      # ties share mid-rank
    assert p[1] == 100 * (4 + 0.5) / 5
    assert p[2] == 100.0
    assert np.isnan(neon.percentile_rank(pd.Series([np.nan]), ref)[0])


def test_build_its_genus_aggregates_cores():
    rows = []
    for core, cnt in [("STER_001-M-1-1-20160101-GEN-DNA1", 10), ("STER_001-M-2-2-20160101-GEN-DNA1", 30)]:
        rows.append(dict(dnaSampleID=core, kingdom="Fungi", genus="Fusarium", individualCount=cnt))
        rows.append(dict(dnaSampleID=core, kingdom="Fungi", genus="Other", individualCount=cnt * 3))
        rows.append(dict(dnaSampleID=core, kingdom=None, genus=None, individualCount=999))
    g = neon.build_its_genus(pd.DataFrame(rows))
    f = g[g.genus == "Fusarium"].iloc[0]
    assert f.reads == 40 and f.total_reads == 160 and f.n_cores == 2 and f.rel_abund_pct == 25.0
    assert g[g.genus == "Pythium"].iloc[0].reads == 0


def test_parse_sample_id_single_depth():
    # from 2022 NEON core IDs have one depth field
    d = neon.parse_sample_id("KONA_001-M-21-20240409-GEN-DNA1")
    assert d["plotID"] == "KONA_001" and d["date"] == pd.Timestamp("2024-04-09")


def test_select_its_runs_deepest_run_then_preferred_product():
    rows = [
        # same DNA sample: two .001 runs (keep the deeper) and one .002 run (preferred product wins)
        dict(product="DP1.10081.001", dnaSampleID="A", sequencerRunID="r1", individualCount=5),
        dict(product="DP1.10081.001", dnaSampleID="A", sequencerRunID="r2", individualCount=50),
        dict(product="DP1.10081.002", dnaSampleID="A", sequencerRunID="r3", individualCount=10),
        # only in .001: deeper run kept
        dict(product="DP1.10081.001", dnaSampleID="B", sequencerRunID="r1", individualCount=7),
        dict(product="DP1.10081.001", dnaSampleID="B", sequencerRunID="r2", individualCount=3),
    ]
    out = neon.select_its_runs(pd.DataFrame(rows))
    got = dict(zip(out.dnaSampleID, zip(out["product"], out.sequencerRunID)))
    assert got == {"A": ("DP1.10081.002", "r3"), "B": ("DP1.10081.001", "r1")}


def _core_rows(core, fus, other, qf="OK"):
    return [dict(dnaSampleID=core, kingdom="Fungi", genus="Fusarium", individualCount=fus, sequenceCountQF=qf),
            dict(dnaSampleID=core, kingdom="Fungi", genus="Other", individualCount=other, sequenceCountQF=qf)]


def test_build_its_genus_mean_of_core_shares_and_qc_filter():
    rows = (_core_rows("STER_001-M-1-1-20220601-GEN-DNA1", 10, 90)        # 10 %
            + _core_rows("STER_001-M-2-20220601-GEN-DNA1", 300, 100)      # 75 %, single-depth ID
            + _core_rows("STER_001-M-3-3-20220601-GEN-DNA1", 5, 0, qf="Below threshold"))
    g = neon.build_its_genus(pd.DataFrame(rows))
    f = g[g.genus == "Fusarium"].iloc[0]
    assert f.n_cores == 2 and f.reads == 310 and f.total_reads == 500
    assert f.rel_abund_pct == 42.5          # mean of 10 % and 75 %, not the pooled 62 %
    g_all = neon.build_its_genus(pd.DataFrame(rows), qc_ok_only=False)
    assert g_all[g_all.genus == "Fusarium"].iloc[0].n_cores == 3


def test_pooling_map(tmp_path):
    pd.DataFrame({"genomicsPooledIDList": ["KONA_003-M-10-30-20170807|KONA_003-M-12-2.5-20170807", None],
                  "genomicsSampleID": ["KONA_003-M-20170807-COMP", "X"], "plotID": ["KONA_003", "KONA_004"],
                  "collectDate": ["2017-08-07T14:58Z", "2017-08-07"]}
                 ).to_parquet(tmp_path / "sls_metagenomicsPooling.parquet")
    p = neon.pooling_map(tmp_path)
    assert list(p.soilSampleID) == ["KONA_003-M-10-30-20170807", "KONA_003-M-12-2.5-20170807"]
    assert set(p.genomicsSampleID) == {"KONA_003-M-20170807-COMP"}
