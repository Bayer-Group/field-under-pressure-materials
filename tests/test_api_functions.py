"""Soil-functions routes of the GUI API on a tiny synthetic dataset: no network, no real data.
The view reads one sample on its own: nothing is ranked against other samples."""
import datetime as dt

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cropfit import api, funguild
from cropfit.api_functions import Measured, _cards, _pathways


@pytest.fixture
def client(tmp_path, monkeypatch):
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    monkeypatch.setattr(api, "PROCESSED", proc)
    pd.DataFrame([dict(plotID="P_001", site="P", lat=39.2, lon=-96.6, half_m=20.0)]).to_parquet(proc / "plot_geometry.parquet")
    pd.DataFrame([dict(metagenome_key="nmdc:dobj-a", site="P", plotID="P_001", date="2022-06-06", n_ko_genes=800_000,
                       ko_depth_ok=True),
                  dict(metagenome_key="nmdc:dobj-s", site="P", plotID="P_001", date="2017-06-05", n_ko_genes=900,
                       ko_depth_ok=False)]).to_parquet(proc / "metagenomes.parquet")
    genes = {"narG/nxrA": 300, "nirK": 200, "norB": 120, "nosZ": 20, "nrfA": 10, "pmoA-amoA": 40, "hao": 10,
             "narH/nxrB": 50, "nifH": 2, "ureC": 100, "phoD": 60, "gcd": 40, "acdS": 30, "phlD": 0, "pcoC/copC": 8,
             "cusA": 30}
    group = {"narG/nxrA": "denitrification", "nirK": "denitrification", "norB": "denitrification", "nosZ": "nosZ",
             "nrfA": "dnra", "pmoA-amoA": "nitrification", "hao": "nitrification", "narH/nxrB": "nitrification",
             "nifH": "n_fixation", "ureC": "urease", "phoD": "p_mobilisation", "gcd": "p_mobilisation", "acdS": "acdS",
             "phlD": "phlD", "pcoC/copC": "copper_resistance", "cusA": "copper_resistance"}
    rows = [dict(metagenome_key="nmdc:dobj-a", ko="K0", gene=g, function_group=group[g], count=n, per_genome_eq=n / 500,
                 per_million=0.0) for g, n in genes.items()]
    rows += [dict(metagenome_key="nmdc:dobj-s", ko="K0", gene="nirK", function_group="denitrification", count=1,
                  per_genome_eq=0.1, per_million=0.0)]
    pd.DataFrame(rows).to_parquet(proc / "ko_panel.parquet")
    pd.DataFrame([dict(plotID="P_001", collectDate=dt.date(2022, 6, 8), ammonium_n_mgkg=4.0, nitrate_n_mgkg=15.0,
                       n_cores=3, net_n_min_mgkg_d=-0.3, net_nitrif_mgkg_d=-0.1, n_pairs=3, site="P")]
                 ).to_parquet(proc / "neon_inorganic_n.parquet")
    pd.DataFrame([dict(plotID="P_001", collectDate=dt.date(2022, 6, 6), organic_c_pct=1.2, total_n_pct=0.1,
                       cn_ratio=12.0, ph_water=7.2, ph_cacl2=6.8, soil_moisture=0.1, n_cores=3, site="P")]
                 ).to_parquet(proc / "neon_chem.parquet")
    F = lambda key, genus, pct: dict(metagenome_key=key, genus=genus, rel_abund_pct=pct)  # noqa: E731
    pd.DataFrame([F("nmdc:dobj-a", "Mortierella", 40.0), F("nmdc:dobj-a", "Fusarium", 30.0),
                  F("nmdc:dobj-a", "Trichoderma", 10.0), F("nmdc:dobj-a", "Glomus", 0.2),
                  F("nmdc:dobj-a", "unclassified_Fungi", 19.8),
                  F("nmdc:dobj-s", "Mortierella", 60.0), F("nmdc:dobj-s", "Fusarium", 40.0)]
                 ).to_parquet(proc / "joined_fungi_genus.parquet")
    G = lambda genus, cat, path, para: dict(genus=genus, trophic_mode="", guilds="", primary_guild="", category=cat,  # noqa: E731
                                            can_be_plant_pathogen=path, can_parasitise_fungi=para, confidence="Probable")
    pd.DataFrame([G("Mortierella", "saprotroph", False, False), G("Fusarium", "plant_pathogen", True, False),
                  G("Trichoderma", "fungal_parasite", True, True), G("Glomus", "arbuscular_mycorrhizal", False, False)]
                 ).to_parquet(proc / "fungal_guilds.parquet")
    return TestClient(api.create_app())


def test_samples_of_a_plot(client):
    s = client.get("/api/plots/P_001/functions").json()
    assert [(x["sample_id"], x["deep_enough"]) for x in s] == [("mg-dobj-s", False), ("mg-dobj-a", True)]
    assert client.get("/api/plots/NOPE/functions").status_code == 404
    assert client.get("/api/functions/mg-nope").status_code == 404


def test_profile_reads_the_sample_on_its_own(client):
    p = client.get("/api/functions/mg-dobj-a").json()
    def keys(x):
        if isinstance(x, dict):
            return set(x) | set().union(*(keys(v) for v in x.values()))
        return set().union(*(keys(v) for v in x)) if isinstance(x, list) else set()
    assert not keys(p) & {"percentile", "level", "relative", "reference", "ref_min", "ref_median", "ref_max",
                          "n2o_ratio_percentile"}                       # nothing compares with other samples
    den = next(x for x in p["pathways"] if x["kegg_module"] == "M00529")
    assert den["complete"] and [s["copies"] for s in den["steps"]] == [300, 200, 120, 20]
    fix = next(x for x in p["pathways"] if x["kegg_module"] == "M00175")
    assert fix["steps"][0]["status"] == "trace"                               # 2 copies < MIN_COUNT
    cards = {c["card"]: c for c in p["cards"]}
    n = cards["nitrogen"]
    assert "full denitrification pathway" in n["finding"] and "No nitrogen fixation" in n["finding"]
    assert any(i["kind"] == "risk" and "About 6 genes that make N2O" in i["text"] for i in n["implications"])
    assert any("pH 7.2" in i["text"] and "ammonia" in i["text"] for i in n["implications"])   # urea at pH >= 7
    assert p["measured"]["soil_moisture"] == 0.1


