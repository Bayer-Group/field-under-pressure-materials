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
