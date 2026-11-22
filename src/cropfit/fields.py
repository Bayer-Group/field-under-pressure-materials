"""Field-level layer: CSB fields x SSURGO map-unit polygons (dominant mukey) + soil attributes."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt as shp_wkt

from . import ssurgo
from .config import window_wkt

SOIL_COLS = ["mukey", "muname", "compname", "mukey_share", "ph_surface", "clay_pct", "om_pct",
             "caco3_pct", "ec_dsm", "awc100_mm", "drainage_class"]


def window_mupolygons(site: str) -> gpd.GeoDataFrame:
    """SSURGO map-unit polygons intersecting the window (EPSG:5070). Cached via SDA cache (slow, ~4 min cold)."""
    sql = ("SELECT mukey, mupolygongeo.STAsText() AS wkt FROM mupolygon WHERE "
           f"mupolygongeo.STIntersects(geometry::STGeomFromText('{window_wkt(site)}', 4326)) = 1")
    df = ssurgo.sda_query(sql)
    if df.empty:
        return gpd.GeoDataFrame({"mukey": []}, geometry=[], crs="EPSG:5070")
    g = gpd.GeoDataFrame({"mukey": df["mukey"].astype(str)},
                         geometry=[shp_wkt.loads(w) for w in df["wkt"]], crs="EPSG:4326")
    return g.to_crs("EPSG:5070")


def dominant_mukey(fields: gpd.GeoDataFrame, mupolys: gpd.GeoDataFrame, id_col: str = "unit_id") -> pd.DataFrame:
    """Per field: mukey with the largest overlap area, and its share of the field's overlapped area
    (both frames in the same projected CRS). Returns columns [id_col, mukey, mukey_share]."""
    ov = gpd.overlay(fields[[id_col, "geometry"]], mupolys[["mukey", "geometry"]],
                     how="intersection", keep_geom_type=True)
    ov["a"] = ov.geometry.area
    tot = ov.groupby(id_col)["a"].sum().rename("tot")
    per = ov.groupby([id_col, "mukey"], as_index=False)["a"].sum()
    per = per.sort_values([id_col, "a"], ascending=[True, False]).drop_duplicates(id_col)
    per = per.merge(tot, left_on=id_col, right_index=True)
    per["mukey_share"] = per["a"] / per["tot"]
    return per[[id_col, "mukey", "mukey_share"]].reset_index(drop=True)


def add_soil(fields: gpd.GeoDataFrame, site: str) -> gpd.GeoDataFrame:
    """Join dominant mukey + soil attributes (contract columns) onto fields (EPSG:5070)."""
    mp = window_mupolygons(site)
    dom = dominant_mukey(fields, mp)
    props = ssurgo.mukey_properties(dom["mukey"].unique().tolist())
    soil = dom.merge(props, on="mukey", how="left")
    out = fields.merge(soil, on="unit_id", how="left")
    return gpd.GeoDataFrame(out, geometry="geometry", crs=fields.crs)
