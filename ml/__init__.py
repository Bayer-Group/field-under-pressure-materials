from .config import (
    CROP_CATEGORIES,
    DEFAULT_CHECKPOINT_PATH,
    DEFAULT_DATA_DIR,
    FORECAST_DAYS,
    FUTURE_FEATURE_NAMES,
    HIST_FEATURE_NAMES,
    HISTORY_DAYS,
    MVP_CROP_CODE_TO_NAME,
    STATIC_FEATURE_NAMES,
    STATIC_SOIL_COLS,
    TARGET_COLS,
    WEATHER_COLS,
    ModelConfig,
    TrainConfig,
)
from .dataset import FeatureScaler, FieldTimeSeriesDataset, split_indices
from .model import VegetationLSTM, compute_masked_metrics, masked_smooth_l1_loss


def __getattr__(name: str):
    if name in ("load_trained_model", "predict_field_7days"):
        from . import predict

        return getattr(predict, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CROP_CATEGORIES",
    "DEFAULT_CHECKPOINT_PATH",
    "DEFAULT_DATA_DIR",
    "FORECAST_DAYS",
    "FUTURE_FEATURE_NAMES",
    "HIST_FEATURE_NAMES",
    "HISTORY_DAYS",
    "MVP_CROP_CODE_TO_NAME",
    "STATIC_FEATURE_NAMES",
    "STATIC_SOIL_COLS",
    "TARGET_COLS",
    "WEATHER_COLS",
    "ModelConfig",
    "TrainConfig",
    "FeatureScaler",
    "FieldTimeSeriesDataset",
    "split_indices",
    "VegetationLSTM",
    "compute_masked_metrics",
    "masked_smooth_l1_loss",
    "load_trained_model",
    "predict_field_7days",
]
