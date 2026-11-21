import geopandas as gpd
from shapely.geometry import box

from cropfit.csb import _prep
from cropfit.fields import dominant_mukey


def test_dominant_mukey_toy():
    fields = gpd.GeoDataFrame({"unit_id": ["a", "b"]}, geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)], crs="EPSG:5070")
    mu = gpd.GeoDataFrame({"mukey": ["1", "2", "3"]},
                          geometry=[box(0, 0, 3, 10), box(3, 0, 10, 10), box(15, 0, 40, 10)], crs="EPSG:5070")
    r = dominant_mukey(fields, mu).set_index("unit_id")
    assert r.loc["a", "mukey"] == "2" and abs(r.loc["a", "mukey_share"] - 0.7) < 1e-9
    assert r.loc["b", "mukey"] == "3" and r.loc["b", "mukey_share"] == 1.0


def test_crop_t_mapping():
    cols = {f"R{y % 100}": [1] for y in range(2018, 2026)}
    cols["R25"] = [24]
    cols["R24"] = [5]
    cols["CSBID"] = ["123"]
    g = gpd.GeoDataFrame(cols, geometry=[box(0, 0, 100, 100)], crs="EPSG:5070")
    out = _prep(g, "STER")
    r = out.iloc[0]
    assert r["unit_id"] == "CSB_123" and r["unit_type"] == "field"
    assert r["crop_2018"] == "corn"
    assert r["crop_t1"] == "winter_wheat" and r["crop_t2"] == "soybean" and r["crop_t5"] == r["crop_2021"]
