import argparse
from pathlib import Path
import sys

import numpy as np
import torch
from torch.utils.data import DataLoader, Subset

if __package__ in (None, ""):
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

from ml.config import (
    DEFAULT_CHECKPOINT_PATH,
    DEFAULT_DATA_DIR,
    FUTURE_FEATURE_NAMES,
    HIST_FEATURE_NAMES,
    STATIC_FEATURE_NAMES,
    TARGET_COLS,
    ModelConfig,
    TrainConfig,
)
from ml.dataset import FeatureScaler, FieldTimeSeriesDataset, split_indices
from ml.model import VegetationLSTM, compute_masked_metrics, masked_smooth_l1_loss


def _select_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _evaluate(
    model: VegetationLSTM,
    loader: DataLoader,
    device: torch.device,
) -> tuple[float, dict[str, float]]:
    model.eval()
    total_loss = 0.0
    total_valid = 0
    preds, targets, masks = [], [], []

    with torch.inference_mode():
        for batch in loader:
            x_hist = batch["x_hist"].to(device)
            x_future = batch["x_future"].to(device)
            x_static = batch["x_static"].to(device)
            last_targets = batch["last_targets"].to(device)
            y_target = batch["y_target"].to(device)
            y_mask = batch["y_mask"].to(device)

            pred = model(x_hist, x_future, x_static, last_targets)
            loss = masked_smooth_l1_loss(pred, y_target, y_mask)
            n_valid = int((y_mask > 0).sum().item())
            if n_valid > 0:
                total_loss += float(loss.item()) * n_valid
                total_valid += n_valid

            preds.append(pred.cpu())
            targets.append(y_target.cpu())
            masks.append(y_mask.cpu())

    avg_loss = total_loss / max(1, total_valid)
    metrics = compute_masked_metrics(
        torch.cat(preds, dim=0),
        torch.cat(targets, dim=0),
        torch.cat(masks, dim=0),
    )
    return avg_loss, metrics


DEFAULT_PIXEL_CHECKPOINT_PATH = Path("ml/checkpoints/vegetation_lstm_pixel.pt")


