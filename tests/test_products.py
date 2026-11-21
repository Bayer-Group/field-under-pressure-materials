"""Product recommendations (products.py): triggers on synthetic risk results and signals, no network, no real data."""
import pytest

from cropfit import api  # noqa: F401  (must be imported before api_functions: circular import)
from cropfit import api_functions, followup, products
from cropfit.kb import SCORED_CROPS
from test_followup import P2, result

UNIT = f"STER_001|2022|{P2}"
TYPICAL = {"Fusarium": 30, "Bipolaris": 16, "Macrophomina": 13}


def recommend_for(res, crop, **kw):
    return products.recommend(res.contributions, res.summary, UNIT, crop, **kw)


def by_id(items):
    return {i["product_id"]: i for i in items}


def test_catalogue_is_valid():
    cat = products.load_catalogue()
    assert list(cat.columns) == products.CATALOGUE_COLUMNS
    assert set(cat["kind"]) <= set(products.KINDS) and set(cat["timing"]) <= set(products.TIMINGS)
    assert set(cat["category"]) <= set(products.CATEGORIES)
    for cs in cat["crops"]:
        assert {c for c in cs.split(";") if c} <= set(SCORED_CROPS)
    assert set(cat.loc[cat["kind"] == "soil", "signal"]) == set(products.SIGNAL_RULES)     # no rule without a row
    assert not cat["verified"].any()               # nobody has checked these rows yet: keep them flagged
    assert (cat["product_class"] != "").all() and (cat["source"] != "").all()
    known = set(followup.load_catalogue()["test_id"])
    assert {t for ts in cat["tests"] for t in ts.split(";") if t} <= known


@pytest.mark.parametrize("column,value,match", [("crops", "banana", "banana"), ("signal", "moon_phase", "moon_phase"),
                                                ("timing", "at_harvest", "at_harvest"), ("tests", "nope", "nope")])
def test_catalogue_rejects_bad_rows(tmp_path, column, value, match):
    f = tmp_path / "c.csv"
    cat = products.load_catalogue()
    cat.loc[cat["kind"] == "soil", column] = value
    cat.assign(verified="no").to_csv(f, index=False)
    with pytest.raises(ValueError, match=match):
        products.load_catalogue(f)


def test_thresholds_match_the_soil_function_cards():
    assert (products.NITRATE_ENOUGH, products.NITRATE_LOW) == (api_functions.NITRATE_ENOUGH, api_functions.NITRATE_LOW)
    assert products.CN_IMMOBILISE == api_functions.CN_IMMOBILISE
    assert products.PH_STRONGLY_ACIDIC == api_functions.PH_BANDS[0][0]
    assert products.PH_ALKALINE == api_functions.PH_BANDS[3][0]
    assert products.OC_LOW == api_functions.OC_BANDS[0][0]


def test_high_reliable_genus_gives_products_with_a_confirming_test():
    res = result({"Fusarium": 900, "Bipolaris": 16, "Macrophomina": 13})
    wheat = by_id(recommend_for(res, "winter_wheat"))
    seed, foliar = wheat["fus_seed"], wheat["fus_head_blight"]
    assert seed["trigger"] == "pathogen_high" and seed["timing"] == "before_planting"
    assert foliar["timing"] == "during_growth" and "3 of 3 soil cores" in foliar["reason"]
    assert set(seed["confirm_with"]) == {"fus_graminearum", "fus_crown_rot"}       # the wheat Fusarium tests
    assert seed["basis"] == "fungi" and seed["confidence"] == "low" and seed["verified"] is False
    assert "bipolaris_seed" not in wheat           # typical level: nothing to treat
    assert "fus_sds_seed" not in wheat             # a soybean product
    soy = by_id(recommend_for(res, "soybean"))
    assert soy["fus_sds_seed"]["confirm_with"] == ["fus_virguliforme", "fus_root_rot"]


def test_weak_detection_says_test_first():
    res = result({"Fusarium": 30, "Bipolaris": [0, 0, 400], "Macrophomina": [3, 3, 3]})
    b = by_id(recommend_for(res, "winter_wheat"))["bipolaris_seed"]
    assert b["trigger"] == "confirm_first" and "1 of 3 soil cores" in b["reason"]
    assert b["confirm_with"] == ["bipolaris_sorokiniana"] and b["priority"] <= products.CONFIRM_BASE
    m = by_id(recommend_for(res, "soybean"))["macrophomina_none"]
    assert m["trigger"] == "confirm_first" and m["category"] == "no_product"


def test_context_raises_a_favoured_disease():
    res = result({"Fusarium": 30, "Bipolaris": 16, "Macrophomina": 900})
    plain = by_id(recommend_for(res, "soybean"))["macrophomina_none"]
    hot = by_id(recommend_for(res, "soybean", context={"p_hot_dry_jul_aug": 0.4}))["macrophomina_none"]
    assert plain["trigger"] == "pathogen_high" and hot["priority"] > plain["priority"]
    assert "hot and dry in 40% of years" in hot["reason"]


