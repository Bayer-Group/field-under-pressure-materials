"""Raw-data integrity: no partial overwrites, atomic cache, one DNA extract per core. No network."""
import json
import types

import pandas as pd
import pytest

from cropfit import http, neon


def _fake_nu(fail_sites):
    def load_by_product(dpid, site, **kw):
        if site in fail_sites:
            raise ConnectionError("boom")
        return {"tab": pd.DataFrame({"siteID": [site], "v": [1]})}
    return types.SimpleNamespace(load_by_product=load_by_product)


def test_fetch_product_keeps_raw_when_a_site_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(neon, "RAW_NEON", tmp_path)
    monkeypatch.setitem(__import__("sys").modules, "neonutilities", _fake_nu(set()))
    neon.fetch_product("DP0", sites=["STER", "KONA"])
    f = tmp_path / "DP0" / "tab.parquet"
    assert set(pd.read_parquet(f).siteID) == {"STER", "KONA"}

    monkeypatch.setitem(__import__("sys").modules, "neonutilities", _fake_nu({"KONA"}))
    with pytest.raises(neon.IncompleteFetch, match="KONA"):
        neon.fetch_product("DP0", sites=["STER", "KONA"])
    assert set(pd.read_parquet(f).siteID) == {"STER", "KONA"}   # untouched

    neon.fetch_product("DP0", sites=["STER", "KONA"], allow_partial=True)
    assert set(pd.read_parquet(f).siteID) == {"STER"}
    assert not list((tmp_path / "DP0").glob("*.part"))


def test_fetch_its_files_keeps_raw_when_a_file_fails(tmp_path, monkeypatch):
    product = "DP1.10081.002"
    monkeypatch.setattr(neon, "RAW_NEON", tmp_path)
    d = tmp_path / product
    d.mkdir()
    pd.DataFrame({"downloadFileUrl": ["https://x/a.csv", "https://x/b.csv"], "collectDate": ["2022-06-07"] * 2,
                  "sequenceCountQF": ["", ""], "dnaSampleID": ["A", "B"]}
                 ).to_parquet(d / f"{neon.ITS_PRODUCTS[product]}.parquet")
    neon.its_taxonomy_path(product).write_bytes(b"old")

    def get(url, **kw):
        if url.endswith("b.csv"):
            raise ConnectionError("boom")
        return types.SimpleNamespace(content=b"dnaSampleID,genus,individualCount\nA,Fusarium,3\n")
    monkeypatch.setattr(http, "get", get)

    with pytest.raises(neon.IncompleteFetch, match="1/2"):
        neon.fetch_its_sample_files(product, workers=1)
    assert neon.its_taxonomy_path(product).read_bytes() == b"old"

    out = neon.fetch_its_sample_files(product, workers=1, allow_partial=True)
    assert list(out.dnaSampleID) == ["A"]
    assert len(pd.read_parquet(neon.its_taxonomy_path(product))) == 1


def test_cached_is_atomic_and_recovers_from_corrupt_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(http, "CACHE", tmp_path)
    calls = []

    def fetch():
        calls.append(1)
        return {"a": 1}
    assert http.cached("ns", "k", fetch) == {"a": 1}
    assert http.cached("ns", "k", fetch) == {"a": 1} and len(calls) == 1
    (entry,) = (tmp_path / "ns").glob("*.json")
    entry.write_text('{"a": ')                       # half-written by an old crash
    assert http.cached("ns", "k", fetch) == {"a": 1} and len(calls) == 2
    assert json.loads(entry.read_text()) == {"a": 1}
    assert not list((tmp_path / "ns").glob("*.part"))

    def bad():
        raise RuntimeError("network")
    with pytest.raises(RuntimeError):
        http.cached("ns", "other", bad)
    assert len(list((tmp_path / "ns").iterdir())) == 1  # nothing left behind


def test_build_its_core_rejects_two_extracts_of_one_core():
    rows = [dict(dnaSampleID=f"STER_001-M-1-1-20160101-GEN-DNA{i}", kingdom="Fungi", genus="Fusarium",
                 individualCount=5) for i in (1, 2)]
    with pytest.raises(ValueError, match="more than one DNA extract"):
        neon.build_its_core(pd.DataFrame(rows))
