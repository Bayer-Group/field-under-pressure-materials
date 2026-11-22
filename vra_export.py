"""
Moduł 1 — Eksport VRA, kalkulator oszczędności PLN, paczki Shapefile RX oraz dump PostGIS.

Samodzielny moduł bez zależności od `scikit-learn` / `joblib`, kompatybilny zarówno
z wcześniejszym schematem stref (`field_id = field_0, ...`), jak i z 2D K-Means
w `ndvi_kmeans.py` (`field_id = 1..N`, niepołączone poligony tej samej strefy,
opcjonalna kolumna `awc_mm_per_m`).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Iterable
import zipfile


def _sanitize_proj_env() -> None:
    """Usuwa zewnętrzne PROJ_LIB/PROJ_DATA, aby koła wheel korzystały z wbudowanego proj.db."""
    prefix = Path(sys.prefix).resolve()
    for var in ("PROJ_LIB", "PROJ_DATA"):
        val = os.environ.get(var)
        if not val:
            continue
        try:
            if not Path(val).resolve().is_relative_to(prefix):
                os.environ.pop(var, None)
        except OSError:
            os.environ.pop(var, None)


_sanitize_proj_env()

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import GeometryCollection, MultiPolygon, Polygon, force_2d, make_valid, to_wkt, unary_union

TARGET_CRS = "EPSG:2180"

ZONE_LABELS_3: dict[int, str] = {
    1: "slaba",
    2: "srednia",
    3: "mocna",
}

FERTILIZER_SPECS: dict[str, dict[str, float | str]] = {
    "saletra_amonowa": {
        "name": "Saletra amonowa 34%",
        "short": "saletra34",
        "n_fraction": 0.34,
        "default_price_pln_t": 1650.0,
    },
    "mocznik_inhibitor": {
        "name": "Mocznik 46% z inhibitorem",
        "short": "mocznik46",
        "n_fraction": 0.46,
        "default_price_pln_t": 2150.0,
    },
    "rsm_32": {
        "name": "RSM 32%",
        "short": "rsm32",
        "n_fraction": 0.32,
        "default_price_pln_t": 1500.0,
    },
    "saletrosan_26": {
        "name": "Saletrosan 26%",
        "short": "saletrosan26",
        "n_fraction": 0.26,
        "default_price_pln_t": 1550.0,
    },
}

STRATEGIES = ("potencjal", "wyrownawcza")
VALID_ID_FORMATS = ("auto", "keep", "field_str", "int")


def _extract_polygonal(geom):
    """Naprawia geometrię i zwraca wyłącznie część poligonalną (Polygon/MultiPolygon) lub None."""
    if geom is None or geom.is_empty:
        return None
    g = force_2d(geom)
    if not g.is_valid:
        try:
            g = make_valid(g)
        except Exception:
            g = g.buffer(0)
    if g is None or g.is_empty:
        return None
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    if isinstance(g, GeometryCollection):
        polys = []
        for sub in g.geoms:
            if isinstance(sub, Polygon) and not sub.is_empty:
                polys.append(sub)
            elif isinstance(sub, MultiPolygon) and not sub.is_empty:
                polys.extend([p for p in sub.geoms if not p.is_empty])
        if not polys:
            return None
        merged = unary_union(polys)
        return merged if isinstance(merged, (Polygon, MultiPolygon)) and not merged.is_empty else None
    return None


def _to_multipolygon(geom) -> MultiPolygon | None:
    """Konwertuje Polygon/MultiPolygon na MultiPolygon dla kolumny GEOMETRY(MultiPolygon, 2180)."""
    g = _extract_polygonal(geom)
    if g is None:
        return None
    if isinstance(g, Polygon):
        return MultiPolygon([g])
    if isinstance(g, MultiPolygon):
        return g
    return None


def _clean_id_scalar(val) -> str:
    """Zamienia wartość ID (np. 1, 1.0, '1', 'field_0') na czysty tekst bez sufiksu '.0'."""
    if val is None or pd.isna(val):
        return ""
    if isinstance(val, (int, np.integer)):
        return str(int(val))
    if isinstance(val, (float, np.floating)):
        if np.isfinite(val) and float(val).is_integer():
            return str(int(val))
        return str(val)
    text = str(val).strip()
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _weighted_mean(values: pd.Series, weights: pd.Series, *, default: float = np.nan) -> float:
    """Liczy średnią ważoną powierzchnią z pominięciem wartości NaN."""
    vals = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    wts = pd.to_numeric(weights, errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(vals) & np.isfinite(wts) & (wts > 0)
    if np.any(mask):
        return float(np.average(vals[mask], weights=wts[mask]))
    finite = vals[np.isfinite(vals)]
    if finite.size > 0:
        return float(np.mean(finite))
    return default


def _default_zone_label(zone_id: int, is_zero_based: bool) -> str:
    """Zwraca etykietę strefy zgodną z kanonem 1..3 (slaba/srednia/mocna)."""
    canonical = zone_id + 1 if is_zero_based else zone_id
    return ZONE_LABELS_3.get(canonical, f"strefa_{zone_id}")


def _build_zone_multipliers(unique_zones: Iterable[int], strategy: str, delta: float) -> dict[int, float]:
    """Buduje globalną mapę mnożników dawek N dla strategii 'potencjal' lub 'wyrownawcza'."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Nieznana strategia '{strategy}'. Dozwolone: {STRATEGIES}.")
    if not (0.0 <= delta < 1.0):
        raise ValueError(f"Parametr delta musi być w przedziale [0.0, 1.0), otrzymano: {delta}.")

    zones_sorted = sorted({int(z) for z in unique_zones})
    if not zones_sorted:
        return {}

    is_zero_based = 0 in zones_sorted and max(zones_sorted) <= 2
    if is_zero_based:
        base_map = {0: 1.0 - delta, 1: 1.0, 2: 1.0 + delta}
    elif set(zones_sorted).issubset({1, 2, 3}):
        base_map = {1: 1.0 - delta, 2: 1.0, 3: 1.0 + delta}
    elif len(zones_sorted) == 1:
        base_map = {zones_sorted[0]: 1.0}
    else:
        scales = np.linspace(1.0 - delta, 1.0 + delta, len(zones_sorted))
        base_map = {z: float(m) for z, m in zip(zones_sorted, scales)}

    if strategy == "wyrownawcza":
        return {z: float(round(2.0 - mult, 6)) for z, mult in base_map.items()}
    return {z: float(round(mult, 6)) for z, mult in base_map.items()}


