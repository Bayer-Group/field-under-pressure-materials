"""Microbiome routes of the GUI API on a tiny synthetic dataset: no network, no real data."""
import datetime as dt

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cropfit import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    monkeypatch.setattr(api, "PROCESSED", proc)
    pd.DataFrame([dict(plotID="P_001", site="P", lat=39.2, lon=-96.6, half_m=20.0),
                  dict(plotID="P_002", site="P", lat=39.3, lon=-96.6, half_m=20.0)]).to_parquet(proc / "plot_geometry.parquet")
    pd.DataFrame([dict(metagenome_key="nmdc:dobj-1", plotID="P_001", date="2020-06-15", n_biosamples=3,
                       kraken_unclassified_pct=90.0),
                  dict(metagenome_key="nmdc:dobj-2", plotID="P_001", date="2021-06-15", n_biosamples=1,
                       kraken_unclassified_pct=95.0)]).to_parquet(proc / "metagenomes.parquet")
    L = lambda k, rank, name, phylum, reads: dict(metagenome_key=k, rank=rank, name=name, domain="Bacteria",
                                                  phylum=phylum, reads=reads)
    pd.DataFrame([
        L("nmdc:dobj-1", "domain", "Bacteria", None, 90_000), L("nmdc:dobj-1", "domain", "Archaea", None, 10_000),
        L("nmdc:dobj-1", "phylum", "Actinobacteria", "Actinobacteria", 50_000),
        L("nmdc:dobj-1", "phylum", "Proteobacteria", "Proteobacteria", 30_000),
        L("nmdc:dobj-1", "phylum", "Thaumarchaeota", "Thaumarchaeota", 10_000),
        L("nmdc:dobj-1", "genus", "Streptomyces", "Actinobacteria", 20_000),
        L("nmdc:dobj-1", "genus", "Bradyrhizobium", "Proteobacteria", 10_000),
        L("nmdc:dobj-1", "genus", "Nitrososphaera", "Thaumarchaeota", 5_000),
        L("nmdc:dobj-2", "domain", "Bacteria", None, 500),
        L("nmdc:dobj-2", "phylum", "Actinobacteria", "Actinobacteria", 500),
    ]).to_parquet(proc / "taxa_lineage.parquet")
    G = lambda genus, pct, reads: dict(site="P", plotID="P_001", collectDate=dt.date(2020, 6, 15), year=2020,
                                       n_cores=2, product="DP1.10081.001", genus=genus, reads=reads,
                                       total_reads=1000, rel_abund_pct=pct, its_below_threshold_share=1 / 3)
    pd.DataFrame([G("Fusarium", 40.0, 400), G("Mortierella", 30.0, 300), G("Hypocreales_gen_Incertae_sedis", 10.0, 100),
                  G("unclassified_Fungi", 20.0, 200), G("Macrophomina", 0.0, 0)]).to_parquet(proc / "its_genus.parquet")
    pd.DataFrame([dict(genus="Fusarium", phylum="Ascomycota", **{"class": "Sordariomycetes"}),
                  dict(genus="Mortierella", phylum="Mortierellomycota", **{"class": "Mortierellomycetes"}),
                  dict(genus="Hypocreales_gen_Incertae_sedis", phylum="Ascomycota", **{"class": "Sordariomycetes"})]
                 ).to_parquet(proc / "its_genus_lineage.parquet")
    return TestClient(api.create_app())


def test_samples_of_a_plot(client):
    s = client.get("/api/plots/P_001/microbiome").json()
    assert [(x["sample_id"], x["kind"], x["date"]) for x in s] == [
        ("mg-dobj-1", "bacteria", "2020-06-15"), ("its-P_001-20200615", "fungi", "2020-06-15"),
        ("mg-dobj-2", "bacteria", "2021-06-15")]
    assert [x["low_depth"] for x in s] == [False, True, True]   # 1,000 fungal reads and 500 bacterial reads are few
    assert s[0]["reads"] == 100_000 and s[0]["n_cores"] == 3
    assert client.get("/api/plots/P_002/microbiome").json() == []
    assert client.get("/api/plots/NOPE/microbiome").status_code == 404