def train_model(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    checkpoint_path: str | Path | None = None,
    model_cfg: ModelConfig | None = None,
    train_cfg: TrainConfig | None = None,
    mode: str = "field",
    anchor_stride: int | None = None,
) -> dict:
    """
    Trenuje model VegetationLSTM na danych z data_dir i zapisuje najlepszy
    checkpoint (wraz ze skalerem i konfiguracją) do checkpoint_path.
    Obsługuje tryb `field` (średnia po polu) oraz `pixel` (piksele 10 m z komórek H3).
    """
    if mode not in ("field", "pixel"):
        raise ValueError(f"Nieznany tryb treningu: {mode!r} (oczekiwano 'field' lub 'pixel').")

    model_cfg = model_cfg or ModelConfig()
    train_cfg = train_cfg or TrainConfig()

    np.random.seed(train_cfg.seed)
    torch.manual_seed(train_cfg.seed)
    device = _select_device()

    data_dir = Path(data_dir)
    if checkpoint_path is None:
        checkpoint_path = DEFAULT_PIXEL_CHECKPOINT_PATH if mode == "pixel" else DEFAULT_CHECKPOINT_PATH

    eff_stride = anchor_stride if anchor_stride is not None else (3 if mode == "pixel" else 1)
    if mode == "pixel":
        master_parquet = data_dir / "pixel_master.parquet"
        sat_parquet = data_dir / "pixel_satellite_indices.parquet"
        entity_col = "pixel_id"
    else:
        master_parquet = data_dir / "fields_master.parquet"
        sat_parquet = data_dir / "satellite_indices.parquet"
        entity_col = "field_id"

    dataset = FieldTimeSeriesDataset(
        fields_master_parquet=master_parquet,
        satellite_indices_parquet=sat_parquet,
        weather_daily_parquet=data_dir / "weather_daily.parquet",
        history_days=model_cfg.history_days,
        forecast_days=model_cfg.forecast_days,
        target_mode=train_cfg.target_mode,
        max_interp_gap_days=train_cfg.max_interp_gap_days,
        min_hist_obs=train_cfg.min_hist_obs,
        entity_col=entity_col,
        anchor_stride=eff_stride,
    )

    train_idx, val_idx = split_indices(
        dataset,
        val_ratio=train_cfg.val_ratio,
        split_mode=train_cfg.split_mode,
        seed=train_cfg.seed,
    )
    scaler = FeatureScaler().fit_from_dataset(dataset, train_idx)
    dataset.scaler = scaler

    train_loader = DataLoader(Subset(dataset, train_idx), batch_size=train_cfg.batch_size, shuffle=True)
    val_loader = DataLoader(Subset(dataset, val_idx), batch_size=train_cfg.batch_size, shuffle=False)

    model = VegetationLSTM(model_cfg).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=train_cfg.lr, weight_decay=train_cfg.weight_decay
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=3
    )

    ckpt_path = Path(checkpoint_path)
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)

    best_val_loss = float("inf")
    best_metrics: dict[str, float] = {}

    print(
        f"[TRAIN] Start na {device}: tryb={mode}/{train_cfg.split_mode}/{train_cfg.target_mode}, "
        f"stride={eff_stride}, okna train={len(train_idx)}, val={len(val_idx)}, epoki={train_cfg.epochs}"
    )

    for epoch in range(1, train_cfg.epochs + 1):
        model.train()
        train_loss_sum = 0.0
        train_valid = 0

        for batch in train_loader:
            x_hist = batch["x_hist"].to(device)
            x_future = batch["x_future"].to(device)
            x_static = batch["x_static"].to(device)
            last_targets = batch["last_targets"].to(device)
            y_target = batch["y_target"].to(device)
            y_mask = batch["y_mask"].to(device)

            optimizer.zero_grad(set_to_none=True)
            pred = model(x_hist, x_future, x_static, last_targets)
            loss = masked_smooth_l1_loss(pred, y_target, y_mask)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), train_cfg.grad_clip)
            optimizer.step()

            n_valid = int((y_mask > 0).sum().item())
            if n_valid > 0:
                train_loss_sum += float(loss.item()) * n_valid
                train_valid += n_valid

        train_loss = train_loss_sum / max(1, train_valid)
        val_loss, val_metrics = _evaluate(model, val_loader, device)
        scheduler.step(val_loss)

        print(
            f"  Epoka {epoch:02d}/{train_cfg.epochs:02d} | train_loss={train_loss:.5f} | "
            f"val_loss={val_loss:.5f} | NDVI MAE={val_metrics['ndvi_mae']:.4f} | "
            f"NDMI MAE={val_metrics['ndmi_mae']:.4f}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_metrics = val_metrics
            torch.save(
                {
                    "model_state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                    "model_config": model_cfg.to_dict(),
                    "train_config": train_cfg.to_dict(),
                    "scaler": scaler.to_dict(),
                    "val_metrics": best_metrics,
                    "entity_mode": mode,
                    "feature_schema": {
                        "hist": list(HIST_FEATURE_NAMES),
                        "future": list(FUTURE_FEATURE_NAMES),
                        "static": list(STATIC_FEATURE_NAMES),
                        "targets": list(TARGET_COLS),
                    },
                },
                ckpt_path,
            )

    print(f"[TRAIN] Zapisano najlepszy model (val_loss={best_val_loss:.5f}) -> {ckpt_path}")
    return {
        "checkpoint_path": str(ckpt_path),
        "best_val_loss": best_val_loss,
        "val_metrics": best_metrics,
        "n_train": len(train_idx),
        "n_val": len(val_idx),
        "mode": mode,
    }


def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Trening modelu VegetationLSTM (prognoza NDVI i NDMI na 7 dni).")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Folder z tabelami Parquet (fields/pixel, satellite, weather).")
    p.add_argument("--mode", choices=("field", "pixel"), default="field", help="Granularność treningu: średnia po polu lub piksel 10 m.")
    p.add_argument("--checkpoint", default=None, help="Ścieżka zapisu wag modelu (.pt); domyślnie zależna od --mode.")
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=None, help="Rozmiar batcha (domyślnie 32 dla field, 256 dla pixel).")
    p.add_argument("--anchor-stride", type=int, default=None, help="Krok przesuwu okien (domyślnie 1 dla field, 3 dla pixel).")
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--hidden-size", type=int, default=64)
    p.add_argument("--num-layers", type=int, default=2)
    p.add_argument("--split-mode", choices=("field", "time"), default="field")
    p.add_argument("--target-mode", choices=("observed", "interpolated"), default="observed")
    p.add_argument("--demo", action="store_true", help="Wygeneruj syntetyczne dane w data/ml/demo i odpal trening testowy.")
    return p


if __name__ == "__main__":
    args = _build_cli().parse_args()
    data_dir = Path(args.data_dir)
    if args.demo:
        if args.mode == "pixel":
            raise ValueError("Tryb --demo generuje wyłącznie dane na poziomie pól (--mode field).")
        from ml.prepare_dataset import generate_synthetic_demo_dataset

        data_dir = generate_synthetic_demo_dataset(DEFAULT_DATA_DIR / "demo")

    batch_size = args.batch_size if args.batch_size is not None else (256 if args.mode == "pixel" else 32)
    checkpoint_path = (
        args.checkpoint
        if args.checkpoint is not None
        else (DEFAULT_PIXEL_CHECKPOINT_PATH if args.mode == "pixel" else DEFAULT_CHECKPOINT_PATH)
    )

    m_cfg = ModelConfig(hidden_size=args.hidden_size, num_layers=args.num_layers)
    t_cfg = TrainConfig(
        epochs=args.epochs,
        batch_size=batch_size,
        lr=args.lr,
        split_mode=args.split_mode,
        target_mode=args.target_mode,
    )
    train_model(
        data_dir=data_dir,
        checkpoint_path=checkpoint_path,
        model_cfg=m_cfg,
        train_cfg=t_cfg,
        mode=args.mode,
        anchor_stride=args.anchor_stride,
    )
