"""Tests for cropfit.risk: units, depth rules, abundance percentile, H x A assembly, result schema. Offline, synthetic."""
import json

import numpy as np
import pandas as pd
import pytest

from cropfit import kb as kbmod
from cropfit import neon, risk
from cropfit.kb import KB

SYN = {"Rhizoctonia": "Rhizoctonia_complex", "Thanatephorus": "Rhizoctonia_complex",
       "Ceratobasidium": "Rhizoctonia_complex", "Gibberella": "Fusarium"}
CROPS = ("winter_wheat", "corn", "millet")


# ---------------------------------------------------------------------------------------------- builders

def core_rows(site, plot, date, product, genus_reads, n_cores=1, total=11500, horizon="M", qf="OK"):
    """Core-level rows like its_core_genus. genus_reads: {genus: int or per-core list}. A filler 'unclassified' row
    keeps every core present (and exercises the placeholder drop)."""
    rows = []
    for i in range(n_cores):
        sid = f"{plot}-{horizon}-{i}-{date.replace('-', '')}-{product}-{qf[:2]}"
        for g, r in {**genus_reads, "unclassified_Fungi": 1}.items():
            r = r[i] if isinstance(r, (list, tuple)) else r
            if r > 0:
                rows.append(dict(site=site, plotID=plot, collectDate=date, dnaSampleID=sid, genus=g, reads=r,
                                 total_reads=total, horizon=horizon, sequenceCountQF=qf, product=product))
    return rows


def mk_kb(extra_genera=(), host_rows=None):
    g = [("Fusarium", "Fusarium", "Ascomycota", True, "primary_lifestyle", None),
         ("Bipolaris", "Bipolaris", "Ascomycota", True, "secondary_lifestyle", None),
         ("Macrophomina", "Macrophomina", "Ascomycota", True, "primary_lifestyle", None),
         ("Rhizoctonia", "Rhizoctonia_complex", "Basidiomycota", True, "primary_lifestyle", None),
         ("Thanatephorus", "Rhizoctonia_complex", "Basidiomycota", True, "primary_lifestyle", None),
         ("Colletotrichum", "Colletotrichum", "Ascomycota", True, "primary_lifestyle", None),   # no USDA hosts
         ("Pythium", "Pythium", "Ascomycota", True, "primary_lifestyle", None),   # a DB wrongly admitting it
         ("Trichoderma", "Trichoderma", "Ascomycota", False, None, "not_plant_pathogen"),
         ("Labyrinthula", "Labyrinthula", "Labyrinthulidia", False, None, "non_fungal"),
         *extra_genera]
    genera = pd.DataFrame([{"genus_raw": a, "genus": a, "canonical_genus": b, "phylum": ph,
                            "primary_lifestyle": "plant_pathogen" if p else "soil_saprotroph",
                            "secondary_lifestyle": None, "plant_pathogenic_capacity": None, "passes_filter": ok,
                            "passed_by": by, "exclusion_reason": ex, "duplicate_rows": 1}
                           for a, b, ph, ok, by, ex in g for p in [ok]], columns=kbmod.GENERA_COLUMNS)
    hr = host_rows if host_rows is not None else {
        ("Fusarium", "winter_wheat"): (400, 60), ("Bipolaris", "winter_wheat"): (30, 9),
        ("Macrophomina", "corn"): (10, 5), ("Rhizoctonia_complex", "corn"): (20, 10),
        ("Pythium", "corn"): (50, 25)}
    docs = {}
    for (gen, _), (nd, _) in hr.items():
        docs[gen] = nd
    rows = []
    for gen, nd in docs.items():
        for crop in kbmod.SCORED_CROPS:
            n = hr.get((gen, crop), (nd, 0))[1]
            rows.append({"genus": gen, "crop_group": crop, "n_species_documented": nd, "n_species_on_crop": n,
                         "h": n / nd, "species_on_crop": "; ".join(f"{gen} sp{i}" for i in range(n)),
                         "n_records_on_crop": n * 2, "n_genus_only_records_on_crop": 0, "source_version": "test"})
    host = pd.DataFrame(rows, columns=kbmod.HOST_COLUMNS)
    meta = {"sources": {"fungaltraits": {"url": "u1", "sha256": "s1"}, "usda_fungus_host": {"url": "u2"}}}
    return KB(genera=genera, host=host, synonyms=dict(SYN), meta=meta)


