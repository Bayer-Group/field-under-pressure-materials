"""Crop-risk routes of the GUI API on a synthetic site: no network, no real data."""
import json
import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cropfit import api, api_risk, risk
from cropfit import kb as kbmod
from test_risk import core_rows, mk_kb

P2, P1 = "DP1.10081.002", "DP1.10081.001"
N_EXTRA = 20                      # genera FungalTraits excludes, detected in every unit: fills the capped skip group
EXTRA = [(f"Xgen{i:02d}", f"Xgen{i:02d}", "Ascomycota", False, None, "not_plant_pathogen") for i in range(N_EXTRA)]


def unit_rows(plot, date, product, i, total=11500, fus_shift=0):
    reads = {"Fusarium": 30 + 40 * i + fus_shift, "Bipolaris": 5 * (i % 4), "Macrophomina": 3 * (i % 5),
             "Pythium": 12 if i % 2 else 0, "Colletotrichum": 8, "Trichoderma": 40,
             **{f"Xgen{k:02d}": 5 + k for k in range(N_EXTRA)}}
    return core_rows("STER", plot, date, product, reads, total=total)


def make_core(fus_shift=0) -> pd.DataFrame:
    rows = []
    for i in range(12):                                         # 2021 and 2022, current method
        rows += unit_rows(f"STER_{i + 1:03d}", "2021-07-01", P2, i, fus_shift=fus_shift)
        rows += unit_rows(f"STER_{i + 1:03d}", "2022-07-01", P2, 11 - i, fus_shift=fus_shift)
    rows += unit_rows("STER_030", "2022-07-02", P2, 3, total=1500)        # shallow
    rows += unit_rows("STER_020", "2016-07-01", P1, 1)                    # one plot, both methods in 2016
    rows += unit_rows("STER_020", "2016-09-01", P2, 2)
    for i, p in enumerate(("STER_021", "STER_022", "STER_023", "STER_024", "STER_025")):   # older-method peers (6 ≥ 5 scored)
        rows += unit_rows(p, "2016-07-05", P1, 4 + i)
    return pd.DataFrame(rows)


@pytest.fixture
def client(tmp_path, monkeypatch):
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    monkeypatch.setattr(api, "PROCESSED", proc)
    plots = [f"STER_{i:03d}" for i in list(range(1, 13)) + [20, 21, 22, 23, 30, 999]]
    pd.DataFrame([dict(plotID=p, site="STER", lat=40.0, lon=-103.0, half_m=20.0) for p in plots]
                 ).to_parquet(proc / "plot_geometry.parquet")
    make_core().to_parquet(proc / "its_core_genus.parquet")
    kb = mk_kb(extra_genera=EXTRA)
    kb.genera.to_parquet(proc / kbmod.GENERA_TABLE)
    kb.host.to_parquet(proc / kbmod.HOST_TABLE)
    (proc / kbmod.META_FILE).write_text(json.dumps(
        {"sources": {"fungaltraits": {"url": "u1", "source_version": "FT v", "retrieved_utc": "2026-01-01T00:00:00Z"},
                     "usda_fungus_host": {"url": "u2", "source_version": "USDA v"}}}))
    for c in (api_risk._result, api_risk._site_units, api_risk._load_kb, api._read):
        c.cache_clear()
    c = TestClient(api.create_app())
    c.proc = proc
    yield c
    for f in (api_risk._result, api_risk._site_units, api_risk._load_kb, api._read):
        f.cache_clear()


def direct(client, year=2022):
    core = pd.read_parquet(client.proc / "its_core_genus.parquet")
    return risk.compute_crop_risk("STER", year, core=core, kb=kbmod.load_kb(client.proc))


def test_unit_list(client):
    u = client.get("/api/plots/STER_020/crop-risk").json()
    assert [x["unit"] for x in u] == ["2016-002", "2016-001"]
    assert u[0]["method"] == "current" and u[1]["method"] == "older"
    assert u[0]["method_label"] == "current ITS method (.002)"
    assert u[1]["method_label"].startswith("older ITS method (.001)")
    assert u[0]["collect_dates"] == ["2016-09-01"] and u[0]["total_reads"] == 11500 and u[0]["n_cores"] == 1
    assert [x["unit"] for x in client.get("/api/plots/STER_001/crop-risk").json()] == ["2022-002", "2021-002"]
    shallow = client.get("/api/plots/STER_030/crop-risk").json()
    assert [(x["unit"], x["low_depth"]) for x in shallow] == [("2022-002", True)]
    assert not u[0]["low_depth"]
    assert client.get("/api/plots/STER_999/crop-risk").json() == []
    assert client.get("/api/plots/NOPE/crop-risk").status_code == 404


