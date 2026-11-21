import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import torch

if __package__ in (None, ""):
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from ml.config import DEFAULT_CHECKPOINT_PATH, DEFAULT_DATA_DIR, ModelConfig
from ml.dataset import FeatureScaler, build_field_daily_series
from ml.model import VegetationLSTM


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


def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Prognoza NDVI i NDMI na 7 dni dla wybranego pola.")
    p.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT_PATH), help="Ścieżka do checkpointu modelu (.pt).")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Folder z fields_master/satellite_indices/weather_daily.")
    p.add_argument("--field-id", default=None, help="ID pola (domyślnie pierwsze z fields_master).")
    p.add_argument("--date", dest="reference_date", default=None, help="Data odniesienia YYYY-MM-DD.")
    return p


if __name__ == "__main__":
    args = _build_cli().parse_args()
    data_dir = Path(args.data_dir)
    fields_df = pd.read_parquet(data_dir / "fields_master.parquet")
    sat_df = pd.read_parquet(data_dir / "satellite_indices.parquet")
    weather_df = pd.read_parquet(data_dir / "weather_daily.parquet")

    if args.field_id is not None:
        row = fields_df[fields_df["field_id"].astype(str) == str(args.field_id)].iloc[0]
    else:
        row = fields_df.iloc[0]

    model, scaler, m_cfg = load_trained_model(args.checkpoint)
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
