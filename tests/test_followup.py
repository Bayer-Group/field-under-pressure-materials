"""Follow-up test suggestions (followup.py): triggers on synthetic risk results, no network, no real data."""
import pandas as pd
import pytest

from cropfit import followup, risk
from cropfit.kb import SCORED_CROPS
from test_risk import core_rows, mk_kb

P2 = "DP1.10081.002"
HOSTS = {("Fusarium", "winter_wheat"): (400, 60), ("Bipolaris", "winter_wheat"): (30, 9),
         ("Macrophomina", "soybean"): (8, 2), ("Fusarium", "soybean"): (400, 40)}


def result(target_reads, n_cores=3, total=11500):
    """12 units; STER_001 gets `target_reads` ({genus: reads or per-core list}), the others a low background."""
    rows = core_rows("STER", "STER_001", "2022-07-01", P2, target_reads, n_cores=n_cores, total=total)
    for i in range(2, 13):
        rows += core_rows("STER", f"STER_{i:03d}", "2022-07-01", P2,
                          {"Fusarium": 20 + i, "Bipolaris": 15 + i, "Macrophomina": 12 + i}, n_cores=3)
    return risk.compute_crop_risk("STER", 2022, core=pd.DataFrame(rows), kb=mk_kb(host_rows=HOSTS))


def suggest_for(res, crop, **kw):
    return followup.suggest(res.contributions, res.summary, f"STER_001|2022|{P2}", crop, **kw)


def by_id(items):
    return {i["test_id"]: i for i in items}


def test_catalogue_is_valid():
    cat = followup.load_catalogue()
    assert list(cat.columns) == followup.CATALOGUE_COLUMNS
    assert set(cat["kind"]) <= set(followup.KINDS)
    assert {"more_cores", "resequence"} <= set(cat["test_id"])
    for cs in cat["crops"]:
        assert {c for c in cs.split(";") if c} <= set(SCORED_CROPS)
    pathogen = cat[cat["kind"].isin(["species_pcr", "inoculum_count", "blind_spot"])]
    assert not pathogen["verified"].any()          # nobody has checked these rows yet: keep them flagged


def test_catalogue_rejects_unknown_crop(tmp_path):
    f = tmp_path / "c.csv"
    cat = followup.load_catalogue()
    cat.loc[0, "crops"] = "banana"
    cat.assign(verified="no").to_csv(f, index=False)
    with pytest.raises(ValueError, match="banana"):
        followup.load_catalogue(f)


def test_high_reliable_genus_asks_for_species():
    res = result({"Fusarium": 900, "Bipolaris": 16, "Macrophomina": 13})
    t = by_id(suggest_for(res, "winter_wheat"))
    g = t["fus_graminearum"]
    assert g["trigger"] == "resolve_species" and "3 of 3 soil cores" in g["reason"]
    assert "60 of its 400" in g["reason"] and g["verified"] is False
    assert "bipolaris_sorokiniana" not in t          # typical level, reliably detected: nothing to resolve
    assert "fus_virguliforme" not in t               # a soybean test


def test_weak_detection_asks_for_confirmation():
    res = result({"Fusarium": 30, "Bipolaris": [0, 0, 400], "Macrophomina": [3, 3, 3]})
    wheat = by_id(suggest_for(res, "winter_wheat"))
    b = wheat["bipolaris_sorokiniana"]
    assert b["trigger"] == "confirm_detection" and "1 of 3 soil cores" in b["reason"]     # one core, many reads
    soy = by_id(suggest_for(res, "soybean"))
    m = soy["macrophomina"]
    assert m["trigger"] == "confirm_detection" and "with 9 reads" in m["reason"]          # three cores, few reads
    assert m["priority"] < 0.6


def test_not_detected_genus_gives_no_pathogen_test():
    res = result({"Fusarium": 30, "Bipolaris": 16})
    assert "macrophomina" not in by_id(suggest_for(res, "soybean"))


def test_blind_spots_follow_the_crop_and_wet_sites_rank_higher():
    res = result({"Fusarium": 30, "Bipolaris": 16, "Macrophomina": 13})
    dry = by_id(suggest_for(res, "soybean"))
    assert {"phytophthora_sojae", "pythium", "soybean_cyst_nematode", "lesion_nematodes"} <= set(dry)
    assert "aphanomyces" not in dry and dry["pythium"]["trigger"] == "blind_spot"
    wet = by_id(suggest_for(res, "soybean", context={"p_wet_may": 0.7, "drainage_class": "Well drained"}))
    assert wet["pythium"]["priority"] > dry["pythium"]["priority"]
    assert "May is wet in 70% of years" in wet["pythium"]["reason"]
    assert wet["soybean_cyst_nematode"]["priority"] == dry["soybean_cyst_nematode"]["priority"]
    poor = by_id(suggest_for(res, "soybean", context={"p_wet_may": 0.1, "drainage_class": "Poorly drained"}))
    assert "poorly drained" in poor["phytophthora_sojae"]["reason"]


def test_single_core_and_shallow_units():
    one = suggest_for(result({"Fusarium": 900, "Bipolaris": 16}, n_cores=1), "winter_wheat")
    assert one[0]["test_id"] == "more_cores" and one[0]["verified"] is True
    assert by_id(one)["fus_graminearum"]["trigger"] == "resolve_species"     # one core cannot be "1 of several"
    shallow = suggest_for(result({"Fusarium": 900}, n_cores=1, total=1500), "winter_wheat")
    assert [i["test_id"] for i in shallow] == ["resequence"]


def test_sorted_and_unknown_unit():
    res = result({"Fusarium": 900, "Bipolaris": [0, 0, 400], "Macrophomina": 13})
    items = suggest_for(res, "winter_wheat")
    assert [i["priority"] for i in items] == sorted((i["priority"] for i in items), reverse=True)
    assert all(0 <= i["priority"] <= 1 and set(i) == set(followup.SUGGESTION_KEYS) for i in items)
    assert followup.suggest(res.contributions, res.summary, "nope", "winter_wheat") == []