def test_unit_response_matches_scorer(client):
    r = client.get("/api/plots/STER_005/crop-risk/2022-002").json()
    assert r["site"] == "STER" and r["unit"] == "2022-002" and r["year"] == 2022 and r["product"] == P2
    assert r["n_units_in_group"] == 13 and r["index_type"].startswith("relative")
    assert [c["crop"] for c in r["crops"]] == list(kbmod.SCORED_CROPS)
    assert r["parameters"]["min_unit_reads"] == 2000 and r["caveats"] and "kb" in r
    assert [k["name"] for k in r["kb"]] == ["FungalTraits", "USDA Fungus-Host"] and r["kb"][0]["url"] == "u1"
    s = direct(client).summary
    s = s[s["product"] == P2]
    for row in r["crops"]:
        sub = s[s["crop"] == row["crop"]]
        ok = sub[sub["status"] == "ok"]
        me = sub[sub["unit_id"] == f"STER_005|2022|{P2}"].iloc[0]
        assert row["status"] == me["status"]
        if row["status"] != "ok":
            continue
        assert row["risk_index"] == pytest.approx(me["risk_index"], abs=1e-4)
        assert row["rank"] == 1 + (ok["risk_index"] > me["risk_index"]).sum()
        assert row["n_peers"] == len(ok) == len(row["peers"])
        assert row["percentile"] == pytest.approx(100 * ((ok["risk_index"] < me["risk_index"]).sum()
                                                         + 0.5 * (ok["risk_index"] == me["risk_index"]).sum())
                                                  / len(ok), abs=0.06)
        assert row["from_detected"] + row["from_not_detected"] == pytest.approx(row["risk_index"], abs=2e-4)
        vals = [p["risk_index"] for p in row["peers"]]
        assert vals == sorted(vals, reverse=True)
        assert "STER_005" in {p["plot_id"] for p in row["peers"]}
    ww, sw = (next(c for c in r["crops"] if c["crop"] == k) for k in ("winter_wheat", "spring_wheat"))
    same = direct(client).metadata["same_host_taxa_as"]
    assert ww["same_as"] is None and sw["same_as"] == same.get("spring_wheat")
    assert {c["crop"]: c["same_as"] for c in r["crops"] if c["same_as"]} == same


def test_peers_are_same_product_only(client):
    r = client.get("/api/plots/STER_020/crop-risk/2016-001").json()
    assert r["n_units_in_group"] == 6
    ww = next(c for c in r["crops"] if c["crop"] == "winter_wheat")
    assert ww["status"] == "ok"
    assert {p["plot_id"] for p in ww["peers"]} == {"STER_020", "STER_021", "STER_022", "STER_023", "STER_024", "STER_025"}
    assert ww["n_peers"] == 6
    cur = client.get("/api/plots/STER_020/crop-risk/2016-002").json()
    assert cur["n_units_in_group"] == 1
    assert next(c for c in cur["crops"] if c["crop"] == "winter_wheat")["n_peers"] == 1


def test_statuses_and_shallow_units(client):
    r = client.get("/api/plots/STER_005/crop-risk/2022-002").json()
    nk = next(c for c in r["crops"] if c["crop"] == "millet")
    assert nk["status"] == "no_knowledge" and nk["risk_index"] is None and nk["rank"] is None
    assert nk["percentile"] is None and nk["from_detected"] is None
    ww = next(c for c in r["crops"] if c["crop"] == "winter_wheat")
    assert ww["status"] == "ok" and ww["n_peers_too_shallow"] == 1 and ww["n_peers"] == 12
    assert "STER_030" not in {p["plot_id"] for p in ww["peers"]}
    sh = client.get("/api/plots/STER_030/crop-risk/2022-002").json()
    assert sh["low_depth"] and all(c["status"] == "insufficient_depth" for c in sh["crops"])
    assert all(c["risk_index"] is None and c["rank"] is None for c in sh["crops"])
    assert [g["reason"] for g in sh["skipped"]] == ["insufficient_depth_unit"]
    assert sh["skipped"][0]["genera"][0]["genus"] is None


def test_skipped_groups_capped_and_oomycete(client):
    r = client.get("/api/plots/STER_001/crop-risk/2022-002").json()      # odd unit index: Pythium detected
    g = {x["reason"]: x for x in r["skipped"]}
    assert "oomycete" in g and g["oomycete"]["genera"][0]["genus"] == "Pythium"
    assert g["oomycete"]["label"] == "Oomycete, not measured by fungal ITS"
    f = g["excluded_by_filter"] if "excluded_by_filter" in g else None
    assert f is not None and f["n"] >= N_EXTRA and len(f["genera"]) == 15 and f["more"] == f["n"] - 15
    reads = [x["reads"] for x in f["genera"]]
    assert reads == sorted(reads, reverse=True)
    assert "no_usda_host_records" in g
    order = list(api_risk.REASON_LABELS)
    assert [x["reason"] for x in r["skipped"]] == [k for k in order if k in g]


