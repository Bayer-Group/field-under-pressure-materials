"""Static baker on the synthetic dataset of test_api.py (crop risk etc. are skipped: no tables for them there)."""
import base64
import json

import numpy as np
import pytest

from cropfit import api, bake, ndvimap
from test_api import client  # noqa: F401  (fixture)


def test_path_to_key():
    assert bake.path_to_key("/plots") == "__plots"
    assert bake.path_to_key("/microbiome/S1?rank=genus") == "__microbiome__S1~rank-genus"
    assert bake.path_to_key("/a?x=1&y=2") == "__a~x-1+y-2"
    assert bake.path_to_key("/plots/STER_006/greenness") == "__plots__STER_006__greenness"
    assert bake.enc("a b/c") == "a%20b%2Fc"


def test_rewrite_urls():
    obj = [{"url": "/api/aerial/P_1.png", "n": 1, "x": ["/api/greenness-maps/M_2.png", "/api/other.png", "/api/aerial/x.jpg"]}]
    assert bake.rewrite_urls(obj) == [{"url": "img/aerial/P_1.png", "n": 1,
                                       "x": ["img/ndvi/M_2.png", "/api/other.png", "/api/aerial/x.jpg"]}]
    with pytest.raises(ValueError):
        bake.rewrite_urls("/api/aerial/a/b.png")


def _load(p):
    txt = p.read_text(encoding="utf-8")
    assert txt.startswith("window.__BAKED__=window.__BAKED__||{};window.__BAKED__[") and txt.endswith(";")
    path, body = txt[len("window.__BAKED__=window.__BAKED__||{};window.__BAKED__["):-1].split("]=", 1)
    return json.loads(path), json.loads(body)


def test_bake_small(client, tmp_path):  # noqa: F811
    out = tmp_path / "static"
    (out).mkdir()
    (out / "index.html").write_text("keep")
    m = bake.bake(client, out, workers=2, log=lambda *_: None)
    assert (out / "index.html").read_text() == "keep"
    path, body = _load(out / "data" / "__plots.js")
    assert path == "/plots" and body[0]["plot_id"] == "P_001"
    _, aerial = _load(out / "data" / "__plots__P_001__aerial.js")
    assert aerial[0]["url"] == "img/aerial/P_001_naip_20200620.png"
    assert (out / "img" / "aerial" / "P_001_naip_20200620.png").read_bytes()[:4] == b"\x89PNG"
    _, maps = _load(out / "data" / "__plots__P_001__greenness-maps.js")
    assert maps[0]["url"].startswith("img/ndvi/") and (out / maps[0]["url"]).exists()
    _, grid = _load(out / "data" / f"__greenness-maps__{maps[0]['map_id']}__grid.js")
    codes = np.frombuffer(base64.b64decode(grid["codes"]), np.uint8).reshape(grid["height"], grid["width"])
    assert (grid["s"], grid["w"], grid["n"], grid["e"]) == tuple(maps[0]["bounds"][0] + maps[0]["bounds"][1])
    assert set(np.unique(codes)) <= {0, 151}          # cloud / NDVI 0.5
    _, dec = _load(out / "data" / "__ndvi-decode.js")
    assert dec["values"][0] is None and dec["values"][151] == 0.5 and len(dec["values"]) == 256
    assert json.loads((out / "data" / "manifest.json").read_text())["counts"]["plots"] == 1
    assert m["counts"]["event"] == 1
