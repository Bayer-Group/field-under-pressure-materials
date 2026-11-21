import torch
import torch.nn as nn
import torch.nn.functional as F

from .config import ModelConfig


class VegetationLSTM(nn.Module):
    """
    Model Encoder-Decoder LSTM w PyTorch prognozujący NDVI i NDMI na 7 dni w przód
    na podstawie 8 tygodni historii (Sentinel-2 + pogoda), 7-dniowej prognozy pogody
    oraz statycznych cech gleby i uprawy.
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config

        self.static_encoder = nn.Sequential(
            nn.Linear(config.static_input_size, config.hidden_size),
            nn.ReLU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_size, config.hidden_size),
            nn.ReLU(),
        )
        self.h0_proj = nn.Linear(config.hidden_size, config.num_layers * config.hidden_size)
        self.c0_proj = nn.Linear(config.hidden_size, config.num_layers * config.hidden_size)

        lstm_dropout = config.dropout if config.num_layers > 1 else 0.0
        self.encoder = nn.LSTM(
            input_size=config.hist_input_size,
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            batch_first=True,
            dropout=lstm_dropout,
        )
        self.decoder = nn.LSTM(
            input_size=config.future_input_size + config.hidden_size,
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            batch_first=True,
            dropout=lstm_dropout,
        )
        mid = max(16, config.hidden_size // 2)
        self.head = nn.Sequential(
            nn.Linear(config.hidden_size, mid),
            nn.ReLU(),
            nn.Linear(mid, 2),
        )

    def forward(
        self,
        x_hist: torch.Tensor,
        x_future: torch.Tensor,
        x_static: torch.Tensor,
        last_targets: torch.Tensor,
    ) -> torch.Tensor:
        batch_size = x_hist.size(0)
        static_emb = self.static_encoder(x_static)

        h0 = (
            torch.tanh(self.h0_proj(static_emb))
            .view(batch_size, self.config.num_layers, self.config.hidden_size)
            .transpose(0, 1)
            .contiguous()
        )
        c0 = (
            torch.tanh(self.c0_proj(static_emb))
            .view(batch_size, self.config.num_layers, self.config.hidden_size)
            .transpose(0, 1)
            .contiguous()
        )

        _, (h_n, c_n) = self.encoder(x_hist, (h0, c0))

        static_seq = static_emb.unsqueeze(1).expand(-1, x_future.size(1), -1)
        dec_in = torch.cat([x_future, static_seq], dim=-1)
        dec_out, _ = self.decoder(dec_in, (h_n, c_n))

        delta = self.head(dec_out)
        return torch.clamp(last_targets.unsqueeze(1) + delta, -1.0, 1.0)


def masked_smooth_l1_loss(
    pred: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
    beta: float = 0.05,
) -> torch.Tensor:
    """Strata SmoothL1 liczona wyłącznie dla dni z ważną obserwacją (mask > 0)."""
    valid = mask > 0
    if not torch.any(valid):
        return pred.sum() * 0.0
    return F.smooth_l1_loss(pred[valid], target[valid], beta=beta, reduction="mean")


def compute_masked_metrics(
    pred: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> dict[str, float]:
    """Zwraca MAE i RMSE osobno dla NDVI i NDMI na zamaskowanych punktach."""
    metrics: dict[str, float] = {}
    for ch, name in enumerate(("ndvi", "ndmi")):
        valid = mask[:, :, ch] > 0
        if not torch.any(valid):
            metrics[f"{name}_mae"] = float("nan")
            metrics[f"{name}_rmse"] = float("nan")
        else:
            diff = pred[:, :, ch][valid] - target[:, :, ch][valid]
            metrics[f"{name}_mae"] = float(torch.mean(torch.abs(diff)).item())
            metrics[f"{name}_rmse"] = float(torch.sqrt(torch.mean(diff * diff)).item())
    metrics["valid_points"] = int((mask[:, :, 0] > 0).sum().item())
    return metrics