def worked_core(target_extra=None, others_extra=None):
    """Plan worked example: STER_026 2022 .002 (3 cores, 34,500 reads) plus 19 STER .002 units in 2018-2021.
    Fusarium: 13 reference units below the target, 6 above. Bipolaris: target 0, 7 other zeros, 12 detected."""
    rows = []
    tgt = {"Fusarium": [345, 575, 520], "Bipolaris": 0, **(target_extra or {})}
    rows += core_rows("STER", "STER_026", "2022-07-12", ".002", tgt, n_cores=3)
    fus = [30 + 20 * i for i in range(13)] + [600 + 50 * i for i in range(6)]
    for i, f in enumerate(fus):
        bip = 6 if i < 12 else 0
        rows += core_rows("STER", f"STER_{i + 1:03d}", f"{2018 + i % 4}-07-01", ".002",
                          {"Fusarium": f, "Bipolaris": bip, **(others_extra or {})})
    return pd.DataFrame(rows)


def run(core, kb=None, **kw):
    kw.setdefault("crops", CROPS)
    return risk.compute_crop_risk("STER", 2022, core=core, kb=kb or mk_kb(), **kw)


def srow(res, crop="winter_wheat", **sel):
    s = res.summary[res.summary["crop"] == crop]
    for k, v in sel.items():
        s = s[s[k] == v]
    assert len(s) == 1
    return s.iloc[0]


# ---------------------------------------------------------------------------------------------- units

def test_units_split_by_product_and_year():
    rows = (core_rows("STER", "STER_001", "2016-07-01", ".001", {"Fusarium": 100})
            + core_rows("STER", "STER_001", "2016-09-01", ".002", {"Fusarium": 50})
            + core_rows("STER", "STER_001", "2017-07-01", ".001", {"Fusarium": 10}))
    units, shares = risk.build_units(pd.DataFrame(rows), SYN)
    assert set(units["unit_id"]) == {"STER_001|2016|.001", "STER_001|2016|.002", "STER_001|2017|.001"}
    assert len(units) == 3
    assert set(shares["unit_id"]) == set(units["unit_id"])


def test_unit_share_is_zero_filled_mean_of_core_shares():
    rows = core_rows("STER", "STER_001", "2022-07-01", ".002", {"Fusarium": [200, 0]}, n_cores=2, total=10000)
    units, shares = risk.build_units(pd.DataFrame(rows), SYN)
    u = units.iloc[0]
    assert u["total_reads"] == 20000 and u["n_cores"] == 2
    f = shares[shares["genus"] == "Fusarium"].iloc[0]
    assert f["reads"] == 200 and f["n_cores_detected"] == 1
    assert f["share_pct"] == pytest.approx((2.0 + 0.0) / 2)       # NOT 200/20000 pooled reads weighting
    # unequal depth: mean of core shares, not pooled
    rows = (core_rows("STER", "STER_002", "2022-07-01", ".002", {"Fusarium": [100, 100]}, n_cores=2, total=10000))
    for r in rows[2:]:
        r["total_reads"] = 1000                                    # second core shallower
    units, shares = risk.build_units(pd.DataFrame(rows), SYN)
    assert shares.iloc[0]["share_pct"] == pytest.approx((1.0 + 10.0) / 2)


def test_units_keep_only_horizon_m_and_qc_passing_cores():
    rows = (core_rows("STER", "STER_001", "2022-07-01", ".002", {"Fusarium": 100})
            + core_rows("STER", "STER_001", "2022-07-01", ".002", {"Fusarium": 900}, horizon="O")
            + core_rows("STER", "STER_001", "2022-07-01", ".002", {"Fusarium": 900}, qf="Below threshold"))
    units, shares = risk.build_units(pd.DataFrame(rows), SYN)
    assert units.iloc[0]["n_cores"] == 1 and units.iloc[0]["total_reads"] == 11500
    assert shares[shares["genus"] == "Fusarium"].iloc[0]["reads"] == 100