def test_contributions(client):
    c = client.get("/api/plots/STER_005/crop-risk/2022-002/winter_wheat").json()
    assert c["label"] == "Winter wheat" and c["row"]["crop"] == "winter_wheat" and c["unit"] == "2022-002"
    cs = c["contributions"]
    assert cs and all(x["contribution"] > 0 for x in cs)
    vals = [x["contribution"] for x in cs]
    assert vals == sorted(vals, reverse=True)
    assert sum(vals) == pytest.approx(c["row"]["risk_index"], abs=1e-3)
    for x in cs:
        assert x["h"] == pytest.approx(x["n_species_on_crop"] / x["n_species_documented"], abs=1e-3)
        assert len(x["species_on_crop"]) <= 10 and x["n_species_more"] == max(0, x["n_species_on_crop"] - 10)
    fus = next(x for x in cs if x["genus"] == "Fusarium")
    assert fus["detected"] and fus["n_species_on_crop"] == 60 and fus["n_species_more"] == 50
    assert fus["lifestyle"] == "plant_pathogen" and fus["members"] == ["Fusarium"]
    assert c["n_scored_zero_h"] >= 1                                    # Macrophomina, Rhizoctonia have no wheat hosts
    assert client.get("/api/plots/STER_005/crop-risk/2022-002/rice").status_code == 404
    assert client.get("/api/plots/STER_005/crop-risk/1999-002/corn").status_code == 404
    assert client.get("/api/plots/STER_005/crop-risk/1999-002").status_code == 404
    assert client.get("/api/plots/STER_999/crop-risk/2022-002").status_code == 404


def test_plot_missing_from_geometry_is_still_known(client):
    geo = pd.read_parquet(client.proc / "plot_geometry.parquet")
    assert "STER_024" not in set(geo["plotID"])                          # scored peer that is not on the map
    assert client.get("/api/plots/STER_024/crop-risk").status_code == 200
    assert client.get("/api/plots/STER_024/crop-risk").json()
    r = client.get("/api/plots/STER_024/crop-risk/2016-001/corn")
    assert r.status_code == 200 and r.json()["contributions"]
    assert client.get("/api/plots/STER_777/crop-risk").status_code == 404


def test_missing_inputs_give_503(client):
    (client.proc / kbmod.META_FILE).unlink()
    r = client.get("/api/plots/STER_005/crop-risk/2022-002")
    assert r.status_code == 503 and "14_build_kb" in r.json()["detail"]
    assert client.get("/api/plots/STER_005/crop-risk").status_code == 200   # units need no KB
    core = client.proc / "its_core_genus.parquet"
    make_core().drop(columns="product").to_parquet(core)
    r = client.get("/api/plots/STER_005/crop-risk")
    assert r.status_code == 503 and "02b" in r.json()["detail"]
    core.unlink()
    r = client.get("/api/plots/STER_005/crop-risk")
    assert r.status_code == 503 and "02b" in r.json()["detail"]


def test_cache_invalidated_by_new_core_table(client):
    url = "/api/plots/STER_005/crop-risk/2022-002/winter_wheat"
    before = client.get(url).json()["row"]["risk_index"]
    assert client.get(url).json()["row"]["risk_index"] == before
    core = client.proc / "its_core_genus.parquet"
    df = make_core()
    df.loc[(df["plotID"] == "STER_005") & (df["genus"] == "Fusarium") & df["collectDate"].str.startswith("2022"),
           "reads"] = 5000
    df.to_parquet(core)
    st = core.stat()
    os.utime(core, (st.st_atime, st.st_mtime + 10))
    after = client.get(url).json()["row"]["risk_index"]
    assert after != before


def test_responses_are_strict_json(client):
    import json
    for unit in client.get("/api/plots/STER_020/crop-risk").json():
        r = client.get(f"/api/plots/STER_020/crop-risk/{unit['unit']}").json()
        json.dumps(r, allow_nan=False)
        for c in r["crops"]:
            json.dumps(client.get(f"/api/plots/STER_020/crop-risk/{unit['unit']}/{c['crop']}").json(), allow_nan=False)


def test_light_mode_scores_only_light_plots(client):
    (client.proc.parent / "light_mode.txt").write_text("# light mode\nSTER_001\nSTER 002\nSTER_003\nSTER_004\nSTER_005\n")
    light = {"STER_001", "STER_002", "STER_003", "STER_004", "STER_005"}
    r = client.get("/api/plots/STER_001/crop-risk/2022-002").json()
    assert r["n_units_in_group"] == 5 and r["notes"][0].startswith("Light mode is on")
    for c in r["crops"]:
        assert {p["plot_id"] for p in c["peers"]} <= light
    assert client.get("/api/plots/STER_006/crop-risk").json() == []        # outside light mode: no ITS units
    (client.proc.parent / "light_mode.txt").unlink()                        # switching off is picked up (cache key)
    r = client.get("/api/plots/STER_001/crop-risk/2022-002").json()
    assert r["n_units_in_group"] > 5 and not any(n.startswith("Light mode") for n in r["notes"])