def test_fungal_roles_from_the_same_cores(client):
    p = client.get("/api/functions/mg-dobj-a").json()
    f = p["fungi"]
    assert f["same_cores"] and f["named_pct"] == pytest.approx(80.2)
    roles = {r["role"]: r for r in f["roles"]}
    assert roles["saprotroph"]["pct"] == pytest.approx(49.9, abs=0.1)        # 40 of the 80.2 named
    assert sum(r["pct"] for r in f["roles"]) == pytest.approx(100, abs=0.2)
    card = next(c for c in p["cards"] if c["card"] == "fungi")
    assert "<1% from mycorrhizal fungi" in card["finding"]
    assert any("Fusarium" in i["text"] for i in card["implications"] if i["kind"] == "risk")
    assert any("Trichoderma" in i["text"] for i in card["implications"] if i["kind"] == "upside")


def test_shallow_sample_keeps_measured_and_fungal_cards(client):
    p = client.get("/api/functions/mg-dobj-s").json()
    cards = {c["card"]: c for c in p["cards"]}
    assert not p["deep_enough"] and p["notes"][0].startswith("Too few genes")
    assert cards["nitrogen"]["status"] == "unknown" and cards["nitrogen"]["headline"] == "Too few genes to tell"
    assert cards["fungi"]["status"] == "notice"                               # fungi do not depend on gene depth
    assert "Fusarium alone is 40% of fungal DNA" in cards["fungi"]["flag"]
    assert cards["n_now"]["status"] == "unknown"                              # no NEON visit within a week of 2017
    assert all(s["status"] == "too_few_genes" for s in p["pathways"][0]["steps"][2:])


def test_cards_are_ranked_by_confidence(client):
    cards = client.get("/api/functions/mg-dobj-a").json()["cards"]
    rank = [(c["status"] == "unknown", {"high": 0, "medium": 1, "low": 2}[c["confidence"]]) for c in cards]
    assert rank == sorted(rank) and cards[0]["basis"] == "measured"


def test_nitrate_thresholds():
    m = lambda no3: Measured(date=dt.date(2022, 6, 6), ammonium_n_mgkg=1.0, nitrate_n_mgkg=no3, net_n_min_mgkg_d=None,  # noqa: E731
                             net_nitrif_mgkg_d=None, ph_water=None, organic_c_pct=None, total_n_pct=None,
                             cn_ratio=None, soil_moisture=None)
    status = lambda no3: next(c.status for c in _cards({}, _pathways({}, False), None, m(no3), False, pd.DataFrame())  # noqa: E731
                              if c.card == "n_now")
    assert (status(30), status(15), status(5)) == ("good", "watch", "act")


def test_funguild_primary_guild_and_category():
    assert funguild.primary_guild("Endophyte-|Plant Pathogen|-Plant Saprotroph") == "Plant Pathogen"
    assert funguild.primary_guild("Arbuscular Mycorrhizal") == "Arbuscular Mycorrhizal"
    assert funguild.primary_guild("") is None
    assert funguild.category("Undefined Saprotroph") == "saprotroph"
    assert funguild.category("Arbuscular Mycorrhizal") == "arbuscular_mycorrhizal"
    assert funguild.category(None) == "unknown"
    recs = pd.DataFrame([dict(taxon="Fusarium", taxonomicLevel="13", trophicMode="Pathotroph",
                              guild="Endophyte-|Plant Pathogen|", confidenceRanking="Possible"),
                         dict(taxon="Trichoderma", taxonomicLevel="13", trophicMode="Pathotroph",
                              guild="|Fungal Parasite|-Plant Pathogen", confidenceRanking="Probable"),
                         dict(taxon="Fusarium oxysporum", taxonomicLevel="20", trophicMode="Pathotroph",
                              guild="|Plant Pathogen|", confidenceRanking="Probable")])
    t = funguild.guild_table(recs).set_index("genus")
    assert list(t.index) == ["Fusarium", "Trichoderma"]                       # genus level only
    assert t.loc["Trichoderma", "can_parasitise_fungi"] and t.loc["Trichoderma", "can_be_plant_pathogen"]


def test_cards_are_coloured_only_by_stated_rules(client):
    cards = {c["card"]: c for c in client.get("/api/functions/mg-dobj-a").json()["cards"]}
    assert all(c["headline"] for c in cards.values())
    assert cards["nitrogen"]["status"] == "info" and cards["nitrogen"]["flag"] is None     # norB:nosZ = 6 < 10
    assert cards["fungi"]["status"] == "notice"                               # Fusarium 30 of 80.2 named = 37%
    assert cards["soil"]["status"] == "info"                                  # pH 7.2, organic carbon 1.2%: no risk band
    assert {c["status"] for k, c in cards.items() if k in ("p_release", "copper", "root_health")} == {"info"}


def test_nitrogen_card_flags_missing_n2o_removal():
    copies = {"narG/nxrA": 50, "nirK": 40, "norB": 30, "nosZ": 0}
    card = next(c for c in _cards(copies, _pathways(copies, True), None, None, True, pd.DataFrame())
                if c.card == "nitrogen")
    assert card.status == "notice" and "no N2O-removing gene" in card.flag
