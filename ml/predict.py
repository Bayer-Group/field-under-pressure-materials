import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path
import re
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
import rasterio.mask
import rasterio.transform
import rasterio.warp
from rasterio.vrt import WarpedVRT
import torch

if __package__ in (None, ""):
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from ml.config import DEFAULT_CHECKPOINT_PATH, DEFAULT_DATA_DIR, ModelConfig
from ml.dataset import FeatureScaler, _prepare_weather_axis, build_field_daily_series, encode_static_features
from ml.model import VegetationLSTM
from ml.prepare_dataset import (
    _normalize_tiff_inputs,
    arrays_to_ndvi_ndmi,
    assign_pixels_to_h3_soil,
    detect_scene_bands,
    load_h3_soil_lookup,
)

DEFAULT_PIXEL_CHECKPOINT_PATH = Path("ml/checkpoints/vegetation_lstm_pixel.pt")


def load_trained_model(
    checkpoint_path: str | Path = DEFAULT_CHECKPOINT_PATH,
    device: str | torch.device | None = None,
) -> tuple[VegetationLSTM, FeatureScaler, ModelConfig]:
    """Wczytuje wytrenowany model VegetationLSTM wraz ze skalerem i konfiguracją."""
    dev = torch.device(device) if device is not None else torch.device("cpu")
    ckpt = torch.load(checkpoint_path, map_location=dev, weights_only=True)
    model_cfg = ModelConfig.from_dict(ckpt["model_config"])
    scaler = FeatureScaler.from_dict(ckpt["scaler"])

    model = VegetationLSTM(model_cfg).to(dev)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model, scaler, model_cfg


def predict_field_7days(
    model: VegetationLSTM,
    scaler: FeatureScaler,
    model_cfg: ModelConfig,
    field_profile,
    satellite_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    reference_date: str | date | None = None,
    crop: str | None = None,
    device: str | torch.device | None = None,
) -> dict:
    """
    Prognozuje NDVI i NDMI na 7 dni w przód dla pojedynczego pola.
    Zwraca słownik gotowy do przekazania do kw.soil.evaluate_field_calendar().
    """
    if is_dataclass(field_profile):
        field_dict = asdict(field_profile)
    elif isinstance(field_profile, pd.Series):
        field_dict = field_profile.to_dict()
    else:
        field_dict = dict(field_profile)

    if crop is not None:
        field_dict["crop"] = crop
    elif "crop" not in field_dict or pd.isna(field_dict.get("crop")):
        field_dict["crop"] = "inne"

    field_id = str(field_dict.get("field_id", "field_0"))

    s_sub = (
        satellite_df[satellite_df["field_id"].astype(str) == field_id].copy()
        if "field_id" in satellite_df.columns
        else satellite_df.copy()
    )
    w_sub = (
        weather_df[weather_df["field_id"].astype(str) == field_id].copy()
        if "field_id" in weather_df.columns
        else weather_df.copy()
    )
    if w_sub.empty:
        raise ValueError(f"Brak danych pogodowych dla pola '{field_id}'.")

    if reference_date is None:
        max_w_date = pd.Timestamp(w_sub["date"].max()).date()
        ref_d = max_w_date - timedelta(days=model_cfg.forecast_days)
    elif isinstance(reference_date, date):
        ref_d = reference_date
    else:
        ref_d = date.fromisoformat(str(reference_date).strip())

    # Odfiltruj ewentualne obserwacje z przyszłości względem reference_date (spójność i brak przecieku przy backtestingu)
    if not s_sub.empty and "date" in s_sub.columns:
        s_sub = s_sub[pd.to_datetime(s_sub["date"]).dt.date <= ref_d].copy()

    hist_start = ref_d - timedelta(days=model_cfg.history_days - 1)
    fut_end = ref_d + timedelta(days=model_cfg.forecast_days)

    w_dates = pd.to_datetime(w_sub["date"]).dt.date
    hist_weather_days = int(((w_dates >= hist_start) & (w_dates <= ref_d)).sum())
    if hist_weather_days < model_cfg.history_days:
        print(
            f"[INFO] Pole {field_id}: dostępnych {hist_weather_days}/{model_cfg.history_days} "
            "dni pogody historycznej — brakujące najstarsze dni zostaną uzupełnione przez backfill."
        )

    series = build_field_daily_series(
        field_row=field_dict,
        sat_df=s_sub,
        weather_df=w_sub,
        date_start=hist_start.isoformat(),
        date_end=fut_end.isoformat(),
    )
    if series is None:
        raise ValueError(
            f"Nie udało się zbudować okna predykcji dla pola '{field_id}' "
            "(sprawdź obecność obserwacji Sentinel-2 oraz ciągłość pogody)."
        )

    h = model_cfg.history_days
    f = model_cfg.forecast_days

    x_hist = scaler.transform_hist(series["hist_matrix"][:h])
    x_future = scaler.transform_future(series["future_matrix"][h : h + f])
    x_static = scaler.transform_static(series["static_vec"])
    last_targets = np.asarray(
        [series["ndvi_causal"][h - 1], series["ndmi_causal"][h - 1]],
        dtype=np.float32,
    )

    dev = torch.device(device) if device is not None else next(model.parameters()).device
    with torch.inference_mode():
        pred = model(
            torch.from_numpy(x_hist).unsqueeze(0).to(dev),
            torch.from_numpy(x_future).unsqueeze(0).to(dev),
            torch.from_numpy(x_static).unsqueeze(0).to(dev),
            torch.from_numpy(last_targets).unsqueeze(0).to(dev),
        )[0].cpu().numpy()

    future_dates = [(ref_d + timedelta(days=k)).isoformat() for k in range(1, f + 1)]
    return {
        "field_id": field_id,
        "reference_date": ref_d.isoformat(),
        "dates": future_dates,
        "ndvi_by_date": {d: round(float(pred[i, 0]), 4) for i, d in enumerate(future_dates)},
        "ndmi_by_date": {d: round(float(pred[i, 1]), 4) for i, d in enumerate(future_dates)},
    }


