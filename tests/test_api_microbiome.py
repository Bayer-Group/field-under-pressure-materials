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
    assert p["rank"] == "phylum" and p["taxa"][0] == dict(name="Actinobacteria", phylum="Actinobacteria", pct=50.0, reads=50_000)
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