def test_units_merge_synonyms_summing_per_core():
    rows = core_rows("STER", "STER_001", "2022-07-01", ".002",
                     {"Rhizoctonia": [100, 0], "Thanatephorus": [50, 60], "Gibberella": 5, "Fusarium": 5},
                     n_cores=2, total=10000)
    _, shares = risk.build_units(pd.DataFrame(rows), SYN)
    sh = shares.set_index("genus")
    assert set(sh.index) == {"Rhizoctonia_complex", "Fusarium"}    # placeholders dropped
    rc = sh.loc["Rhizoctonia_complex"]
    assert rc["reads"] == 210 and rc["n_cores_detected"] == 2
    assert rc["share_pct"] == pytest.approx((1.5 + 0.6) / 2)       # summed within core, then mean over cores
    assert sh.loc["Fusarium", "reads"] == 20                       # Gibberella 2 x 5 + Fusarium 2 x 5


# ---------------------------------------------------------------------------------------------- depth

def depth_setup(units_spec):
    """units_spec: list of (plot, total_reads, {genus: reads}); one core each, STER .002 2022."""
    rows = []
    for plot, total, gr in units_spec:
        rows += core_rows("STER", plot, "2022-07-01", ".002", gr, total=total)
    units, shares = risk.build_units(pd.DataFrame(rows), SYN)
    return units, shares


def status_of(units, shares, genera=("Bipolaris",), floor=2000, min_exp=3.0):
    allowed = set(genera)
    s_typ = risk.typical_share(shares, units, floor)
    scored = risk.scored_genera(shares, units, allowed, floor)
    st = risk.depth_status(shares, units, s_typ, scored, floor, min_exp)
    return st.set_index(["unit_id", "genus"])


def test_depth_unit_floor_and_genus_rule_only_skips_non_detections():
    spec = [(f"STER_{i:03d}", 34500, {"Bipolaris": 17}) for i in range(1, 5)]       # share 0.0493%
    spec += [("STER_010", 34500, {}),                    # deep, zero reads: expected 17 >= 3 -> not_detected
             ("STER_011", 2500, {}),                     # above floor but shallow: expected 1.23 < 3
             ("STER_012", 2500, {"Bipolaris": 1}),       # shallow but detected -> never depth-skipped
             ("STER_013", 1500, {})]                     # below the 2000 floor
    units, shares = depth_setup(spec)
    st = status_of(units, shares)
    stat = lambda p: st.loc[(f"{p}|2022|.002", "Bipolaris"), "status"]
    assert stat("STER_001") == "detected"
    assert stat("STER_010") == "not_detected"
    assert stat("STER_011") == "insufficient_depth"
    assert stat("STER_012") == "detected"
    assert stat("STER_013") == "insufficient_depth_unit"
    # s_typ = median non-zero share among floor-passing units; floor-failing units are not used
    s_typ = st.loc[("STER_010|2022|.002", "Bipolaris"), "s_typ_pct"]
    assert s_typ == pytest.approx(100 * 17 / 34500)        # median of 4 x 0.0493% and the shallow unit's 0.04%
    assert st.loc[("STER_011|2022|.002", "Bipolaris"), "expected_reads"] == pytest.approx(2500 * s_typ / 100)
    assert st.loc[("STER_011|2022|.002", "Bipolaris"), "expected_reads"] < 3 <= st.loc[
        ("STER_010|2022|.002", "Bipolaris"), "expected_reads"]


def test_depth_s_typ_undefined_turns_rule_off():
    # genus detected in only 2 floor-passing units -> s_typ undefined -> shallow zero stays not_detected
    spec = [("STER_001", 34500, {"Bipolaris": 17}), ("STER_002", 34500, {"Bipolaris": 17}),
            ("STER_003", 2100, {}), ("STER_004", 34500, {})]
    units, shares = depth_setup(spec)
    st = status_of(units, shares)
    assert st["s_typ_pct"].isna().all() and st["expected_reads"].isna().all()
    assert st.loc[("STER_003|2022|.002", "Bipolaris"), "status"] == "not_detected"
    ts = risk.typical_share(shares, units, 2000)
    assert ts.iloc[0]["n_units_detected"] == 2 and np.isnan(ts.iloc[0]["s_typ_pct"])