def predict_field_pixels_7days(
    model: VegetationLSTM,
    scaler: FeatureScaler,
    model_cfg: ModelConfig,
    field_id: str,
    fields_geojson: str | Path,
    tiff_inputs: str | Path | list | tuple,
    weather_df: pd.DataFrame,
    field_profile=None,
    soil_h3_parquet: str | Path = Path("data/soil/field_soil_h3_cells.parquet"),
    reference_date: str | date | None = None,
    crop: str | None = None,
    out_dir: str | Path | None = None,
    save_days: list[int] | tuple[int, ...] | None = None,
    id_col: str = "id",
    batch_size: int = 1024,
    device: str | torch.device | None = None,
) -> dict:
    """
    Prognozuje NDVI i NDMI na 7 dni dla KAŻDEGO ważnego piksela 10 m wybranego pola
    i zapisuje wynikowe rastry 2-pasmowe GeoTIFF (`NDVI`, `NDMI`) gotowe dla `ndvi_kmeans.py`.
    Używa wyłącznie obserwacji satelitarnych z okresu [ref_d - 55d, ref_d] (zero przecieku z przyszłości).
    """
    from ml.config import MVP_CROP_CODE_TO_NAME, STATIC_SOIL_COLS
    from ml.prepare_dataset import PIXEL_SOIL_VALUE_COLS

    fid = str(field_id)
    if field_profile is None:
        field_dict: dict = {}
    elif is_dataclass(field_profile):
        field_dict = asdict(field_profile)
    elif isinstance(field_profile, pd.Series):
        field_dict = field_profile.to_dict()
    else:
        field_dict = dict(field_profile)
    field_dict.setdefault("field_id", fid)

    gdf = gpd.read_file(fields_geojson)
    if id_col and id_col in gdf.columns:
        gdf["field_id"] = gdf[id_col].astype(str)
    else:
        gdf["field_id"] = [f"field_{i}" for i in range(len(gdf))]
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    field_gdf = gdf[gdf["field_id"] == fid].copy()
    if field_gdf.empty:
        raise ValueError(f"Nie znaleziono pola '{fid}' w {fields_geojson}.")

    if crop is not None:
        field_dict["crop"] = crop
    elif "crop" not in field_dict or pd.isna(field_dict.get("crop")):
        raw_cc = field_gdf.iloc[0].get("crop_code", np.nan)
        try:
            field_dict["crop"] = MVP_CROP_CODE_TO_NAME.get(int(round(float(raw_cc))), "inne")
        except (TypeError, ValueError):
            field_dict["crop"] = "inne"

    w_sub = (
        weather_df[weather_df["field_id"].astype(str) == fid].copy()
        if "field_id" in weather_df.columns
        else weather_df.copy()
    )
    if w_sub.empty:
        raise ValueError(f"Brak danych pogodowych dla pola '{fid}'.")

    if reference_date is None:
        max_w_date = pd.Timestamp(w_sub["date"].max()).date()
        ref_d = max_w_date - timedelta(days=model_cfg.forecast_days)
    elif isinstance(reference_date, date):
        ref_d = reference_date
    else:
        ref_d = date.fromisoformat(str(reference_date).strip())

    h = model_cfg.history_days
    f = model_cfg.forecast_days
    hist_start = ref_d - timedelta(days=h - 1)
    fut_end = ref_d + timedelta(days=f)

    w_axis = _prepare_weather_axis(w_sub, date_start=hist_start.isoformat(), date_end=fut_end.isoformat())
    if w_axis is None:
        raise ValueError(f"Nie udało się zbudować osi pogodowej dla pola '{fid}' w oknie [{hist_start}, {fut_end}].")

    # Ścisłe filtrowanie scen satelitarnych wyłącznie <= reference_date (zero future leakage)
    all_items = _normalize_tiff_inputs(tiff_inputs)
    filtered_by_date: dict[str, Path] = {}
    for obs_date_str, tif_path in all_items:
        obs_d = date.fromisoformat(obs_date_str)
        if hist_start <= obs_d <= ref_d:
            filtered_by_date[obs_date_str] = tif_path

    scene_items = sorted(filtered_by_date.items(), key=lambda kv: kv[0])
    if not scene_items:
        raise ValueError(f"Brak scen Sentinel-2 dla pola '{fid}' w oknie przyczynowym [{hist_start}, {ref_d}].")

    with rasterio.open(scene_items[0][1]) as ref_src:
        ref_crs = ref_src.crs
        field_utm = field_gdf.to_crs(ref_crs)
        geom = field_utm.geometry.iloc[0]
        if geom is None or geom.is_empty:
            raise ValueError(f"Pusta geometria pola '{fid}'.")
        if "area_ha" not in field_dict or pd.isna(field_dict.get("area_ha")):
            field_dict["area_ha"] = float(geom.area / 10000.0)
        _, band_idx0 = detect_scene_bands(ref_src)
        masked0, crop_transform = rasterio.mask.mask(
            ref_src, [geom], indexes=band_idx0, crop=True, filled=False
        )

    crop_h, crop_w = masked0.shape[1], masked0.shape[2]
    poly_mask = geometry_mask(
        [geom],
        out_shape=(crop_h, crop_w),
        transform=crop_transform,
        invert=True,
    )
    poly_rows, poly_cols = np.nonzero(poly_mask)
    if len(poly_rows) == 0:
        raise ValueError(f"Brak pikseli 10 m wewnątrz poligonu pola '{fid}'.")

    n_poly = len(poly_rows)
    ndvi_hist = np.full((n_poly, h), np.nan, dtype=np.float32)
    ndmi_hist = np.full((n_poly, h), np.nan, dtype=np.float32)
    date_to_idx = w_axis["date_to_idx"]

    for obs_date_str, tif_path in scene_items:
        day_idx = date_to_idx.get(obs_date_str)
        if day_idx is None or day_idx >= h:
            continue
        with rasterio.open(tif_path) as src:
            has_precomputed, band_indexes = detect_scene_bands(src)
            with WarpedVRT(
                src,
                crs=ref_crs,
                transform=crop_transform,
                width=crop_w,
                height=crop_h,
                resampling=Resampling.nearest,
                nodata=np.nan,
            ) as vrt:
                ma = vrt.read(band_indexes, masked=True)
            arr = np.where(ma.mask, np.nan, ma.data.astype(np.float32))
            ndvi_2d, ndmi_2d = arrays_to_ndvi_ndmi(arr, has_precomputed=has_precomputed, nodata=src.nodata)
            ndvi_hist[:, day_idx] = ndvi_2d[poly_rows, poly_cols]
            ndmi_hist[:, day_idx] = ndmi_2d[poly_rows, poly_cols]

    valid_tp = np.isfinite(ndvi_hist) & np.isfinite(ndmi_hist)
    valid_px_mask = valid_tp.sum(axis=1) >= 1
    if not np.any(valid_px_mask):
        raise ValueError(f"Żaden piksel pola '{fid}' nie miał bezchmurnej obserwacji w oknie [{hist_start}, {ref_d}].")

    val_rows = poly_rows[valid_px_mask]
    val_cols = poly_cols[valid_px_mask]
    val_ndvi = ndvi_hist[valid_px_mask]
    val_ndmi = ndmi_hist[valid_px_mask]
    val_valid_tp = valid_tp[valid_px_mask]
    n_px = len(val_rows)

    weather_hist = w_axis["weather_mat"][:h]
    doy_sin_hist = w_axis["doy_sin"][:h]
    doy_cos_hist = w_axis["doy_cos"][:h]
    pos_h = np.arange(h, dtype=np.int64)

    x_hist_all = np.empty((n_px, h, model_cfg.hist_input_size), dtype=np.float32)
    last_targets_all = np.empty((n_px, 2), dtype=np.float32)

    for p in range(n_px):
        obs_idx = np.flatnonzero(val_valid_tp[p])
        prev_rank = np.searchsorted(obs_idx, pos_h, side="right") - 1
        has_prev = prev_rank >= 0
        prev_pos = np.where(has_prev, obs_idx[np.maximum(prev_rank, 0)], obs_idx[0])

        exact_prev = np.where(has_prev, (pos_h - prev_pos).astype(np.float32), 9999.0)
        days_since_norm = (np.where(has_prev, np.minimum(exact_prev, 30.0), 30.0) / 30.0).astype(np.float32)
        ndvi_c = val_ndvi[p, prev_pos].astype(np.float32)
        ndmi_c = val_ndmi[p, prev_pos].astype(np.float32)

        x_hist_all[p, :, 0] = ndvi_c
        x_hist_all[p, :, 1] = ndmi_c
        x_hist_all[p, :, 2] = val_valid_tp[p].astype(np.float32)
        x_hist_all[p, :, 3] = days_since_norm
        x_hist_all[p, :, 4:11] = weather_hist
        x_hist_all[p, :, 11] = doy_sin_hist
        x_hist_all[p, :, 12] = doy_cos_hist
        last_targets_all[p, 0] = ndvi_c[-1]
        last_targets_all[p, 1] = ndmi_c[-1]

    xs_utm, ys_utm = rasterio.transform.xy(crop_transform, val_rows, val_cols, offset="center")
    lons, lats = rasterio.warp.transform(
        ref_crs,
        "EPSG:4326",
        np.asarray(xs_utm, dtype=np.float64),
        np.asarray(ys_utm, dtype=np.float64),
    )
    h3_lookup = load_h3_soil_lookup(soil_h3_parquet)
    assigned_soil = assign_pixels_to_h3_soil(
        field_id=fid,
        pixel_lats=np.asarray(lats, dtype=np.float64),
        pixel_lons=np.asarray(lons, dtype=np.float64),
        h3_lookup=h3_lookup,
        fallback_row=field_dict,
    )

    base_static = encode_static_features(field_dict)
    x_static_all = np.repeat(base_static[None, :], n_px, axis=0)
    for col in PIXEL_SOIL_VALUE_COLS:
        s_idx = STATIC_SOIL_COLS.index(col)
        x_static_all[:, s_idx] = assigned_soil[col]

    x_hist_scaled = scaler.transform_hist(x_hist_all)
    x_static_scaled = scaler.transform_static(x_static_all)
    x_future_scaled = scaler.transform_future(w_axis["future_matrix"][h : h + f])

    dev = torch.device(device) if device is not None else next(model.parameters()).device
    preds_chunks: list[np.ndarray] = []
    with torch.inference_mode():
        x_fut_base = torch.from_numpy(x_future_scaled).to(dev)
        for start_i in range(0, n_px, batch_size):
            end_i = min(n_px, start_i + batch_size)
            cur_bs = end_i - start_i
            p_chunk = model(
                torch.from_numpy(x_hist_scaled[start_i:end_i]).to(dev),
                x_fut_base.unsqueeze(0).expand(cur_bs, -1, -1),
                torch.from_numpy(x_static_scaled[start_i:end_i]).to(dev),
                torch.from_numpy(last_targets_all[start_i:end_i]).to(dev),
            )
            preds_chunks.append(p_chunk.cpu().numpy())

    pred_all = np.concatenate(preds_chunks, axis=0)  # (n_px, f, 2)
    future_dates = [(ref_d + timedelta(days=k)).isoformat() for k in range(1, f + 1)]

    output_tiffs: list[str] = []
    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        safe_fid = re.sub(r"[^A-Za-z0-9_.-]+", "_", fid)
        day_offsets = sorted(set(save_days)) if save_days is not None else list(range(1, f + 1))

        for day_offset in day_offsets:
            if not (1 <= day_offset <= f):
                raise ValueError(f"Nieprawidłowy indeks dnia prognozy: {day_offset} (oczekiwano 1..{f}).")
            d_idx = day_offset - 1
            f_date = future_dates[d_idx]
            tif_out = out_path / f"ndvi_ndmi_forecast_{f_date}_field_{safe_fid}.tif"

            ndvi_grid = np.full((crop_h, crop_w), np.nan, dtype=np.float32)
            ndmi_grid = np.full((crop_h, crop_w), np.nan, dtype=np.float32)
            ndvi_grid[val_rows, val_cols] = pred_all[:, d_idx, 0]
            ndmi_grid[val_rows, val_cols] = pred_all[:, d_idx, 1]

            with rasterio.open(
                tif_out,
                "w",
                driver="GTiff",
                height=crop_h,
                width=crop_w,
                count=2,
                dtype="float32",
                crs=ref_crs,
                transform=crop_transform,
                nodata=np.nan,
                compress="deflate",
            ) as dst:
                dst.write(ndvi_grid, 1)
                dst.write(ndmi_grid, 2)
                dst.set_band_description(1, "NDVI")
                dst.set_band_description(2, "NDMI")
            output_tiffs.append(str(tif_out))

    return {
        "field_id": fid,
        "reference_date": ref_d.isoformat(),
        "dates": future_dates,
        "n_pixels": int(n_px),
        "mean_ndvi_by_date": {d: round(float(pred_all[:, i, 0].mean()), 4) for i, d in enumerate(future_dates)},
        "mean_ndmi_by_date": {d: round(float(pred_all[:, i, 1].mean()), 4) for i, d in enumerate(future_dates)},
        "std_ndvi_by_date": {d: round(float(pred_all[:, i, 0].std()), 4) for i, d in enumerate(future_dates)},
        "output_tiffs": output_tiffs,
    }