def test_bacteria_composition_shares_add_up(client):
    c = client.get("/api/microbiome/mg-dobj-1?rank=genus&top=2").json()
    assert [(t["name"], t["phylum"], t["pct"]) for t in c["taxa"]] == [
        ("Streptomyces", "Actinobacteria", 20.0), ("Bradyrhizobium", "Proteobacteria", 10.0)]
    assert c["other_pct"] == 5.0 and c["unassigned_pct"] == 65.0 and c["n_taxa"] == 3
    assert sum(t["pct"] for t in c["taxa"]) + c["other_pct"] + c["unassigned_pct"] == pytest.approx(100)
    a = client.get("/api/microbiome/mg-dobj-1?rank=genus").json()  # without top: every taxon, nothing folded
    assert [t["name"] for t in a["taxa"]] == ["Streptomyces", "Bradyrhizobium", "Nitrososphaera"] and a["other_pct"] == 0
    p = client.get("/api/microbiome/mg-dobj-1").json()           # phylum is the default rank
    assert p["rank"] == "phylum" and p["taxa"][0] == dict(name="Actinobacteria", phylum="Actinobacteria", pct=50.0, reads=50_000, description=None)
    assert p["unassigned_pct"] == 10.0
    assert any("90%" in n for n in p["notes"])


def test_fungi_composition_placeholders_are_unassigned(client):
    g = client.get("/api/microbiome/its-P_001-20200615?rank=genus").json()
    assert [t["name"] for t in g["taxa"]] == ["Fusarium", "Mortierella"]       # zero-read genera are left out
    assert g["unassigned_pct"] == 30.0                                           # placeholder + unclassified
    p = client.get("/api/microbiome/its-P_001-20200615?rank=phylum").json()
    assert [(t["name"], t["pct"]) for t in p["taxa"]] == [("Ascomycota", 50.0), ("Mortierellomycota", 30.0)]
    assert p["unassigned_pct"] == 20.0
    notes = " ".join(p["notes"])
    assert "older method" in notes and "33%" in notes and "Few DNA reads" in notes


def test_bad_requests(client):
    assert client.get("/api/microbiome/its-P_001-19990101").status_code == 404
    assert client.get("/api/microbiome/mg-dobj-1?rank=species").status_code == 422
    assert client.get("/api/microbiome/mg-dobj-1?top=0").status_code == 422


def test_missing_tables_are_reported(client):
    for n in ("metagenomes", "taxa_lineage", "its_genus"):
        (api.PROCESSED / f"{n}.parquet").unlink()
    r = client.get("/api/plots/P_001/microbiome")
    assert r.status_code == 503 and "05_build_biology" in r.json()["detail"]


# ---------------------------------------------------------------- roles (docs/microbe_roles.md)
def test_genus_composition_carries_descriptions(client, role_files):
    g = {t["name"]: t["description"] for t in client.get("/api/microbiome/mg-dobj-1?rank=genus").json()["taxa"]}
    assert g["Streptomyces"].startswith("Thread-forming") and g["Bradyrhizobium"] is None
    assert all(t["description"] is None for t in client.get("/api/microbiome/mg-dobj-1").json()["taxa"])   # phylum rank
    assert client.get("/api/microbiome/its-P_001-20200615?rank=genus").json()["taxa"][0]["description"].startswith("Common soil")


def test_bacteria_roles(client, role_files):
    c = client.get("/api/microbiome/mg-dobj-1/roles").json()
    s = {x["class_id"]: x for x in c["summary"]}
    assert [x["class_id"] for x in c["summary"]] == ["useful", "mixed", "harmful", "context", "background", "unknown"]
    assert [s[k]["pct"] for k in ("useful", "mixed", "harmful", "context", "background", "unknown")] == [10, 20, 0, 5, 0, 0]
    assert (s["useful"]["pct_of_named"], s["mixed"]["pct_of_named"], s["context"]["pct_of_named"]) == (28.57, 57.14, 14.29)
    assert s["mixed"]["label"] == "Mixed (useful and harmful species)" and s["mixed"]["top"] == ["Streptomyces"]
    assert c["unassigned_pct"] == 65 and c["annotated_pct"] == 35 and c["n_genera"] == 3 and c["reads"] == 100_000
    t = {x["term_id"]: x for x in c["terms"]}
    assert len(c["terms"]) == 32 and c["terms"][0]["term_id"] == "useful"
    assert {k: t[k]["pct"] for k in ("useful", "nutrient_supply", "n_fixation", "legume_symbiont", "biocontrol",
                                     "antibiotic_producer", "harmful", "plant_pathogen", "root_soilborne_pathogen",
                                     "context", "nitrification", "denitrification")} == dict(
        useful=30, nutrient_supply=10, n_fixation=10, legume_symbiont=10, biocontrol=20, antibiotic_producer=20,
        harmful=20, plant_pathogen=20, root_soilborne_pathogen=20, context=5, nitrification=5, denitrification=0)
    g = t["n_fixation"]["genera"][0]
    assert (g["name"], g["term_id"], g["confidence"], g["domain"], g["pct"]) == (
        "Bradyrhizobium", "legume_symbiont", "high", "Bacteria", 10.0)
    assert g["species_examples"] == ["Bradyrhizobium japonicum"] and g["note"] is None and g["description"] is None
    assert t["plant_pathogen"]["genera"][0]["note"] == "potato scab" and t["unknown"]["n_genera"] == 0
    assert c["sources"] == ["llm:test"] and t["denitrification"]["genera"] == []
    notes = " ".join(c["notes"])
    assert "AI (LLM) annotation" in notes and "medium or high confidence" in notes and "not yet annotated" not in notes
    assert "Based on 3 soil cores from the plot." in c["notes"]