def test_typical_share_median_of_nonzero_among_floor_units():
    spec = [("STER_001", 10000, {"Bipolaris": 10}), ("STER_002", 10000, {"Bipolaris": 20}),
            ("STER_003", 10000, {"Bipolaris": 40}), ("STER_004", 10000, {"Bipolaris": 1000}),
            ("STER_005", 1000, {"Bipolaris": 900})]                     # below floor: ignored
    units, shares = depth_setup(spec)
    ts = risk.typical_share(shares, units, 2000).iloc[0]
    assert ts["n_units_detected"] == 4 and ts["s_typ_pct"] == pytest.approx(0.3)   # median(0.1, 0.2, 0.4, 10)


# ---------------------------------------------------------------------------------------------- worked example

def test_worked_example_exact_numbers():
    res = run(worked_core(), crops=("winter_wheat",))
    c = res.contributions
    assert set(c["unit_id"]) == {"STER_026|2022|.002"}
    f, b = (c[c["genus"] == g].iloc[0] for g in ("Fusarium", "Bipolaris"))
    # Fusarium: 13 lower, 1 tie (itself), n = 20
    assert f["detection_status"] == "detected" and f["reads"] == 1440 and f["total_reads"] == 34500
    assert f["share_pct"] == pytest.approx(100 * (345 / 11500 + 575 / 11500 + 520 / 11500) / 3)
    assert f["reference_n"] == 20 and f["percentile"] == pytest.approx(67.5) and f["a"] == pytest.approx(0.675)
    assert f["n_species_documented"] == 400 and f["n_species_on_crop"] == 60
    assert f["h"] == pytest.approx(0.15) and f["contribution"] == pytest.approx(0.10125)
    # Bipolaris: not detected, 8 zeros incl. itself, mid-rank 100*(0.5*8)/20
    assert b["detection_status"] == "not_detected" and b["reads"] == 0
    assert b["percentile"] == pytest.approx(20.0) and b["a"] == pytest.approx(0.2)
    assert b["expected_reads"] == pytest.approx(34500 * 6 / 11500 / 100 * 100, rel=1e-6) and b["expected_reads"] >= 3
    assert b["h"] == pytest.approx(0.3) and b["contribution"] == pytest.approx(0.06)
    assert set(c["detection_status"]) <= {"detected", "not_detected"}
    s = srow(res)
    assert s["risk_index"] == pytest.approx(0.16125)
    assert s["risk_from_detected"] == pytest.approx(0.10125) and s["risk_from_not_detected"] == pytest.approx(0.06)
    assert s["h_sum_scored"] == pytest.approx(0.45) and s["status"] == "ok"
    assert s["n_genera_scored"] == 2 and s["n_genera_contributing"] == 2 and s["n_genera_not_detected"] == 1
    assert s["top_genus"] == "Fusarium" and s["top_contribution"] == pytest.approx(0.10125)
    assert s["reference_n_min"] == s["reference_n_max"] == 20 and not s["small_reference"]
    assert s["total_reads"] == 34500 and s["n_cores"] == 3 and s["collect_dates"] == "2022-07-12"


def test_percentiles_match_neon_percentile_rank():
    core = worked_core()
    res = run(core)
    units, shares = risk.build_units(core, SYN)
    sh = shares.merge(units[["unit_id", "plotID", "year", "product"]], on="unit_id")
    for genus in ("Fusarium", "Bipolaris"):
        full = units[units["product"] == ".002"][["unit_id"]].merge(sh[sh["genus"] == genus], on="unit_id", how="left")
        full["share_pct"] = full["share_pct"].fillna(0.0)
        tgt = full[full["unit_id"] == "STER_026|2022|.002"]["share_pct"]
        want = float(neon.percentile_rank(tgt, full["share_pct"]).iloc[0])
        got = res.contributions.query("genus == @genus")["percentile"].iloc[0]
        assert got == pytest.approx(want)