def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Prognoza NDVI i NDMI na 7 dni dla wybranego pola lub pikseli 10 m.")
    p.add_argument("--mode", choices=("field", "pixel"), default="field", help="Tryb predykcji: średnia po polu albo rastry 10 m per piksel.")
    p.add_argument("--checkpoint", default=None, help="Ścieżka do checkpointu modelu (.pt); domyślnie zależna od --mode.")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Folder z tabelami Parquet.")
    p.add_argument("--field-id", default=None, help="ID pola (domyślnie pierwsze z fields_master).")
    p.add_argument("--date", dest="reference_date", default=None, help="Data odniesienia YYYY-MM-DD.")
    p.add_argument("--fields-geojson", default="data/fields/lowicki_fields_crops.geojson", help="Granice pól (dla --mode pixel).")
    p.add_argument("--tiff-dir", default="data/satellite/lowicki_2024-03-01_to_2024-10-31", help="Folder ze scenami GeoTIFF (dla --mode pixel).")
    p.add_argument("--soil-h3-parquet", default="data/soil/field_soil_h3_cells.parquet", help="Tabela H3 gleby (dla --mode pixel).")
    p.add_argument("--out-dir", default="data/ml/pixel_forecasts", help="Folder zapisu prognozowanych GeoTIFF-ów (dla --mode pixel).")
    p.add_argument("--save-days", type=int, nargs="*", default=None, help="Opcjonalne numery dni prognozy (1..7) do zapisu jako GeoTIFF.")
    return p


