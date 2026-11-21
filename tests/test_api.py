"""GUI API on a tiny synthetic dataset: no network, no real data."""
import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cropfit import api, ndvimap, overlay, stac


@pytest.fixture
def client(tmp_path, monkeypatch):
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    monkeypatch.setattr(api, "PROCESSED", proc)
    monkeypatch.setattr(api, "ROOT", tmp_path)
    monkeypatch.setattr(overlay, "OVERLAY_DIR", tmp_path / "overlay")
    pd.DataFrame([dict(plotID="P_001", site="P", lat=39.2, lon=-96.6, half_m=20.0)]).to_parquet(proc / "plot_geometry.parquet")
    d = pd.to_datetime
    pd.DataFrame(dict(plotID="P_001", date=d(["2020-06-01", "2020-05-01", "2020-07-01", "2020-08-01"]),
                      ndvi=[0.71234, 0.3, 0.9, np.nan], clear=[True, True, False, True])).to_parquet(proc / "plot_vi_timeseries.parquet")
    pd.DataFrame([dict(event_id="P_001_20200615", site="P", plotID="P_001", date=d("2020-06-15"),
                       has_metagenome=False, has_its=True, has_chem=True)]).to_parquet(proc / "events.parquet")
    from rasterio.transform import from_origin
    x, y = stac.to_xy(-96.6, 39.2, "EPSG:32614")
    chip = np.full((3, 40, 40), 120, dtype=np.uint8)
    stac.save_chip(tmp_path / "chips" / "P_001_naip_20200620.tif", chip, from_origin(x - 20, y + 20, 1, 1), "EPSG:32614", nodata=0)
    pd.DataFrame([dict(plotID="P_001", source="naip", date=d("2020-06-20"), date_precision="day",
                       chip="chips/P_001_naip_20200620.tif"),
                  dict(plotID="P_001", source="naip", date=d("2021-06-20"), date_precision="day",
                       chip="chips/gone.tif")]).to_parquet(proc / "plot_aerial.parquet")
    # greenness map: NDVI 0.5 everywhere, the west half hidden by cloud
    ndvi = np.full((40, 40), 0.5)
    clear = np.ones((40, 40), dtype=bool)
    clear[:, :20] = False
    stac.save_chip(tmp_path / "maps" / "P_001_s2ndvi_20200601.tif", ndvimap.encode(ndvi, clear),
                   from_origin(x - 200, y + 200, 10, 10), "EPSG:32614", nodata=0)
    pd.DataFrame([dict(plotID="P_001", date=d("2020-06-01"), valid_frac=0.5, chip="maps/P_001_s2ndvi_20200601.tif"),
                  dict(plotID="P_001", date=d("2020-07-01"), valid_frac=0.1, chip="maps/P_001_s2ndvi_20200601.tif")]
                 ).to_parquet(proc / "plot_ndvi_maps.parquet")
    return TestClient(api.create_app())


def test_plots_and_greenness(client):
    assert client.get("/api/plots").json() == [dict(plot_id="P_001", site="P", lat=39.2, lon=-96.6, half_m=20.0)]
    # only clear observations with a value, oldest first, rounded
    assert client.get("/api/plots/P_001/greenness").json() == [dict(date="2020-05-01", ndvi=0.3), dict(date="2020-06-01", ndvi=0.712)]
    assert client.get("/api/plots/NOPE/greenness").status_code == 404


def test_events(client):
    assert client.get("/api/plots/P_001/events").json() == [dict(event_id="P_001_20200615", date="2020-06-15")]
    e = client.get("/api/events/P_001_20200615").json()
    assert e["plot_id"] == "P_001" and e["sampled"] == ["Soil chemistry", "Soil fungi"]
    assert client.get("/api/events/NOPE").status_code == 404


def test_aerial_overlay(client):
    from PIL import Image
    photos = client.get("/api/plots/P_001/aerial").json()
    assert [p["photo_id"] for p in photos] == ["P_001_naip_20200620"]          # the row without a chip file is left out
    (s, w), (n, e) = photos[0]["bounds"]
    assert s < 39.2 < n and w < -96.6 < e                                     # the overlay surrounds the plot centre
    assert (n - s) * 111_320 == pytest.approx(40, rel=0.15)                  # and is about the chip's 40 m tall
    r = client.get(photos[0]["url"])
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content))
    assert img.mode == "RGBA" and img.getpixel((img.width // 2, img.height // 2)) == (120, 120, 120, 255)
    assert client.get("/api/aerial/unknown_photo.png").status_code == 404     # photos are looked up by id, not by path


def test_missing_table_is_reported(client):
    (api.PROCESSED / "events.parquet").unlink()
    r = client.get("/api/events/P_001_20200615")
    assert r.status_code == 503 and "events.parquet" in r.json()["detail"]


def test_ndvi_codes_round_trip():
    v = np.array([-1.0, -0.33, 0.0, 0.5, 1.0, np.nan])
    out = ndvimap.decode(ndvimap.encode(v, np.isfinite(v)))
    assert np.allclose(out[:5], v[:5], atol=0.005) and np.isnan(out[5])


def test_greenness_maps(client):
    from PIL import Image
    maps = client.get("/api/plots/P_001/greenness-maps").json()
    assert [m["date"] for m in maps] == ["2020-06-01"]                         # the mostly clouded one is left out
    (s, w), (n, e) = maps[0]["bounds"]
    assert (n - s) * 111_320 == pytest.approx(400, rel=0.15)
    img = Image.open(io.BytesIO(client.get(maps[0]["url"]).content))
    assert img.getpixel((img.width - 3, img.height // 2)) == (186, 210, 114, 255)   # NDVI 0.5: halfway from yellow to green
    assert img.getpixel((2, img.height // 2))[3] == 0                         # cloud: transparent
    value = lambda lon: client.get(f"/api/greenness-maps/{maps[0]['map_id']}/value", params=dict(lat=39.2, lon=lon)).json()["ndvi"]  # noqa: E731
    assert value(-96.6 + 0.001) == 0.5
    assert value(-96.6 - 0.001) is None                                      # under cloud
    assert value(-96.5) is None                                              # outside the map
    bad = client.get(f"/api/greenness-maps/{maps[0]['map_id']}/value", params=dict(lat=95, lon="nan"))
    assert bad.status_code == 422                                            # not a place on Earth
    assert client.get("/api/greenness-maps/unknown_map.png").status_code == 404


def test_greenness_maps_are_optional(client):
    (api.PROCESSED / "plot_ndvi_maps.parquet").unlink()
    assert client.get("/api/plots/P_001/greenness-maps").json() == []