def test_total_equals_sum_of_contributions_and_split_adds_up():
    res = run(worked_core(), crops=("winter_wheat", "corn", "millet"))
    c, s = res.contributions, res.summary
    assert (c["contribution"] == c["a"] * c["h"]).all()
    for (uid, crop), g in c.groupby(["unit_id", "crop"]):
        row = s[(s["unit_id"] == uid) & (s["crop"] == crop)].iloc[0]
        if row["status"] == "ok":
            assert row["risk_index"] == pytest.approx(g["contribution"].sum())
            det = g.loc[g["detection_status"] == "detected", "contribution"].sum()
            nd = g.loc[g["detection_status"] == "not_detected", "contribution"].sum()
            assert row["risk_from_detected"] + row["risk_from_not_detected"] == pytest.approx(row["risk_index"])
            assert row["risk_from_detected"] == pytest.approx(det)
            assert row["risk_from_not_detected"] == pytest.approx(nd)
    assert (c["h"] == 0).any()                                       # H = 0 rows are kept for the explanation


def test_reference_is_same_site_and_product_only():
    base = run(worked_core())
    extra = pd.DataFrame(
        sum([core_rows("STER", f"STER_{i + 40:03d}", "2019-07-01", ".001", {"Fusarium": 9000, "Bipolaris": 50})
             for i in range(15)], [])
        + sum([core_rows("KONA", f"KONA_{i + 1:03d}", "2022-07-01", ".002", {"Fusarium": 9000}) for i in range(15)], []))
    res = run(pd.concat([worked_core(), extra], ignore_index=True))
    f0 = base.contributions.query("genus == 'Fusarium'").iloc[0]
    f1 = res.contributions.query("genus == 'Fusarium'").iloc[0]
    assert f1["reference_n"] == f0["reference_n"] == 20
    assert f1["percentile"] == pytest.approx(f0["percentile"])
    assert f1["reference_years"] == "2018; 2019; 2020; 2021; 2022"   # all years of the same product
    assert "STER" in f1["reference_definition"] and ".002" in f1["reference_definition"]
    pd.testing.assert_series_equal(srow(res)[["risk_index"]], srow(base)[["risk_index"]])


def test_small_reference_flag_and_hard_minimum():
    def core_n(n_units):
        rows = core_rows("STER", "STER_026", "2022-07-12", ".002", {"Fusarium": 500})
        for i in range(n_units - 1):
            rows += core_rows("STER", f"STER_{i + 1:03d}", f"{2018 + i % 4}-07-01", ".002",
                              {"Fusarium": 100 + 50 * i})
        return pd.DataFrame(rows)
    ok = run(core_n(10))
    assert not ok.contributions["small_reference"].any() and ok.contributions["reference_n"].iloc[0] == 10
    small = run(core_n(7))                              # 5 <= n < 10: computed, flagged
    f = small.contributions.query("genus == 'Fusarium'").iloc[0]
    assert f["small_reference"] and f["reference_n"] == 7 and np.isfinite(f["a"])
    assert srow(small)["small_reference"]
    tiny = run(core_n(4))                               # n < 5: A is NaN -> not summed, listed as skipped
    assert tiny.contributions.empty
    sk = tiny.skipped.query("reason == 'reference_too_small'")
    assert list(sk["genus"]) == ["Fusarium"] and "reference_n 4" in sk.iloc[0]["detail"]
    assert srow(tiny)["status"] == "no_scored_genera" and np.isnan(srow(tiny)["risk_index"])


def test_not_detected_in_reference_is_skipped_not_summed():
    res = run(worked_core())
    assert "Macrophomina" not in set(res.contributions["genus"])         # zero reads in every reference unit
    sk = res.skipped.query("genus == 'Macrophomina'")
    assert list(sk["reason"]) == ["not_detected_in_reference"] and sk.iloc[0]["reads"] == 0
    assert "Rhizoctonia_complex" in set(res.skipped.query("reason == 'not_detected_in_reference'")["genus"])


