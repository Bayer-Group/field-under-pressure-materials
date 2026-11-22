from pathlib import Path
import sys
from typing import Literal

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

if __package__ in (None, ""):
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from ml.config import (
    CROP_CATEGORIES,
    FORECAST_DAYS,
    FUTURE_SCALE_INDICES,
    HIST_SCALE_INDICES,
    HISTORY_DAYS,
    STATIC_SCALE_INDICES,
    STATIC_SOIL_COLS,
    WEATHER_COLS,
)


class FeatureScaler:
    """Standaryzator cech ciągłych w oparciu o czysty NumPy (bez scikit-learn)."""

    def __init__(
        self,
        hist_mean: np.ndarray | None = None,
        hist_std: np.ndarray | None = None,
        future_mean: np.ndarray | None = None,
        future_std: np.ndarray | None = None,
        static_mean: np.ndarray | None = None,
        static_std: np.ndarray | None = None,
    ):
        self.hist_mean = hist_mean
        self.hist_std = hist_std
        self.future_mean = future_mean
        self.future_std = future_std
        self.static_mean = static_mean
        self.static_std = static_std

    @staticmethod
    def _fit_indices(arr: np.ndarray, indices: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
        sub = arr[..., indices].reshape(-1, len(indices))
        mean = sub.mean(axis=0).astype(np.float32)
        std = sub.std(axis=0).astype(np.float32)
        std = np.where(std < 1e-6, 1.0, std).astype(np.float32)
        return mean, std

    def fit_from_dataset(
        self,
        dataset: "FieldTimeSeriesDataset",
        train_indices: list[int],
    ) -> "FeatureScaler":
        if not train_indices:
            raise ValueError("Lista train_indices jest pusta — nie można dopasować skalera.")
        x_hist = np.stack([dataset.samples[i]["x_hist"] for i in train_indices], axis=0)
        x_fut = np.stack([dataset.samples[i]["x_future"] for i in train_indices], axis=0)
        x_stat = np.stack([dataset.samples[i]["x_static"] for i in train_indices], axis=0)

        self.hist_mean, self.hist_std = self._fit_indices(x_hist, HIST_SCALE_INDICES)
        self.future_mean, self.future_std = self._fit_indices(x_fut, FUTURE_SCALE_INDICES)
        self.static_mean, self.static_std = self._fit_indices(x_stat, STATIC_SCALE_INDICES)
        return self

    def transform_hist(self, x: np.ndarray) -> np.ndarray:
        out = x.copy()
        out[..., HIST_SCALE_INDICES] = (out[..., HIST_SCALE_INDICES] - self.hist_mean) / self.hist_std
        return out

    def transform_future(self, x: np.ndarray) -> np.ndarray:
        out = x.copy()
        out[..., FUTURE_SCALE_INDICES] = (out[..., FUTURE_SCALE_INDICES] - self.future_mean) / self.future_std
        return out

    def transform_static(self, x: np.ndarray) -> np.ndarray:
        out = x.copy()
        out[..., STATIC_SCALE_INDICES] = (out[..., STATIC_SCALE_INDICES] - self.static_mean) / self.static_std
        return out

    def to_dict(self) -> dict:
        return {
            "hist_mean": self.hist_mean.tolist(),
            "hist_std": self.hist_std.tolist(),
            "future_mean": self.future_mean.tolist(),
            "future_std": self.future_std.tolist(),
            "static_mean": self.static_mean.tolist(),
            "static_std": self.static_std.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureScaler":
        return cls(
            hist_mean=np.asarray(data["hist_mean"], dtype=np.float32),
            hist_std=np.asarray(data["hist_std"], dtype=np.float32),
            future_mean=np.asarray(data["future_mean"], dtype=np.float32),
            future_std=np.asarray(data["future_std"], dtype=np.float32),
            static_mean=np.asarray(data["static_mean"], dtype=np.float32),
            static_std=np.asarray(data["static_std"], dtype=np.float32),
        )


def encode_static_features(field_row: pd.Series | dict) -> np.ndarray:
    """Tworzy 14-elementowy wektor cech statycznych pola (gleba + one-hot uprawy)."""
    soil_vals = []
    for col in STATIC_SOIL_COLS:
        val = float(field_row.get(col, 0.0) if hasattr(field_row, "get") else field_row[col])
        if col == "area_ha":
            val = float(np.log1p(max(0.0, val)))
        soil_vals.append(val)

    crop_name = str(field_row.get("crop", "inne") if hasattr(field_row, "get") else field_row["crop"]).lower()
    if crop_name not in CROP_CATEGORIES:
        crop_name = "inne"
    crop_oh = [1.0 if crop_name == cat else 0.0 for cat in CROP_CATEGORIES]
    return np.asarray([*soil_vals, *crop_oh], dtype=np.float32)


def _prepare_weather_axis(
    weather_df: pd.DataFrame,
    date_start: str | pd.Timestamp,
    date_end: str | pd.Timestamp,
) -> dict | None:
    """
    Buduje wspólną dzienną oś pogodowo-sezonową [date_start, date_end] dla pola
    (współdzieloną przez pole i wszystkie jego piksele).
    """
    dates = pd.date_range(pd.Timestamp(date_start), pd.Timestamp(date_end), freq="D")
    n = len(dates)
    if n == 0:
        return None

    date_strs = dates.strftime("%Y-%m-%d")
    base = pd.DataFrame({"date": date_strs})

    w_sub = weather_df.drop_duplicates(subset=["date"], keep="last").copy()
    w_sub["date"] = pd.to_datetime(w_sub["date"]).dt.normalize()
    w_merged = base.merge(w_sub[["date", *WEATHER_COLS]], on="date", how="left")
    for col in WEATHER_COLS:
        w_merged[col] = pd.to_numeric(w_merged[col], errors="coerce")
        if col == "precip_sum_mm":
            w_merged[col] = w_merged[col].fillna(0.0)
        else:
            w_merged[col] = w_merged[col].interpolate(method="linear").ffill().bfill()

    if w_merged[list(WEATHER_COLS)].isna().any().any():
        return None

    weather_mat = w_merged[list(WEATHER_COLS)].to_numpy(dtype=np.float32)
    precip_idx = WEATHER_COLS.index("precip_sum_mm")
    weather_mat[:, precip_idx] = np.log1p(np.clip(weather_mat[:, precip_idx], 0.0, None))

    doy = dates.day_of_year.to_numpy(dtype=np.float32)
    doy_sin = np.sin(2.0 * np.pi * doy / 365.25).astype(np.float32)
    doy_cos = np.cos(2.0 * np.pi * doy / 365.25).astype(np.float32)

    future_matrix = np.column_stack(
        [
            weather_mat,
            doy_sin,
            doy_cos,
        ]
    ).astype(np.float32)

    date_strs_arr = date_strs.to_numpy()
    return {
        "date_strs": date_strs_arr,
        "date_to_idx": {str(d): i for i, d in enumerate(date_strs_arr)},
        "weather_mat": weather_mat,
        "doy_sin": doy_sin,
        "doy_cos": doy_cos,
        "future_matrix": future_matrix,
    }


def build_field_daily_series(
    field_row: pd.Series | dict,
    sat_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    date_start: str | pd.Timestamp,
    date_end: str | pd.Timestamp,
    max_interp_gap_days: int = 10,
    precomputed_weather: dict | None = None,
) -> dict[str, np.ndarray] | None:
    """
    Skleja nieregularne obserwacje Sentinel-2 i dzienną pogodę na wspólną,
    ciągłą oś dni kalendarzowych [date_start, date_end] dla jednego pola lub piksela.
    """
    w_axis = (
        precomputed_weather
        if precomputed_weather is not None
        else _prepare_weather_axis(weather_df, date_start=date_start, date_end=date_end)
    )
    if w_axis is None:
        return None

    date_strs_arr = w_axis["date_strs"]
    date_to_idx = w_axis["date_to_idx"]
    n = len(date_strs_arr)
    if n == 0 or sat_df.empty:
        return None

    # 2. Obserwacje Sentinel-2 (nieregularne) zmapowane na indeksy osi dziennej
    s_sub = sat_df.drop_duplicates(subset=["date"], keep="last")
    ndvi_obs = np.full(n, np.nan, dtype=np.float32)
    ndmi_obs = np.full(n, np.nan, dtype=np.float32)

    s_dates = s_sub["date"].astype(str).tolist()
    s_ndvi = pd.to_numeric(s_sub["ndvi"], errors="coerce").to_numpy(dtype=np.float32)
    s_ndmi = pd.to_numeric(s_sub["ndmi"], errors="coerce").to_numpy(dtype=np.float32)
    for d_val, v_ndvi, v_ndmi in zip(s_dates, s_ndvi, s_ndmi):
        idx = date_to_idx.get(d_val)
        if idx is not None:
            ndvi_obs[idx] = v_ndvi
            ndmi_obs[idx] = v_ndmi

    valid_obs = np.isfinite(ndvi_obs) & np.isfinite(ndmi_obs)
    obs_idx = np.flatnonzero(valid_obs)
    if len(obs_idx) == 0:
        return None

    obs_mask = valid_obs.astype(np.float32)
    pos = np.arange(n, dtype=np.int64)

    # days_since_obs (znormalizowane do [0, 1] względem 30 dni) oraz dokładna odległość wstecz/wprzód
    prev_rank = np.searchsorted(obs_idx, pos, side="right") - 1
    has_prev = prev_rank >= 0
    prev_pos = np.where(has_prev, obs_idx[np.maximum(prev_rank, 0)], obs_idx[0])

    exact_prev = np.where(has_prev, (pos - prev_pos).astype(np.float32), 9999.0)
    days_since_norm = (np.where(has_prev, np.minimum(exact_prev, 30.0), 30.0) / 30.0).astype(np.float32)

    next_rank = np.searchsorted(obs_idx, pos, side="left")
    has_next = next_rank < len(obs_idx)
    next_pos = np.where(has_next, obs_idx[np.minimum(next_rank, len(obs_idx) - 1)], obs_idx[-1])
    days_until = np.where(has_next, (next_pos - pos).astype(np.float32), 9999.0)
    nearest_gap = np.minimum(exact_prev, days_until)

    # Przyczynowe wypełnianie dla wejść modelu (x_hist, last_targets) — zero przecieku z przyszłości
    ndvi_causal = ndvi_obs[prev_pos].astype(np.float32)
    ndmi_causal = ndmi_obs[prev_pos].astype(np.float32)

    # Interpolacja liniowa używana WYŁĄCZNIE jako cel (y_target) w trybie target_mode='interpolated'
    pos_f = pos.astype(np.float64)
    obs_f = obs_idx.astype(np.float64)
    ndvi_interp = np.interp(pos_f, obs_f, ndvi_obs[obs_idx].astype(np.float64)).astype(np.float32)
    ndmi_interp = np.interp(pos_f, obs_f, ndmi_obs[obs_idx].astype(np.float64)).astype(np.float32)

    # 3. Sklejanie macierzy cech
    hist_matrix = np.column_stack(
        [
            ndvi_causal,
            ndmi_causal,
            obs_mask,
            days_since_norm,
            w_axis["weather_mat"],
            w_axis["doy_sin"],
            w_axis["doy_cos"],
        ]
    ).astype(np.float32)

    static_vec = encode_static_features(field_row)

    return {
        "dates": date_strs_arr,
        "hist_matrix": hist_matrix,
        "future_matrix": w_axis["future_matrix"],
        "static_vec": static_vec,
        "ndvi_causal": ndvi_causal,
        "ndmi_causal": ndmi_causal,
        "ndvi_interp": ndvi_interp,
        "ndmi_interp": ndmi_interp,
        "ndvi_filled": ndvi_causal,
        "ndmi_filled": ndmi_causal,
        "ndvi_obs": ndvi_obs,
        "ndmi_obs": ndmi_obs,
        "obs_mask": obs_mask,
        "interp_mask": (nearest_gap <= float(max_interp_gap_days)).astype(np.float32),
    }


class FieldTimeSeriesDataset(Dataset):
    """
    Okna przesuwne (56 dni historii -> 7 dni prognozy NDVI i NDMI)
    z maską utraty dla nieregularnych obserwacji Sentinel-2.
    Obsługuje zarówno tryb pól (`entity_col='field_id'`), jak i pikseli 10m (`entity_col='pixel_id'`).
    """

    def __init__(
        self,
        fields_master_parquet: str | Path,
        satellite_indices_parquet: str | Path,
        weather_daily_parquet: str | Path,
        history_days: int = HISTORY_DAYS,
        forecast_days: int = FORECAST_DAYS,
        target_mode: Literal["observed", "interpolated"] = "observed",
        max_interp_gap_days: int = 10,
        min_hist_obs: int = 2,
        scaler: FeatureScaler | None = None,
        entity_col: str = "field_id",
        anchor_stride: int = 1,
    ):
        self.history_days = history_days
        self.forecast_days = forecast_days
        self.scaler = scaler
        self.entity_col = entity_col
        self.samples: list[dict] = []

        fields_df = pd.read_parquet(fields_master_parquet)
        sat_df = pd.read_parquet(satellite_indices_parquet)
        weather_df = pd.read_parquet(weather_daily_parquet)

        if entity_col not in fields_df.columns:
            raise ValueError(f"Brak kolumny '{entity_col}' w {fields_master_parquet}.")
        if entity_col not in sat_df.columns:
            raise ValueError(f"Brak kolumny '{entity_col}' w {satellite_indices_parquet}.")

        fields_df["field_id"] = fields_df["field_id"].astype(str)
        fields_df[entity_col] = fields_df[entity_col].astype(str)
        sat_df["field_id"] = sat_df["field_id"].astype(str)
        sat_df[entity_col] = sat_df[entity_col].astype(str)
        weather_df["field_id"] = weather_df["field_id"].astype(str)

        sat_by_entity = {eid: grp for eid, grp in sat_df.groupby(entity_col)}
        weather_by_field = {fid: grp for fid, grp in weather_df.groupby("field_id")}
        weather_axis_cache: dict[str, dict | None] = {}

        eff_min_hist_obs = max(1, int(min_hist_obs))
        eff_stride = max(1, int(anchor_stride))

        for f_row in fields_df.to_dict("records"):
            fid = f_row["field_id"]
            eid = f_row[entity_col]
            if eid not in sat_by_entity or fid not in weather_by_field:
                continue

            w_sub = weather_by_field[fid]
            if fid not in weather_axis_cache:
                weather_axis_cache[fid] = _prepare_weather_axis(
                    w_sub,
                    date_start=w_sub["date"].min(),
                    date_end=w_sub["date"].max(),
                )
            w_axis = weather_axis_cache[fid]
            if w_axis is None:
                continue

            series = build_field_daily_series(
                f_row,
                sat_by_entity[eid],
                w_sub,
                date_start=w_axis["date_strs"][0],
                date_end=w_axis["date_strs"][-1],
                max_interp_gap_days=max_interp_gap_days,
                precomputed_weather=w_axis,
            )
            if series is None:
                continue

            n = len(series["dates"])
            if n < history_days + forecast_days:
                continue

            for anchor in range(history_days - 1, n - forecast_days, eff_stride):
                h_start = anchor - history_days + 1
                h_end = anchor + 1
                f_start = anchor + 1
                f_end = anchor + 1 + forecast_days

                if int(series["obs_mask"][h_start:h_end].sum()) < eff_min_hist_obs:
                    continue

                if target_mode == "observed":
                    y_ndvi = series["ndvi_obs"][f_start:f_end]
                    y_ndmi = series["ndmi_obs"][f_start:f_end]
                    mask_1d = series["obs_mask"][f_start:f_end]
                elif target_mode == "interpolated":
                    y_ndvi = series["ndvi_interp"][f_start:f_end]
                    y_ndmi = series["ndmi_interp"][f_start:f_end]
                    mask_1d = series["interp_mask"][f_start:f_end]
                else:
                    raise ValueError(f"Nieznany target_mode: {target_mode!r}")

                if float(mask_1d.sum()) <= 0.0:
                    continue

                y_target = np.stack(
                    [
                        np.where(np.isfinite(y_ndvi), y_ndvi, 0.0),
                        np.where(np.isfinite(y_ndmi), y_ndmi, 0.0),
                    ],
                    axis=-1,
                ).astype(np.float32)
                y_mask = np.stack([mask_1d, mask_1d], axis=-1).astype(np.float32)
                last_targets = np.asarray(
                    [series["ndvi_causal"][anchor], series["ndmi_causal"][anchor]],
                    dtype=np.float32,
                )

                self.samples.append(
                    {
                        "field_id": fid,
                        "entity_id": eid,
                        "anchor_date": str(series["dates"][anchor]),
                        "x_hist": series["hist_matrix"][h_start:h_end],
                        "x_future": series["future_matrix"][f_start:f_end],
                        "x_static": series["static_vec"],
                        "last_targets": last_targets,
                        "y_target": y_target,
                        "y_mask": y_mask,
                    }
                )

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        s = self.samples[idx]
        x_hist = s["x_hist"]
        x_future = s["x_future"]
        x_static = s["x_static"]

        if self.scaler is not None:
            x_hist = self.scaler.transform_hist(x_hist)
            x_future = self.scaler.transform_future(x_future)
            x_static = self.scaler.transform_static(x_static)

        return {
            "x_hist": torch.from_numpy(x_hist),
            "x_future": torch.from_numpy(x_future),
            "x_static": torch.from_numpy(x_static),
            "last_targets": torch.from_numpy(s["last_targets"]),
            "y_target": torch.from_numpy(s["y_target"]),
            "y_mask": torch.from_numpy(s["y_mask"]),
        }


def split_indices(
    dataset: FieldTimeSeriesDataset,
    val_ratio: float = 0.2,
    split_mode: Literal["field", "time"] = "field",
    seed: int = 42,
) -> tuple[list[int], list[int]]:
    """
    Dzieli próbki na zbiór treningowy i walidacyjny bez wycieku danych
    (wg nadrzędnych pól `field_id` lub chronologicznie wg daty zakotwiczenia).
    """
    n = len(dataset)
    if n < 2:
        raise ValueError(f"Za mało okien czasowych ({n}) do podziału train/val.")

    if split_mode == "field":
        fields = sorted({s["field_id"] for s in dataset.samples})
        if len(fields) >= 2:
            rng = np.random.default_rng(seed)
            shuffled = list(fields)
            rng.shuffle(shuffled)
            n_val_fields = max(1, min(len(fields) - 1, round(len(fields) * val_ratio)))
            val_fields = set(shuffled[:n_val_fields])
            train_idx = [i for i, s in enumerate(dataset.samples) if s["field_id"] not in val_fields]
            val_idx = [i for i, s in enumerate(dataset.samples) if s["field_id"] in val_fields]
            return train_idx, val_idx
        print("[UWAGA] Tylko 1 pole w zbiorze — przełączam podział walidacyjny na tryb czasowy ('time').")

    # Podział czasowy (bez przecieku w przyszłość)
    ordered = sorted(
        range(n),
        key=lambda i: (dataset.samples[i]["anchor_date"], dataset.samples[i].get("entity_id", dataset.samples[i]["field_id"])),
    )
    cut = max(1, min(n - 1, int(round(n * (1.0 - val_ratio)))))
    return ordered[:cut], ordered[cut:]