def normalize_zone_field_ids(
    zones_gdf: gpd.GeoDataFrame,
    fields_geojson: str | Path | None = None,
    id_format: str = "auto",
) -> gpd.GeoDataFrame:
    """
    Normalizuje `field_id` w warstwie stref tak, aby pasowało do kanonicznych ID pól
    (`field_0`, ...) z modułów glebowych i ML lub żądanego formatu.
    """
    if id_format not in VALID_ID_FORMATS:
        raise ValueError(f"Nieznany id_format='{id_format}'. Dozwolone: {VALID_ID_FORMATS}.")
    if zones_gdf.empty:
        out = zones_gdf.copy()
        out["field_id"] = out.get("field_id", pd.Series(dtype=str)).astype(str)
        return out
    if "field_id" not in zones_gdf.columns:
        raise KeyError("Brak kolumny 'field_id' w warstwie stref.")

    out = zones_gdf.copy()
    cleaned = out["field_id"].map(_clean_id_scalar)

    if id_format == "keep":
        out["field_id"] = cleaned.astype(str)
        return out

    if id_format == "int":
        out["field_id"] = cleaned.map(lambda s: re.sub(r"^field_", "", s)).astype(str)
        return out

    non_empty = [s for s in cleaned if s]
    is_numeric = bool(non_empty) and all(re.fullmatch(r"\d+", s) for s in non_empty)
    if not is_numeric:
        out["field_id"] = cleaned.astype(str)
        return out

    if fields_geojson is not None and Path(fields_geojson).exists():
        fields = gpd.read_file(fields_geojson)
        if not fields.empty:
            if "field_id" in fields.columns:
                fields["field_id"] = fields["field_id"].map(_clean_id_scalar)
            else:
                fields["field_id"] = [f"field_{i}" for i in range(len(fields))]
            fields = fields[fields.geometry.notna() & ~fields.geometry.is_empty].copy()
            target_crs = out.crs or TARGET_CRS
            if fields.crs is None:
                fields = fields.set_crs("EPSG:4326")
            if str(fields.crs) != str(target_crs):
                fields = fields.to_crs(target_crs)

            work_crs = out.crs or TARGET_CRS
            pts_geom = out.geometry.representative_point()
            pts = gpd.GeoDataFrame(
                {"_orig_idx": out.index, "_raw_fid": cleaned.values},
                geometry=pts_geom,
                crs=work_crs,
            )

            joined = gpd.sjoin(pts, fields[["field_id", "geometry"]], how="left", predicate="within")
            joined = joined.drop_duplicates(subset=["_orig_idx"])

            missing_mask = joined["field_id"].isna()
            if missing_mask.any():
                nearest = gpd.sjoin_nearest(
                    pts.loc[pts["_orig_idx"].isin(joined.loc[missing_mask, "_orig_idx"])],
                    fields[["field_id", "geometry"]],
                    how="left",
                ).drop_duplicates(subset=["_orig_idx"])
                nearest_map = nearest.set_index("_orig_idx")["field_id"].to_dict()
                joined["field_id"] = joined.apply(
                    lambda r: nearest_map.get(r["_orig_idx"], r["field_id"]) if pd.isna(r["field_id"]) else r["field_id"],
                    axis=1,
                )

            raw_to_canon: dict[str, str] = {}
            for raw_fid, grp in joined.groupby("_raw_fid", sort=False):
                valid_matches = grp["field_id"].dropna().astype(str)
                if not valid_matches.empty:
                    raw_to_canon[str(raw_fid)] = valid_matches.mode().iloc[0]

            row_fallback = joined.set_index("_orig_idx")["field_id"].to_dict()
            mapped = [
                raw_to_canon.get(raw_s)
                or (str(row_fallback[idx]) if pd.notna(row_fallback.get(idx)) else f"field_{raw_s}")
                for idx, raw_s in zip(out.index, cleaned)
            ]
            out["field_id"] = pd.Series(mapped, index=out.index, dtype="object").astype(str)
            return out

    if id_format == "field_str":
        out["field_id"] = cleaned.map(lambda s: f"field_{s}" if s else "").astype(str)
    else:
        out["field_id"] = cleaned.astype(str)
    return out