def test_insufficient_depth_genus_skipped_in_shallow_unit():
    """Plan contrast: same Bipolaris, 2,500-read unit -> expected 1.25 reads -> insufficient_depth, not scored."""
    rows = core_rows("STER", "STER_026", "2022-07-12", ".002", {"Fusarium": 100}, total=2500)
    for i in range(14):
        rows += core_rows("STER", f"STER_{i + 1:03d}", f"{2018 + i % 4}-07-01", ".002",
                          {"Fusarium": 100 + 10 * i, "Bipolaris": 6 if i < 7 else 0}, total=11500)
    res = run(pd.DataFrame(rows))
    assert "Bipolaris" not in set(res.contributions["genus"])
    sk = res.skipped.query("genus == 'Bipolaris' and unit_id == 'STER_026|2022|.002'").iloc[0]
    assert sk["reason"] == "insufficient_depth" and sk["expected_reads"] < 3 and sk["reads"] == 0
    assert srow(res)["n_genera_skipped_depth"] == 1 and srow(res)["status"] == "ok"
    # The shallow unit (above the floor) is not part of Bipolaris's reference, but Fusarium (detected) still is.
    assert res.contributions.query("genus == 'Fusarium'")["reference_n"].iloc[0] == 15


def test_unit_below_floor_is_nan_and_excluded_from_references():
    core = worked_core()
    low = pd.DataFrame(core_rows("STER", "STER_030", "2022-07-12", ".002", {"Fusarium": 50}, total=1500))
    res = run(pd.concat([core, low], ignore_index=True))
    s = res.summary[res.summary["unit_id"] == "STER_030|2022|.002"]
    assert len(s) == len(CROPS) and (s["status"] == "insufficient_depth").all()
    assert s["risk_index"].isna().all() and s["risk_from_detected"].isna().all()
    assert (res.skipped.query("unit_id == 'STER_030|2022|.002'")["reason"] == "insufficient_depth_unit").all()
    assert "STER_030|2022|.002" not in set(res.contributions["unit_id"])
    assert res.contributions["reference_n"].eq(20).all()                 # the shallow unit is not in any reference
    assert srow(res, unit_id="STER_026|2022|.002")["status"] == "ok"


# ---------------------------------------------------------------------------------------------- assembly

def test_rhizoctonia_complex_summed_per_core_in_contributions():
    rows = []
    for i in range(10):
        rows += core_rows("STER", f"STER_{i + 1:03d}", f"{2018 + i % 4}-07-01", ".002",
                          {"Rhizoctonia": 10 * i, "Thanatephorus": 5 * i})
    rows += core_rows("STER", "STER_026", "2022-07-12", ".002", {"Rhizoctonia": 100, "Thanatephorus": 50})
    res = run(pd.DataFrame(rows), crops=("corn",))
    c = res.contributions
    assert set(c["genus"]) == {"Rhizoctonia_complex"}
    r = c[c["unit_id"] == "STER_026|2022|.002"].iloc[0]
    assert r["reads"] == 150 and r["genus_members"] == "Rhizoctonia; Thanatephorus"
    assert r["share_pct"] == pytest.approx(100 * 150 / 11500)
    assert r["h"] == pytest.approx(0.5) and r["reference_n"] == 11
    assert r["percentile"] == pytest.approx(100 * (10 + 0.5) / 11)       # above 0..135 of the others except 135? 150>135
    assert r["contribution"] == pytest.approx(r["a"] * 0.5)


def test_oomycete_excluded_from_contributions_and_listed_as_skipped():
    core = worked_core(target_extra={"Pythium": 300}, others_extra={"Pythium": 200})
    res = run(core, crops=("corn",))
    assert "Pythium" not in set(res.contributions["genus"])
    sk = res.skipped.query("genus == 'Pythium'")
    assert list(sk["reason"]) == ["oomycete"]
    assert "oomycete" in " ".join(res.metadata["caveats"]).lower()


def test_detected_genera_not_scored_are_listed_with_reasons():
    extra = {"Trichoderma": 20, "Labyrinthula": 5, "Colletotrichum": 8, "Mystery": 9}
    res = run(worked_core(target_extra=extra), crops=("corn",))
    sk = res.skipped.query("unit_id == 'STER_026|2022|.002'").set_index("genus")["reason"].to_dict()
    assert sk["Trichoderma"] == "excluded_by_filter"
    assert sk["Labyrinthula"] == "non_fungal"
    assert sk["Colletotrichum"] == "no_usda_host_records"
    assert sk["Mystery"] == "not_in_fungaltraits"
    assert not {"Trichoderma", "Labyrinthula", "Colletotrichum", "Mystery"} & set(res.contributions["genus"])