def test_roles_genera_cap_and_other_pct(client, role_files):
    c = client.get("/api/microbiome/mg-dobj-1/roles?genera_per_term=1").json()
    t = {x["term_id"]: x for x in c["terms"]}
    assert len(t["useful"]["genera"]) == 1 and t["useful"]["genera"][0]["name"] == "Streptomyces"
    assert t["useful"]["other_genera_pct"] == 10 and t["biocontrol"]["other_genera_pct"] == 0
    assert client.get("/api/microbiome/mg-dobj-1/roles?genera_per_term=0").status_code == 422
    assert client.get("/api/microbiome/mg-nope/roles").status_code == 404


def test_fungi_roles_with_and_without_curated_tables(client, role_files):
    url = "/api/microbiome/its-P_001-20200615/roles"
    c = client.get(url).json()
    s = {x["class_id"]: x["pct"] for x in c["summary"]}
    assert s["harmful"] == 40 and s["unknown"] == 30 and c["unassigned_pct"] == 30 and c["annotated_pct"] == 70
    assert any("tables are missing" in n for n in c["notes"])
    G = pd.DataFrame([dict(genus="Mortierella", trophic_mode="", guilds="", primary_guild="Undefined Saprotroph",
                           category="saprotroph", can_be_plant_pathogen=False, can_parasitise_fungi=False,
                           confidence="Probable")])
    G.to_parquet(api.PROCESSED / "fungal_guilds.parquet")
    pd.DataFrame([dict(genus="Fusarium", primary_lifestyle="plant_pathogen", secondary_lifestyle="litter_saprotroph",
                       plant_pathogenic_capacity="leaf/fruit/seed_pathogen")]).to_parquet(
        api.PROCESSED / "kb_fungaltraits_genus.parquet")
    c = client.get(url).json()
    s = {x["class_id"]: x["pct"] for x in c["summary"]}
    t = {x["term_id"]: x for x in c["terms"]}
    assert s["background"] == 30 and s["unknown"] == 0 and s["harmful"] == 40
    m = t["decomposer"]["genera"]
    assert {(x["name"], x["confidence"], x["source"]) for x in m} == {("Mortierella", "medium", "funguild"),
                                                                       ("Fusarium", "medium", "fungaltraits")}
    f = t["foliar_pathogen"]["genera"][0]
    assert (f["name"], f["confidence"], f["source"]) == ("Fusarium", "high", "fungaltraits")
    assert t["root_soilborne_pathogen"]["genera"][0]["source"] == "llm:test"          # LLM organ row kept
    assert c["sources"] == ["fungaltraits", "funguild", "llm:test"]
    assert not any("tables are missing" in n for n in c["notes"])


def test_roles_without_annotation_files(client, tmp_path, monkeypatch):
    from cropfit import microbe_roles
    monkeypatch.setattr(microbe_roles, "ANNOTATIONS_FILE", tmp_path / "nope.csv")
    monkeypatch.setattr(microbe_roles, "GENERA_FILE", tmp_path / "nope2.csv")
    c = client.get("/api/microbiome/mg-dobj-1/roles").json()
    assert {x["class_id"]: x["pct"] for x in c["summary"]}["unknown"] == 35 and c["annotated_pct"] == 0
    assert any("not available" in n for n in c["notes"]) and any("not yet annotated" in n for n in c["notes"])
    assert all(t["description"] is None for t in client.get("/api/microbiome/mg-dobj-1?rank=genus").json()["taxa"])