def load_and_dissolve_zones(
    zones_input: str | Path | gpd.GeoDataFrame,
    target_crs: str = TARGET_CRS,
    fields_geojson: str | Path | None = None,
    id_format: str = "auto",
) -> gpd.GeoDataFrame:
    """
    Wczytuje warstwę stref (.gpkg, .geojson, .parquet lub GeoDataFrame), reprojektuje do EPSG:2180,
    normalizuje `field_id` i scala wielokrotne poligony tej samej pary `(field_id, zone)`.
    """
    if isinstance(zones_input, gpd.GeoDataFrame):
        gdf = zones_input.copy()
    else:
        in_path = Path(zones_input)
        if not in_path.exists():
            raise FileNotFoundError(f"Brak pliku warstwy stref: {in_path}")
        if in_path.suffix.lower() == ".parquet":
            gdf = gpd.read_parquet(in_path)
        else:
            gdf = gpd.read_file(in_path)

    if gdf.empty:
        cols = ["field_id", "zone", "zone_label", "area_ha", "ndvi_z", "geometry"]
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=target_crs)

    if gdf.crs is None:
        gdf = gdf.set_crs(target_crs)
    elif str(gdf.crs) != str(target_crs):
        gdf = gdf.to_crs(target_crs)

    gdf["geometry"] = gdf["geometry"].map(_extract_polygonal)
    gdf = gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty].copy()
    if gdf.empty:
        cols = ["field_id", "zone", "zone_label", "area_ha", "ndvi_z", "geometry"]
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=target_crs)

    gdf = normalize_zone_field_ids(gdf, fields_geojson=fields_geojson, id_format=id_format)
    if "zone" not in gdf.columns:
        raise KeyError("Brak kolumny 'zone' w warstwie stref.")
    gdf["zone"] = pd.to_numeric(gdf["zone"], errors="raise").astype(int)
    gdf["_frag_area_ha"] = gdf.geometry.area / 10_000.0

    has_ndvi = "ndvi_z" in gdf.columns
    has_awc = "awc_mm_per_m" in gdf.columns
    has_label = "zone_label" in gdf.columns
    is_zero_based = 0 in set(gdf["zone"].unique()) and int(gdf["zone"].max()) <= 2

    records: list[dict] = []
    for (fid, zone_id), grp in gdf.groupby(["field_id", "zone"], sort=True):
        dissolved = _extract_polygonal(unary_union(grp["geometry"].tolist()))
        if dissolved is None or dissolved.is_empty:
            continue

        label_val: str | None = None
        if has_label:
            non_null_labels = grp["zone_label"].dropna().astype(str).str.strip()
            non_null_labels = non_null_labels[non_null_labels != ""]
            if not non_null_labels.empty:
                label_val = str(non_null_labels.iloc[0])
        if not label_val:
            label_val = _default_zone_label(int(zone_id), is_zero_based)

        rec: dict = {
            "field_id": str(fid),
            "zone": int(zone_id),
            "zone_label": label_val,
            "area_ha": round(float(dissolved.area) / 10_000.0, 4),
            "ndvi_z": round(_weighted_mean(grp["ndvi_z"], grp["_frag_area_ha"], default=0.0), 4) if has_ndvi else 0.0,
        }
        if has_awc:
            awc_mean = _weighted_mean(grp["awc_mm_per_m"], grp["_frag_area_ha"], default=np.nan)
            rec["awc_mm_per_m"] = round(awc_mean, 1) if np.isfinite(awc_mean) else np.nan
        rec["geometry"] = dissolved
        records.append(rec)

    if not records:
        cols = ["field_id", "zone", "zone_label", "area_ha", "ndvi_z"] + (["awc_mm_per_m"] if has_awc else []) + ["geometry"]
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=target_crs)

    out = gpd.GeoDataFrame(records, geometry="geometry", crs=target_crs)
    return out.sort_values(["field_id", "zone"]).reset_index(drop=True)