def test_crop_without_host_records_is_no_knowledge_and_nan_not_zero():
    res = run(worked_core(), crops=("winter_wheat", "millet"))
    m = srow(res, crop="millet")
    assert m["status"] == "no_knowledge" and np.isnan(m["risk_index"])
    assert np.isnan(m["risk_from_detected"]) and np.isnan(m["risk_from_not_detected"])
    assert m["h_sum_scored"] == 0 and m["n_genera_scored"] == 2           # genera were scored, none known on millet
    assert pd.isna(m["top_genus"])
    assert srow(res, crop="winter_wheat")["status"] == "ok"


def test_summary_has_one_row_per_unit_and_crop():
    res = run(worked_core())
    assert list(res.summary.columns) == risk.SUMMARY_COLUMNS
    assert list(res.contributions.columns) == risk.CONTRIBUTION_COLUMNS
    assert list(res.skipped.columns) == risk.SKIPPED_COLUMNS
    assert len(res.summary) == len(CROPS) and set(res.summary["crop"]) == set(CROPS)
    assert not res.empty and res.metadata["reason"] is None
    assert res.metadata["n_units"] == 1 and res.metadata["products"] == [".002"]


# ---------------------------------------------------------------------------------------------- errors / empty

def test_no_data_for_site_year_gives_empty_result_with_reason():
    res = risk.compute_crop_risk("STER", 2025, core=worked_core(), kb=mk_kb(), crops=CROPS)
    assert res.empty
    assert list(res.summary.columns) == risk.SUMMARY_COLUMNS
    assert list(res.contributions.columns) == risk.CONTRIBUTION_COLUMNS
    assert list(res.skipped.columns) == risk.SKIPPED_COLUMNS
    assert res.metadata["reason"].startswith("no ITS units for STER 2025")
    assert "STER 2022" in res.metadata["reason"]
    d = res.to_dict()
    json.dumps(d, allow_nan=False)
    assert d["summary"] == [] and d["metadata"]["reason"] == res.metadata["reason"]
    other = risk.compute_crop_risk("NOPE", 2022, core=worked_core(), kb=mk_kb())
    assert other.empty and "NOPE 2022" in other.metadata["reason"]


def test_missing_product_column_raises_with_02b_hint():
    core = worked_core().drop(columns=["product"])
    with pytest.raises(KeyError, match="02b"):
        run(core)


def test_load_core_genus_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match="02b"):
        risk.load_core_genus(tmp_path / "its_core_genus.parquet")
    p = tmp_path / "stale.parquet"
    worked_core().drop(columns=["product"]).to_parquet(p)
    with pytest.raises(KeyError, match="02b"):
        risk.load_core_genus(p)
    p2 = tmp_path / "ok.parquet"
    worked_core().to_parquet(p2)
    assert "product" in risk.load_core_genus(p2).columns


def test_missing_kb_files_raise_naming_script_12(tmp_path, monkeypatch):
    orig = kbmod.load_kb
    monkeypatch.setattr(kbmod, "load_kb", lambda: orig(tmp_path))
    with pytest.raises(FileNotFoundError, match="12_build_kb"):
        risk.compute_crop_risk("STER", 2022, core=worked_core())


# ---------------------------------------------------------------------------------------------- to_dict

def test_to_dict_is_strict_json_with_stable_schema():
    core = worked_core(target_extra={"Trichoderma": 20})
    core["collectDate"] = pd.to_datetime(core["collectDate"])           # Timestamps must be serialised too
    res = run(core, crops=CROPS)
    assert res.summary["risk_index"].isna().any() and res.skipped["expected_reads"].isna().any()   # NaNs present
    d = res.to_dict()
    text = json.dumps(d, allow_nan=False)
    back = json.loads(text)
    assert back == d
    assert d["schema_version"] == "crop_risk/1" == risk.SCHEMA_VERSION
    assert d["site"] == "STER" and d["year"] == 2022
    assert d["columns"] == {"summary": risk.SUMMARY_COLUMNS, "contributions": risk.CONTRIBUTION_COLUMNS,
                            "skipped": risk.SKIPPED_COLUMNS}
    for key, cols in d["columns"].items():
        assert all(list(r.keys()) == cols for r in d[key])
    assert len(d["summary"]) == len(res.summary) and len(d["contributions"]) == len(res.contributions)
    m = res.summary.query("crop == 'millet'").index[0]
    assert d["summary"][m]["risk_index"] is None                         # NaN -> null, never 0
    assert type(d["summary"][0]["year"]) is int and type(d["summary"][0]["small_reference"]) is bool