if __name__ == "__main__":
    args = _build_cli().parse_args()
    data_dir = Path(args.data_dir)
    ckpt_path = (
        Path(args.checkpoint)
        if args.checkpoint is not None
        else (DEFAULT_PIXEL_CHECKPOINT_PATH if args.mode == "pixel" else DEFAULT_CHECKPOINT_PATH)
    )
    fields_df = pd.read_parquet(data_dir / "fields_master.parquet")
    weather_df = pd.read_parquet(data_dir / "weather_daily.parquet")

    if args.field_id is not None:
        row = fields_df[fields_df["field_id"].astype(str) == str(args.field_id)].iloc[0]
    else:
        row = fields_df.iloc[0]

    model, scaler, m_cfg = load_trained_model(ckpt_path)

    if args.mode == "pixel":
        result = predict_field_pixels_7days(
            model=model,
            scaler=scaler,
            model_cfg=m_cfg,
            field_id=str(row["field_id"]),
            fields_geojson=args.fields_geojson,
            tiff_inputs=args.tiff_dir,
            weather_df=weather_df,
            field_profile=row,
            soil_h3_parquet=args.soil_h3_parquet,
            reference_date=args.reference_date,
            out_dir=args.out_dir,
            save_days=args.save_days,
        )
        out_df = pd.DataFrame(
            {
                "date": result["dates"],
                "mean_ndvi": [result["mean_ndvi_by_date"][d] for d in result["dates"]],
                "std_ndvi": [result["std_ndvi_by_date"][d] for d in result["dates"]],
                "mean_ndmi": [result["mean_ndmi_by_date"][d] for d in result["dates"]],
            }
        )
        print(
            f"Prognoza 7-dniowa 10m ({result['n_pixels']} pikseli) dla pola {result['field_id']} "
            f"od {result['reference_date']}:"
        )
        print(out_df.to_string(index=False))
        print(f"Zapisano {len(result['output_tiffs'])} plików GeoTIFF w {args.out_dir}")
    else:
        sat_df = pd.read_parquet(data_dir / "satellite_indices.parquet")
        result = predict_field_7days(
            model=model,
            scaler=scaler,
            model_cfg=m_cfg,
            field_profile=row,
            satellite_df=sat_df,
            weather_df=weather_df,
            reference_date=args.reference_date,
        )
        out_df = pd.DataFrame(
            {
                "date": result["dates"],
                "ndvi_forecast": [result["ndvi_by_date"][d] for d in result["dates"]],
                "ndmi_forecast": [result["ndmi_by_date"][d] for d in result["dates"]],
            }
        )
        print(f"Prognoza 7-dniowa dla pola {result['field_id']} od {result['reference_date']}:")
        print(out_df.to_string(index=False))