def compute_variable_rate_doses(
    zones_gdf: gpd.GeoDataFrame,
    base_n_kg_ha: float = 80.0,
    fertilizer: str = "saletra_amonowa",
    strategy: str = "potencjal",
    delta: float = 0.20,
    price_pln_per_ton: float | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Oblicza zmienne dawki azotu (kg N/ha i kg nawozu/ha), koszty oraz oszczędności PLN względem
    dawki jednolitej (`base_n_kg_ha`) per strefa oraz zagregowane podsumowanie per pole.
    """
    if fertilizer not in FERTILIZER_SPECS:
        raise ValueError(f"Nieznany nawóz '{fertilizer}'. Dozwolone: {list(FERTILIZER_SPECS)}.")
    if base_n_kg_ha < 0:
        raise ValueError(f"Dawka bazowa base_n_kg_ha nie może być ujemna: {base_n_kg_ha}.")

    spec = FERTILIZER_SPECS[fertilizer]
    fert_name = str(spec["name"])
    n_fraction = float(spec["n_fraction"])
    price_t = float(price_pln_per_ton) if price_pln_per_ton is not None else float(spec["default_price_pln_t"])

    out = zones_gdf.copy()
    if out.empty:
        summary_cols = [
            "field_id", "n_zones", "total_area_ha", "fertilizer", "strategy",
            "base_n_kg_ha", "weighted_n_kg_ha", "total_n_kg", "total_product_kg",
            "uniform_product_kg", "savings_product_kg", "total_cost_pln",
            "uniform_cost_pln", "savings_pln", "savings_pct",
        ]
        return out, pd.DataFrame(columns=summary_cols)

    zone_ints = pd.to_numeric(out["zone"], errors="raise").astype(int)
    mult_map = _build_zone_multipliers(zone_ints.unique(), strategy=strategy, delta=delta)
    multipliers = zone_ints.map(mult_map).astype(float)

    area = pd.to_numeric(out["area_ha"], errors="coerce").fillna(0.0).astype(float)
    dose_n_ha = base_n_kg_ha * multipliers
    dose_prod_ha = dose_n_ha / n_fraction
    tot_n = dose_n_ha * area
    tot_prod = dose_prod_ha * area
    cost = (tot_prod / 1000.0) * price_t

    uniform_prod_ha = base_n_kg_ha / n_fraction
    uniform_prod = uniform_prod_ha * area
    uniform_cost = (uniform_prod / 1000.0) * price_t

    sav_prod = uniform_prod - tot_prod
    sav_pln = uniform_cost - cost

    out["fertilizer"] = fertilizer
    out["fertilizer_name"] = fert_name
    out["strategy"] = strategy
    out["base_n_kg_ha"] = round(float(base_n_kg_ha), 2)
    out["dose_multiplier"] = np.round(multipliers, 4)
    out["dose_kg_n_ha"] = np.round(dose_n_ha, 2)
    out["dose_kg_product_ha"] = np.round(dose_prod_ha, 2)
    out["total_n_kg"] = np.round(tot_n, 2)
    out["total_product_kg"] = np.round(tot_prod, 2)
    out["price_pln_per_ton"] = round(price_t, 2)
    out["cost_pln"] = np.round(cost, 2)
    out["uniform_product_kg"] = np.round(uniform_prod, 2)
    out["uniform_cost_pln"] = np.round(uniform_cost, 2)
    out["savings_product_kg"] = np.round(sav_prod, 2)
    out["savings_pln"] = np.round(sav_pln, 2)

    raw_df = pd.DataFrame(
        {
            "field_id": out["field_id"].astype(str),
            "zone": zone_ints,
            "area_ha": area,
            "total_n_kg": tot_n,
            "total_product_kg": tot_prod,
            "uniform_product_kg": uniform_prod,
            "cost_pln": cost,
            "uniform_cost_pln": uniform_cost,
        }
    )

    summary_rows: list[dict] = []
    for fid, grp in raw_df.groupby("field_id", sort=True):
        f_area = float(grp["area_ha"].sum())
        f_n_kg = float(grp["total_n_kg"].sum())
        f_prod = float(grp["total_product_kg"].sum())
        f_uni_prod = float(grp["uniform_product_kg"].sum())
        f_cost = float(grp["cost_pln"].sum())
        f_uni_cost = float(grp["uniform_cost_pln"].sum())
        f_sav_prod = f_uni_prod - f_prod
        f_sav_pln = f_uni_cost - f_cost
        summary_rows.append(
            {
                "field_id": str(fid),
                "n_zones": int(grp["zone"].nunique()),
                "total_area_ha": round(f_area, 4),
                "fertilizer": fertilizer,
                "strategy": strategy,
                "base_n_kg_ha": round(float(base_n_kg_ha), 2),
                "weighted_n_kg_ha": round(f_n_kg / f_area, 2) if f_area > 0 else 0.0,
                "total_n_kg": round(f_n_kg, 2),
                "total_product_kg": round(f_prod, 2),
                "uniform_product_kg": round(f_uni_prod, 2),
                "savings_product_kg": round(f_sav_prod, 2),
                "total_cost_pln": round(f_cost, 2),
                "uniform_cost_pln": round(f_uni_cost, 2),
                "savings_pln": round(f_sav_pln, 2),
                "savings_pct": round(100.0 * f_sav_pln / f_uni_cost, 2) if f_uni_cost > 0 else 0.0,
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    return out, summary_df


def compute_all_scenarios_summary(
    zones_gdf: gpd.GeoDataFrame,
    base_n_kg_ha: float = 80.0,
    delta: float = 0.20,
    prices_pln_per_ton: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Porównuje wszystkie 8 scenariuszy (4 nawozy × 2 strategie) względem dawki jednolitej."""
    rows: list[dict] = []
    for fert_key, spec in FERTILIZER_SPECS.items():
        price_t = (
            float(prices_pln_per_ton[fert_key])
            if prices_pln_per_ton and fert_key in prices_pln_per_ton
            else float(spec["default_price_pln_t"])
        )
        for strat in STRATEGIES:
            _, f_sum = compute_variable_rate_doses(
                zones_gdf=zones_gdf,
                base_n_kg_ha=base_n_kg_ha,
                fertilizer=fert_key,
                strategy=strat,
                delta=delta,
                price_pln_per_ton=price_t,
            )
            tot_prod = float(f_sum["total_product_kg"].sum()) if not f_sum.empty else 0.0
            uni_prod = float(f_sum["uniform_product_kg"].sum()) if not f_sum.empty else 0.0
            tot_cost = float(f_sum["total_cost_pln"].sum()) if not f_sum.empty else 0.0
            uni_cost = float(f_sum["uniform_cost_pln"].sum()) if not f_sum.empty else 0.0
            sav_pln = uni_cost - tot_cost
            rows.append(
                {
                    "fertilizer": fert_key,
                    "fertilizer_name": str(spec["name"]),
                    "strategy": strat,
                    "n_fields": int(len(f_sum)),
                    "total_area_ha": round(float(f_sum["total_area_ha"].sum()), 4) if not f_sum.empty else 0.0,
                    "total_product_kg": round(tot_prod, 2),
                    "uniform_product_kg": round(uni_prod, 2),
                    "savings_product_kg": round(uni_prod - tot_prod, 2),
                    "total_cost_pln": round(tot_cost, 2),
                    "uniform_cost_pln": round(uni_cost, 2),
                    "savings_pln": round(sav_pln, 2),
                    "savings_pct": round(100.0 * sav_pln / uni_cost, 2) if uni_cost > 0 else 0.0,
                }
            )
    return pd.DataFrame(rows)


def export_zones_shapefile(zones_gdf: gpd.GeoDataFrame, out_shp_path: str | Path) -> Path:
    """
    Zapisuje warstwę VRA do formatu ESRI Shapefile w EPSG:2180 z nazwami kolumn DBF <= 10 znaków,
    gotową pod terminale rozsiewaczy (John Deere / Trimble / Topcon).
    """
    if zones_gdf.empty:
        raise ValueError("Brak stref do eksportu Shapefile.")

    gdf = zones_gdf.reset_index(drop=True).copy()
    if gdf.crs is None:
        gdf = gdf.set_crs(TARGET_CRS)
    elif str(gdf.crs) != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)

    data: dict = {
        "field_id": gdf["field_id"].astype(str),
        "zone": pd.to_numeric(gdf["zone"], errors="raise").astype(int),
        "zone_lbl": gdf["zone_label"].astype(str),
        "area_ha": pd.to_numeric(gdf["area_ha"], errors="coerce").round(4),
        "ndvi_z": pd.to_numeric(gdf["ndvi_z"], errors="coerce").round(4),
    }
    if "awc_mm_per_m" in gdf.columns:
        data["awc_mm"] = pd.to_numeric(gdf["awc_mm_per_m"], errors="coerce").round(1)
    data.update(
        {
            "fert": gdf["fertilizer"].astype(str),
            "strategy": gdf["strategy"].astype(str),
            "dose_n_ha": pd.to_numeric(gdf["dose_kg_n_ha"], errors="coerce").round(2),
            "dose_kg_ha": pd.to_numeric(gdf["dose_kg_product_ha"], errors="coerce").round(2),
            "tot_kg": pd.to_numeric(gdf["total_product_kg"], errors="coerce").round(2),
            "cost_pln": pd.to_numeric(gdf["cost_pln"], errors="coerce").round(2),
        }
    )

    shp_gdf = gpd.GeoDataFrame(data, geometry=gdf.geometry.values, crs=TARGET_CRS)
    out_path = Path(out_shp_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shp_gdf.to_file(out_path, driver="ESRI Shapefile", encoding="utf-8")
    return out_path


def export_field_rx_package(zones_gdf: gpd.GeoDataFrame, field_id: str, out_dir: str | Path) -> Path:
    """Pakuje pojedyncze pole VRA jako archiwum .zip zawierające komplet plików Shapefile RX."""
    sub = zones_gdf[zones_gdf["field_id"].astype(str) == str(field_id)].copy()
    if sub.empty:
        raise ValueError(f"Brak stref dla pola '{field_id}' do eksportu paczki RX.")

    fert_key = str(sub["fertilizer"].iloc[0]) if "fertilizer" in sub.columns else "vra"
    fert_short = str(FERTILIZER_SPECS.get(fert_key, {}).get("short", re.sub(r"[^a-z0-9]+", "", fert_key.lower()) or "vra"))
    safe_fid = re.sub(r"[^A-Za-z0-9_-]+", "_", str(field_id)).strip("_") or "field"

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    zip_path = out_root / f"rx_{safe_fid}_{fert_short}.zip"

    with tempfile.TemporaryDirectory() as tmpdir:
        stem = f"{safe_fid}_{fert_short}"
        shp_path = export_zones_shapefile(sub, Path(tmpdir) / f"{stem}.shp")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for sidecar in sorted(shp_path.parent.glob(f"{stem}.*")):
                zf.write(sidecar, arcname=sidecar.name)
    return zip_path


def _sql_lit(val) -> str:
    """Formatuje bezpieczny literał SQL (NULL, liczba lub escaped string)."""
    if val is None or (isinstance(val, (float, np.floating)) and not np.isfinite(val)) or pd.isna(val):
        return "NULL"
    if isinstance(val, (int, np.integer)):
        return str(int(val))
    if isinstance(val, (float, np.floating)):
        return f"{float(val):.6g}"
    text = str(val).replace("'", "''")
    return f"'{text}'"


def export_zones_to_sql(
    zones_gdf: gpd.GeoDataFrame,
    summary_df: pd.DataFrame,
    sql_path: str | Path,
) -> Path:
    """
    Generuje idempotentny dump PostGIS (CREATE EXTENSION postgis, CREATE TABLE IF NOT EXISTS,
    indeks GIST oraz INSERT ... ON CONFLICT DO UPDATE) dla `public.field_zones` i `public.field_zone_summary`.
    """
    gdf = zones_gdf.reset_index(drop=True).copy()
    if not gdf.empty:
        if gdf.crs is None:
            gdf = gdf.set_crs(TARGET_CRS)
        elif str(gdf.crs) != TARGET_CRS:
            gdf = gdf.to_crs(TARGET_CRS)

    lines: list[str] = [
        "-- Moduł 1: Dump PostGIS stref VRA i podsumowań kosztów/oszczędności nawożenia",
        "CREATE EXTENSION IF NOT EXISTS postgis;",
        "",
        "CREATE TABLE IF NOT EXISTS public.field_zones (",
        "    field_id TEXT NOT NULL,",
        "    zone INTEGER NOT NULL,",
        "    zone_label TEXT,",
        "    area_ha DOUBLE PRECISION NOT NULL,",
        "    ndvi_z DOUBLE PRECISION,",
        "    awc_mm_per_m DOUBLE PRECISION,",
        "    fertilizer TEXT,",
        "    fertilizer_name TEXT,",
        "    strategy TEXT,",
        "    base_n_kg_ha DOUBLE PRECISION,",
        "    dose_multiplier DOUBLE PRECISION,",
        "    dose_kg_n_ha DOUBLE PRECISION,",
        "    dose_kg_product_ha DOUBLE PRECISION,",
        "    total_n_kg DOUBLE PRECISION,",
        "    total_product_kg DOUBLE PRECISION,",
        "    price_pln_per_ton DOUBLE PRECISION,",
        "    cost_pln DOUBLE PRECISION,",
        "    uniform_product_kg DOUBLE PRECISION,",
        "    uniform_cost_pln DOUBLE PRECISION,",
        "    savings_product_kg DOUBLE PRECISION,",
        "    savings_pln DOUBLE PRECISION,",
        "    geom GEOMETRY(MultiPolygon, 2180) NOT NULL,",
        "    PRIMARY KEY (field_id, zone)",
        ");",
        "",
        "CREATE INDEX IF NOT EXISTS idx_field_zones_geom ON public.field_zones USING GIST (geom);",
        "",
    ]

    zone_cols = [
        "field_id", "zone", "zone_label", "area_ha", "ndvi_z", "awc_mm_per_m",
        "fertilizer", "fertilizer_name", "strategy", "base_n_kg_ha", "dose_multiplier",
        "dose_kg_n_ha", "dose_kg_product_ha", "total_n_kg", "total_product_kg",
        "price_pln_per_ton", "cost_pln", "uniform_product_kg", "uniform_cost_pln",
        "savings_product_kg", "savings_pln",
    ]
    zone_update_cols = [c for c in zone_cols if c not in ("field_id", "zone")] + ["geom"]
    zone_update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in zone_update_cols)
    zone_insert_header = ", ".join(zone_cols + ["geom"])

    for _, row in gdf.iterrows():
        mp = _to_multipolygon(row.geometry)
        if mp is None or mp.is_empty:
            continue
        wkt = to_wkt(mp, rounding_precision=2)
        vals = [_sql_lit(row[c] if c in row.index else None) for c in zone_cols]
        vals.append(f"ST_SetSRID(ST_GeomFromText('{wkt}', 2180), 2180)")
        lines.append(
            f"INSERT INTO public.field_zones ({zone_insert_header}) VALUES ({', '.join(vals)}) "
            f"ON CONFLICT (field_id, zone) DO UPDATE SET {zone_update_sql};"
        )

    lines.extend(
        [
            "",
            "CREATE TABLE IF NOT EXISTS public.field_zone_summary (",
            "    field_id TEXT PRIMARY KEY,",
            "    n_zones INTEGER NOT NULL,",
            "    total_area_ha DOUBLE PRECISION NOT NULL,",
            "    fertilizer TEXT,",
            "    strategy TEXT,",
            "    base_n_kg_ha DOUBLE PRECISION,",
            "    weighted_n_kg_ha DOUBLE PRECISION,",
            "    total_n_kg DOUBLE PRECISION,",
            "    total_product_kg DOUBLE PRECISION,",
            "    uniform_product_kg DOUBLE PRECISION,",
            "    savings_product_kg DOUBLE PRECISION,",
            "    total_cost_pln DOUBLE PRECISION,",
            "    uniform_cost_pln DOUBLE PRECISION,",
            "    savings_pln DOUBLE PRECISION,",
            "    savings_pct DOUBLE PRECISION",
            ");",
            "",
        ]
    )

    sum_cols = [
        "field_id", "n_zones", "total_area_ha", "fertilizer", "strategy", "base_n_kg_ha",
        "weighted_n_kg_ha", "total_n_kg", "total_product_kg", "uniform_product_kg",
        "savings_product_kg", "total_cost_pln", "uniform_cost_pln", "savings_pln", "savings_pct",
    ]
    sum_update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in sum_cols if c != "field_id")
    sum_header = ", ".join(sum_cols)

    for _, row in summary_df.iterrows():
        vals = [_sql_lit(row[c] if c in row.index else None) for c in sum_cols]
        lines.append(
            f"INSERT INTO public.field_zone_summary ({sum_header}) VALUES ({', '.join(vals)}) "
            f"ON CONFLICT (field_id) DO UPDATE SET {sum_update_sql};"
        )

    out_path = Path(sql_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _resolve_zones_input(zones_input: str | Path | None, out_dir: Path) -> Path:
    if zones_input is not None:
        return Path(zones_input)
    for candidate in (out_dir / "field_zones.gpkg", out_dir / "field_zones.geojson"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Nie znaleziono warstwy stref (ani field_zones.gpkg, ani field_zones.geojson) w {out_dir}."
    )


def run_vra_export(
    zones_input: str | Path | None = None,
    out_dir: str | Path = Path("data/zones"),
    fields_geojson: str | Path | None = Path("data/fields/lowicki_fields_crops.geojson"),
    id_format: str = "auto",
    fertilizer: str = "saletra_amonowa",
    strategy: str = "potencjal",
    base_n_kg_ha: float = 80.0,
    delta: float = 0.20,
    price_pln_per_ton: float | None = None,
    rx_fields: list[str] | str | None = None,
    update_zones_geojson: bool = False,
    run_zone_soil: bool = False,
    soil_cache_dir: str | Path = Path("data/soil/aws_cache"),
    voivodeships: list[str] | tuple[str, ...] | None = None,
    soil_sql_path: str | Path = Path("data/soil/field_zone_soil_profiles.sql"),
) -> dict:
    """
    Pełny pipeline post-klasteryzacji Modułu 1:
    normalizacja ID -> dissolve stref -> dawki VRA & oszczędności PLN ->
    porównanie 8 scenariuszy -> ESRI Shapefile + paczki RX .zip -> dump PostGIS SQL ->
    opcjonalnie offline SoilGrids per strefa + SQL.
    """
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    resolved_input = _resolve_zones_input(zones_input, out_root)

    dissolved_gdf = load_and_dissolve_zones(
        zones_input=resolved_input,
        target_crs=TARGET_CRS,
        fields_geojson=fields_geojson,
        id_format=id_format,
    )
    vra_gdf, summary_df = compute_variable_rate_doses(
        zones_gdf=dissolved_gdf,
        base_n_kg_ha=base_n_kg_ha,
        fertilizer=fertilizer,
        strategy=strategy,
        delta=delta,
        price_pln_per_ton=price_pln_per_ton,
    )
    scenarios_df = compute_all_scenarios_summary(
        zones_gdf=dissolved_gdf,
        base_n_kg_ha=base_n_kg_ha,
        delta=delta,
        prices_pln_per_ton={fertilizer: price_pln_per_ton} if price_pln_per_ton is not None else None,
    )

    vra_geojson = out_root / "field_zones_vra.geojson"
    vra_parquet = out_root / "field_zones_vra.parquet"
    summary_parquet = out_root / "field_zones_summary.parquet"
    summary_json = out_root / "field_zones_summary.json"
    scenarios_json = out_root / "field_zones_scenarios.json"
    all_shp_path = out_root / "shapefiles/all_fields_vra_zones.shp"
    sql_dump_path = out_root / "field_zones_dump.sql"
    rx_dir = out_root / "rx_packages"

    vra_gdf.to_file(vra_geojson, driver="GeoJSON")
    vra_gdf.to_parquet(vra_parquet, index=False)
    if update_zones_geojson:
        vra_gdf.to_file(out_root / "field_zones.geojson", driver="GeoJSON")

    summary_df.to_parquet(summary_parquet, index=False)
    summary_df.to_json(summary_json, orient="records", force_ascii=False, indent=2)
    scenarios_df.to_json(scenarios_json, orient="records", force_ascii=False, indent=2)

    export_zones_shapefile(vra_gdf, all_shp_path)

    if rx_fields == "ALL":
        target_rx_fields = summary_df["field_id"].astype(str).tolist()
    elif isinstance(rx_fields, str):
        target_rx_fields = [s.strip() for s in rx_fields.split(",") if s.strip()]
    elif rx_fields is not None:
        target_rx_fields = [str(f) for f in rx_fields]
    else:
        target_rx_fields = (
            summary_df.sort_values("total_area_ha", ascending=False)["field_id"].head(3).astype(str).tolist()
            if not summary_df.empty
            else []
        )

    rx_paths: list[Path] = []
    for fid in target_rx_fields:
        rx_paths.append(export_field_rx_package(vra_gdf, fid, rx_dir))

    export_zones_to_sql(vra_gdf, summary_df, sql_dump_path)

    soil_parquet_out: Path | None = None
    soil_sql_out: Path | None = None
    if run_zone_soil and not vra_gdf.empty:
        from kw import soil_aws

        soil_df = soil_aws.prepare_zone_soil_profiles(
            zones_input=vra_geojson,
            cache_dir=Path(soil_cache_dir),
            voivodeships=voivodeships,
            crops_geojson=fields_geojson,
        )
        soil_parquet_out = Path(soil_aws.DEFAULT_ZONE_PROFILES_PARQUET)
        if not soil_df.empty:
            soil_sql_out = soil_aws.export_soil_profiles_to_sql(
                soil_df,
                table_name="field_zone_soil_profiles",
                sql_path=soil_sql_path,
            )

    total_area = float(summary_df["total_area_ha"].sum()) if not summary_df.empty else 0.0
    total_n = float(summary_df["total_n_kg"].sum()) if not summary_df.empty else 0.0
    total_prod = float(summary_df["total_product_kg"].sum()) if not summary_df.empty else 0.0
    total_cost = float(summary_df["total_cost_pln"].sum()) if not summary_df.empty else 0.0
    total_sav_pln = float(summary_df["savings_pln"].sum()) if not summary_df.empty else 0.0
    best_row = scenarios_df.sort_values("savings_pln", ascending=False).iloc[0] if not scenarios_df.empty else None

    print(
        f"[VRA EXPORT] Strefy: {len(vra_gdf)} | Pola: {len(summary_df)} | "
        f"Powierzchnia: {total_area:.2f} ha | Nawóz: {fertilizer} ({strategy}, ±{int(round(delta * 100))}%)"
    )
    print(
        f"[VRA EXPORT] Suma N: {total_n:.1f} kg | Nawóz: {total_prod:.1f} kg | "
        f"Koszt: {total_cost:.2f} PLN | Bilans vs dawka jednolita: {total_sav_pln:+.2f} PLN"
    )
    if best_row is not None:
        print(
            f"[VRA EXPORT] Najkorzystniejszy scenariusz z 8: "
            f"{best_row['fertilizer']} / {best_row['strategy']} "
            f"({best_row['savings_pln']:+.2f} PLN, {best_row['savings_pct']:+.2f}%)"
        )

    return {
        "zones_gdf": vra_gdf,
        "summary_df": summary_df,
        "scenarios_df": scenarios_df,
        "vra_geojson": vra_geojson,
        "vra_parquet": vra_parquet,
        "summary_parquet": summary_parquet,
        "summary_json": summary_json,
        "scenarios_json": scenarios_json,
        "shapefile": all_shp_path,
        "rx_packages": rx_paths,
        "sql_dump": sql_dump_path,
        "soil_parquet": soil_parquet_out,
        "soil_sql": soil_sql_out,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Moduł 1 — Eksport VRA (dawki N, oszczędności PLN, Shapefile RX, PostGIS SQL)."
    )
    parser.add_argument("--zones-input", type=Path, default=None, help="Plik wejściowy stref (.gpkg lub .geojson).")
    parser.add_argument("--out-dir", type=Path, default=Path("data/zones"), help="Katalog wyjściowy (domyślnie data/zones).")
    parser.add_argument(
        "--fields-geojson",
        type=Path,
        default=Path("data/fields/lowicki_fields_crops.geojson"),
        help="Granice pól do wyrównania field_id (spatial join).",
    )
    parser.add_argument("--id-format", choices=VALID_ID_FORMATS, default="auto", help="Format normalizacji field_id.")
    parser.add_argument("--fertilizer", choices=list(FERTILIZER_SPECS), default="saletra_amonowa")
    parser.add_argument("--strategy", choices=list(STRATEGIES), default="potencjal")
    parser.add_argument("--base-n", type=float, default=80.0, help="Dawka bazowa azotu [kg N/ha].")
    parser.add_argument("--delta", type=float, default=0.20, help="Odchylenie VRA (domyślnie 0.20 = ±20%%).")
    parser.add_argument("--price-pln-t", type=float, default=None, help="Opcjonalna własna cena nawozu [PLN/t].")
    parser.add_argument(
        "--rx-fields",
        nargs="*",
        default=None,
        help="Lista field_id pod paczki RX .zip lub 'ALL' dla wszystkich pól (domyślnie top 3 wg powierzchni).",
    )
    parser.add_argument("--update-zones-geojson", action="store_true", help="Nadpisz out_dir/field_zones.geojson wersją VRA.")
    parser.add_argument("--run-zone-soil", action="store_true", help="Policz profile SoilGrids per strefa z cache AWS i zapisz SQL.")
    parser.add_argument("--soil-cache-dir", type=Path, default=Path("data/soil/aws_cache"))
    parser.add_argument("--voivodeships", nargs="*", default=None)
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    rx_arg: list[str] | str | None
    if args.rx_fields is None:
        rx_arg = None
    elif len(args.rx_fields) == 1 and args.rx_fields[0].upper() == "ALL":
        rx_arg = "ALL"
    else:
        rx_arg = args.rx_fields

    run_vra_export(
        zones_input=args.zones_input,
        out_dir=args.out_dir,
        fields_geojson=args.fields_geojson,
        id_format=args.id_format,
        fertilizer=args.fertilizer,
        strategy=args.strategy,
        base_n_kg_ha=args.base_n,
        delta=args.delta,
        price_pln_per_ton=args.price_pln_t,
        rx_fields=rx_arg,
        update_zones_geojson=args.update_zones_geojson,
        run_zone_soil=args.run_zone_soil,
        soil_cache_dir=args.soil_cache_dir,
        voivodeships=args.voivodeships,
    )