def test_metadata_content_and_caveats():
    md = run(worked_core()).to_dict()["metadata"]
    assert md["formula"] == "risk = sum_g A(p,g) * H(g,c)"
    assert md["parameters"] == {"min_unit_reads": 2000, "min_expected_reads": 3.0, "min_reference": 10,
                                "hard_min_reference": 5}
    assert md["crops_scored"] == list(CROPS)
    assert md["same_host_taxa_as"] == {}                     # no two test crops share identical host evidence
    assert "double_wheat_soy" in md["crops_excluded"]
    meta = mk_kb().meta                                      # kb_meta.json, sources flattened to the top level
    assert md["kb"] == {**meta["sources"], **{k: v for k, v in meta.items() if k != "sources"}}
    assert md["kb"]["fungaltraits"]["sha256"] == "s1"
    assert md["index_type"].endswith("not a probability of disease")
    text = " ".join(md["caveats"])
    for phrase in ("not a probability", "oomycete", ".001", "bacteria"):
        assert phrase in text
    assert md["generated_utc"] and md["reason"] is None


def test_metadata_kb_has_sources_at_top_level_per_plan():
    md = run(worked_core()).metadata
    assert md["kb"]["fungaltraits"]["sha256"] == "s1"


def test_custom_parameters_are_recorded_and_applied():
    res = run(worked_core(), min_unit_reads=30000, min_reference=3, hard_min_reference=1)   # 11,500-read refs fail
    assert res.metadata["parameters"] == {"min_unit_reads": 30000, "min_expected_reads": 3.0, "min_reference": 3,
                                          "hard_min_reference": 1}
    assert srow(res)["status"] == "ok" and res.contributions["reference_n"].eq(1).all()   # target alone passes


@pytest.mark.parametrize("kw,core", [
    ({"min_unit_reads": 40000}, None),                                         # every unit below the floor
    ({}, pd.DataFrame(core_rows("STER", "STER_026", "2022-07-12", ".002", {"Mortierella": 100}))),  # no pathogen
])
def test_no_scored_genera_anywhere_does_not_crash(kw, core):
    res = run(worked_core() if core is None else core, **kw)
    assert res.contributions.empty and (res.summary["status"] != "ok").all()
    assert res.summary["risk_index"].isna().all()


# ---------------------------------------------------------------------------------------------- review fixes

def test_same_host_taxa_is_derived_from_the_kb():
    host = mk_kb().host
    assert risk.same_host_taxa(host, ("winter_wheat", "spring_wheat", "corn")) == {}   # spring_wheat has no records
    twin = host[host["crop_group"] == "winter_wheat"].assign(crop_group="spring_wheat")
    host2 = pd.concat([host[host["crop_group"] != "spring_wheat"], twin], ignore_index=True)
    assert risk.same_host_taxa(host2, ("winter_wheat", "spring_wheat", "corn")) == {"spring_wheat": "winter_wheat"}


def test_all_cores_failing_qc_gives_a_specific_reason():
    core = pd.DataFrame(core_rows("STER", "STER_026", "2022-07-12", ".002", {"Fusarium": 100}, qf="Below threshold"))
    res = run(core)
    assert res.empty and "none passed NEON QC" in res.metadata["reason"]


def test_counts_are_integers_and_year_is_coerced():
    res = risk.compute_crop_risk("ster", "2022", core=worked_core(), kb=mk_kb(), crops=CROPS)
    assert not res.empty and res.year == 2022
    assert str(res.contributions["reads"].dtype) == "Int64" and str(res.summary["reference_n_min"].dtype) == "Int64"
    rec = res.to_dict()["contributions"][0]
    assert isinstance(rec["reads"], int) and isinstance(rec["reference_n"], int)
