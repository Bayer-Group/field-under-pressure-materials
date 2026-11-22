"""python -m ml.validate_2024_2025 --data-dir ml_data \
     --checkpoint ml/checkpoints/vegetation_lstm.pt --out validation_results.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from ml.predict import load_trained_model, predict_field_7days


def parse_args():
    p = argparse.ArgumentParser(description="Walidacja VegetationLSTM, lata 2024–2025")
    p.add_argument("--data-dir", default="ml_data")
    p.add_argument("--checkpoint", default="ml/checkpoints/vegetation_lstm.pt")
    p.add_argument("--out", default="validation_results")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--step-days", type=int, default=7, help="Odstęp dat kotwic")
    p.add_argument("--min-valid-ratio", type=float, default=0.5)
    p.add_argument("--max-fields", type=int, default=0, help="0 oznacza wszystkie")
    return p.parse_args()


def main():
    args = parse_args()
    base, out = Path(args.data_dir), Path(args.out)
    files = [base / "fields_master.parquet", base / "satellite_indices.parquet", base / "weather_daily.parquet"]
    needed = [Path(args.checkpoint), *files]
    missing = [str(p) for p in needed if not p.is_file()]
    if missing:
        raise SystemExit("Brak danych/modelu:\n- " + "\n- ".join(missing))
    out.mkdir(parents=True, exist_ok=True)
    fields = pd.read_parquet(files[0]); sat = pd.read_parquet(files[1]); weather = pd.read_parquet(files[2])
    for df in (fields, sat, weather):
        df["field_id"] = df["field_id"].astype(str)
    for df in (sat, weather):
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    sat = sat.dropna(subset=["ndvi", "ndmi"])
    if "valid_pixel_ratio" in sat.columns:
        sat = sat[sat["valid_pixel_ratio"] >= args.min_valid_ratio]
    # Dla danej daty i pola bierzemy jedną rzeczywistą obserwację.
    sat = sat.groupby(["field_id", "date"], as_index=False)[["ndvi", "ndmi"]].median()
    model, scaler, model_cfg = load_trained_model(args.checkpoint, device="cpu")
    start = pd.Timestamp(args.start); end = pd.Timestamp(args.end)
    rows=[]; skipped=0
    field_rows = fields.drop_duplicates("field_id").to_dict("records")
    if args.max_fields:
        field_rows = field_rows[:args.max_fields]
    for field in field_rows:
        fid = str(field["field_id"])
        observations = sat[sat.field_id == fid].set_index("date")
        w = weather[weather.field_id == fid].sort_values("date")
        if observations.empty or w.empty: continue
        # Dane do historii mogą zaczynać się w 2023 r.; kotwice zawsze są 2024+.
        # NIE używamy wyników spoza lat testowych jako targetów.
        earliest = max(start, w.date.min() + pd.Timedelta(days=model_cfg.history_days-1))
        latest = min(end - pd.Timedelta(days=model_cfg.forecast_days), w.date.max() - pd.Timedelta(days=model_cfg.forecast_days))
        if earliest > latest: continue
        for anchor in pd.date_range(earliest, latest, freq=f"{args.step_days}D"):
            # Model oczekuje prawdziwej pogody na następne 7 dni: test 'perfect weather'.
            # Dane satelitarne po dacie kotwicy NIE MOGĄ trafić do wejścia!
            past_sat = sat[(sat.field_id == fid) & (sat.date <= anchor)].copy()
            try:
                pred = predict_field_7days(
                    model=model, scaler=scaler, model_cfg=model_cfg,
                    field_profile=field, satellite_df=past_sat,
                    weather_df=w, reference_date=anchor.date().isoformat(),
                    crop=field.get("crop", "inne"), device="cpu",
                )
            except (ValueError, KeyError) as e:
                skipped += 1
                if skipped <= 5:
                    print(f"BŁĄD | pole={fid} | data={anchor.date()} | {type(e).__name__}: {e}")
                continue
            for horizon in range(1, model_cfg.forecast_days + 1):
                target_date = anchor + pd.Timedelta(days=horizon)
                if target_date not in observations.index: continue
                key = target_date.date().isoformat()
                p_ndvi = pred.get("ndvi_by_date", {}).get(key)
                p_ndmi = pred.get("ndmi_by_date", {}).get(key)
                if p_ndvi is None or p_ndmi is None: continue
                truth = observations.loc[target_date]
                if isinstance(truth, pd.DataFrame): truth = truth.iloc[0]
                # Naiwny baseline: ostatnia REALNA obserwacja z dnia <= anchor.
                hist_obs = observations.loc[observations.index <= anchor]
                if hist_obs.empty: continue
                baseline = hist_obs.iloc[-1]
                for var, estimate in (("ndvi", p_ndvi), ("ndmi", p_ndmi)):
                    actual = float(truth[var]); estimated=float(estimate)
                    if not np.isfinite(actual) or not np.isfinite(estimated): continue
                    rows.append(dict(field_id=fid, anchor_date=anchor.date().isoformat(),
                                     target_date=key, year=target_date.year, horizon=horizon,
                                     variable=var, actual=actual, predicted=estimated,
                                     persistence=float(baseline[var])))
    if not rows:
        raise SystemExit(f"Nie znaleziono porównań z rzeczywistymi obserwacjami. Pominięte prognozy: {skipped}. "
                         "Sprawdź daty, field_id i kompletność danych.")
    df = pd.DataFrame(rows)
    df["error"] = df.predicted - df.actual
    df["baseline_error"] = df.persistence - df.actual
    df.to_csv(out / "predictions_vs_observations.csv", index=False)
    def metric(g):
        return pd.Series({
            "n": len(g), "mae": g.error.abs().mean(),
            "rmse": np.sqrt((g.error**2).mean()),
            "baseline_mae": g.baseline_error.abs().mean(),
            "baseline_rmse": np.sqrt((g.baseline_error**2).mean()),
        })
    df.groupby(["year", "variable"], sort=True).apply(metric).reset_index().to_csv(out / "metrics_by_year.csv", index=False)
    df.groupby(["year", "variable", "horizon"], sort=True).apply(metric).reset_index().to_csv(out / "metrics_by_horizon.csv", index=False)
    print(f"Zapisano {len(df)} porównań do {out}. Pominięte próby: {skipped}")
    print("UWAGA: Wyniki z rzeczywistą przyszłą pogodą = test perfect-weather.")
    print("UWAGA: Przed publikacją wyniku sprawdź brak przecieku przyszłych obserwacji w build_field_daily_series.")


if __name__ == "__main__":
    main()