def test_unmeasured_organisms_need_a_site_that_favours_them():
    res = result(TYPICAL)
    assert not [i for i in recommend_for(res, "soybean") if i["trigger"] == "site_favoured"]
    wet = by_id(recommend_for(res, "soybean", context={"p_wet_may": 0.7, "drainage_class": "Well drained"}))
    assert {"pythium_seed", "phytophthora_seed"} <= set(wet) and "alfalfa_oomycete_seed" not in wet
    p = wet["pythium_seed"]
    assert p["trigger"] == "site_favoured" and p["confirm_with"] == ["pythium"] and p["basis"] == "site"
    assert "May is wet in 70% of years" in p["reason"]


def test_soil_signals():
    res = result(TYPICAL)
    corn = by_id(recommend_for(res, "corn", signals={"nitrate_n_mgkg": 6.0, "cn_ratio": 24.0, "ph": 7.9,
                                                    "organic_c_pct": 0.8, "urease": "found", "n2o_flag": True}))
    assert {"n_sidedress", "starter_n", "p_band", "zinc", "organic_amendment", "urease_inhibitor",
            "nitrification_inhibitor"} <= set(corn)
    assert "lime" not in corn and "iron_chelate" not in corn
    n = corn["n_sidedress"]
    assert n["trigger"] == "soil_signal" and n["timing"] == "during_growth" and "well below" in n["reason"]
    assert n["basis"] == "measured" and n["confidence"] == "medium" and n["confirm_with"] == []
    assert corn["urease_inhibitor"]["basis"] == "genes" and corn["urease_inhibitor"]["confidence"] == "low"
    fine = by_id(recommend_for(res, "corn", signals={"nitrate_n_mgkg": 30.0, "cn_ratio": 11.0, "ph": 6.5,
                                                    "organic_c_pct": 2.5, "urease": "trace", "n2o_flag": False}))
    assert not [i for i in fine.values() if i["trigger"] == "soil_signal"]
    mid = by_id(recommend_for(res, "corn", signals={"nitrate_n_mgkg": 18.0}))["n_sidedress"]
    assert mid["priority"] < n["priority"] and "well below" not in mid["reason"]


def test_ph_rules_do_not_overlap():
    res = result(TYPICAL)
    acid = by_id(recommend_for(res, "alfalfa", signals={"ph": 5.2}))
    assert "lime" in acid and "lime_legume" not in acid
    mild = by_id(recommend_for(res, "alfalfa", signals={"ph": 5.8}))
    assert "lime_legume" in mild and "lime" not in mild
    assert "iron_chelate" in by_id(recommend_for(res, "soybean", signals={"ph": 8.0}))


def test_nitrification_inhibitor_needs_the_flag_or_a_wet_site():
    res = result(TYPICAL)
    sig = {"nitrification": "found", "n2o_flag": False}
    assert "nitrification_inhibitor" not in by_id(recommend_for(res, "corn", signals=sig))
    wet = by_id(recommend_for(res, "corn", signals=sig, context={"drainage_class": "Poorly drained"}))
    assert "poorly drained" in wet["nitrification_inhibitor"]["reason"]


def test_inoculant_follows_the_crop_history():
    res = result(TYPICAL)
    new = by_id(recommend_for(res, "soybean", signals={"crop_in_history": False, "bradyrhizobium_pct": 0.1}))
    assert "Bradyrhizobium is also low" in new["rhizobial_inoculant"]["reason"]
    assert new["rhizobial_inoculant"]["basis"] == "history"
    assert "rhizobial_inoculant" not in by_id(recommend_for(res, "soybean", signals={"crop_in_history": True}))
    assert "rhizobial_inoculant" not in by_id(recommend_for(res, "corn", signals={"crop_in_history": False}))
    bean = by_id(recommend_for(res, "dry_bean", signals={"crop_in_history": False, "bradyrhizobium_pct": 0.1}))
    assert "Bradyrhizobium" not in bean["rhizobial_inoculant"]["reason"]       # not the bean's nodule bacterium


def test_missing_values_give_no_item_and_are_listed():
    res = result(TYPICAL)
    assert not [i for i in recommend_for(res, "corn") if i["trigger"] == "soil_signal"]
    assert not [i for i in recommend_for(res, "corn", signals={"ph": float("nan"), "urease": "too_few_genes"})
                if i["trigger"] == "soil_signal"]
    todo = products.unanswered("corn")
    assert {"n_sidedress", "starter_n", "lime", "urease_inhibitor", "nitrification_inhibitor"} <= set(todo)
    assert "rhizobial_inoculant" not in todo       # not a corn product
    assert "lime" not in products.unanswered("corn", {"ph": 6.5})


def test_shallow_unit_keeps_soil_rules_but_no_pathogen_items():
    res = result({"Fusarium": 900}, n_cores=1, total=1500)
    items = recommend_for(res, "winter_wheat", signals={"ph": 5.0})
    assert {i["product_id"] for i in items} == {"lime", "p_band"}


def test_sorted_and_unknown_unit():
    res = result({"Fusarium": 900, "Bipolaris": [0, 0, 400], "Macrophomina": 13})
    items = recommend_for(res, "winter_wheat", signals={"ph": 5.0}, context={"p_wet_may": 0.8})
    assert [i["priority"] for i in items] == sorted((i["priority"] for i in items), reverse=True)
    assert all(0 <= i["priority"] <= 1 and set(i) == set(products.RECOMMENDATION_KEYS) for i in items)
    assert {i["timing"] for i in items} == set(products.TIMINGS)
    assert products.recommend(res.contributions, res.summary, "nope", "winter_wheat") == []
