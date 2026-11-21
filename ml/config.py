from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


HISTORY_DAYS = 56  # 8 tygodni obserwacji Sentinel-2 i pogody (koncepcja MVP, sekcja 3)
FORECAST_DAYS = 7  # Horyzont prognozy NDVI i NDMI: 7 dni do przodu

# Kody Copernicus CLMS z bk/assign_crops.py zmapowane na uprawy z MVP
MVP_CROP_CODE_TO_NAME: dict[int, str] = {
    1110: "pszenica",
    1130: "kukurydza",
    1430: "rzepak",
}

CROP_CATEGORIES: tuple[str, ...] = ("pszenica", "kukurydza", "rzepak", "inne")

WEATHER_COLS: tuple[str, ...] = (
    "temp_mean_c",
    "temp_min_c",
    "temp_max_c",
    "precip_sum_mm",
    "sm_l1",
    "sm_l2",
    "sm_l3",
)

STATIC_SOIL_COLS: tuple[str, ...] = (
    "area_ha",
    "sand_pct",
    "silt_pct",
    "clay_pct",
    "ph",
    "om",
    "cec",
    "bulk_density",
    "wilting_point",
    "field_capacity",
)

TARGET_COLS: tuple[str, ...] = ("ndvi", "ndmi")

HIST_FEATURE_NAMES: tuple[str, ...] = (
    "ndvi",
    "ndmi",
    "obs_mask",
    "days_since_obs",
    *WEATHER_COLS,
    "doy_sin",
    "doy_cos",
)  # 13 cech

FUTURE_FEATURE_NAMES: tuple[str, ...] = (
    *WEATHER_COLS,
    "doy_sin",
    "doy_cos",
)  # 9 cech

STATIC_FEATURE_NAMES: tuple[str, ...] = (
    *STATIC_SOIL_COLS,
    "crop_pszenica",
    "crop_kukurydza",
    "crop_rzepak",
    "crop_inne",
)  # 14 cech

# Indeksy cech ciągłych poddawanych standaryzacji (bez masek binarnych, one-hot, doy_sin/cos)
HIST_SCALE_INDICES: tuple[int, ...] = (0, 1, 4, 5, 6, 7, 8, 9, 10)
FUTURE_SCALE_INDICES: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
STATIC_SCALE_INDICES: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)

DEFAULT_DATA_DIR = Path("ml_data")
DEFAULT_CHECKPOINT_PATH = Path("ml/checkpoints/vegetation_lstm.pt")


@dataclass
class ModelConfig:
    hist_input_size: int = len(HIST_FEATURE_NAMES)
    future_input_size: int = len(FUTURE_FEATURE_NAMES)
    static_input_size: int = len(STATIC_FEATURE_NAMES)
    hidden_size: int = 64
    num_layers: int = 2
    dropout: float = 0.15
    history_days: int = HISTORY_DAYS
    forecast_days: int = FORECAST_DAYS

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ModelConfig":
        return cls(**data)


@dataclass
class TrainConfig:
    epochs: int = 30
    batch_size: int = 32
    lr: float = 1e-3
    weight_decay: float = 1e-4
    val_ratio: float = 0.2
    split_mode: Literal["field", "time"] = "field"
    target_mode: Literal["observed", "interpolated"] = "observed"
    max_interp_gap_days: int = 10
    min_hist_obs: int = 2
    seed: int = 42
    grad_clip: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrainConfig":
        return cls(**data)
