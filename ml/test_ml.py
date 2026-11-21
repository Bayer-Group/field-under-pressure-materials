from pathlib import Path
import sys
import tempfile
import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon
import torch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from kw.soil_bonification import FieldSoilProfile, evaluate_field_calendar
from ml.config import FORECAST_DAYS, HISTORY_DAYS, ModelConfig, TrainConfig
from ml.dataset import FeatureScaler, FieldTimeSeriesDataset, split_indices
from ml.model import VegetationLSTM, compute_masked_metrics, masked_smooth_l1_loss
from ml.predict import load_trained_model, predict_field_7days
from ml.prepare_dataset import (
    build_fields_master,
    build_weather_table_from_bayer,
    build_weather_table_from_open_meteo,
    extract_satellite_indices_from_tiffs,
    generate_synthetic_demo_dataset,
    parse_date_from_filename,
)
from ml.train import train_model


class TestPrepareDataset(unittest.TestCase):
    def test_build_fields_master_with_bk_crops_schema(self):
        bk_crops = ROOT_DIR / "bk" / "fields_crops.geojson"
        gdf = gpd.read_file(bk_crops).head(6).copy()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            crops_path = tmp / "sample_crops.geojson"
            gdf.to_file(crops_path, driver="GeoJSON")

            # Symulacja wyjścia prepare_all_soil_profiles dla tych 6 pól
            centroids = gdf.to_crs("EPSG:2180").geometry.centroid.to_crs("EPSG:4326")
            soil_df = pd.DataFrame(
                {
                    "field_id": [f"field_{i}" for i in range(len(gdf))],
                    "area_ha": gdf["area_ha"].to_numpy(),
                    "centroid_lat": centroids.y.to_numpy(),
                    "centroid_lon": centroids.x.to_numpy(),
                    "h3_cells_count": [5] * len(gdf),
                    "sand_pct": [68.0] * len(gdf),
                    "silt_pct": [20.0] * len(gdf),
                    "clay_pct": [12.0] * len(gdf),
                    "ph": [6.1] * len(gdf),
                    "om": [3.5] * len(gdf),
                    "cec": [16.0] * len(gdf),
                    "bulk_density": [1.38] * len(gdf),
                    "soilTexture": ["Sandy Loam"] * len(gdf),
                    "bonitation_score": [62.0] * len(gdf),
                    "klasa_bonitacyjna": ["IIIb"] * len(gdf),
                    "permeability": ["wysoka"] * len(gdf),
                    "water_retention": ["niska"] * len(gdf),
                    "wilting_point": [0.08] * len(gdf),
                    "field_capacity": [0.18] * len(gdf),
                }
            )
            soil_path = tmp / "soil.parquet"
            soil_df.to_parquet(soil_path, index=False)

            master = build_fields_master(
                fields_crops_geojson=crops_path,
                soil_profiles_parquet=soil_path,
                out_path=tmp / "fields_master.parquet",
            )
            self.assertEqual(len(master), 6)
            self.assertEqual(master.loc[0, "crop"], "kukurydza")  # 1130
            self.assertEqual(master.loc[1, "crop"], "inne")       # NaN
            self.assertEqual(master.loc[2, "crop"], "rzepak")     # 1430

            mvp_only = build_fields_master(
                fields_crops_geojson=crops_path,
                soil_profiles_parquet=soil_path,
                out_path=tmp / "fields_master_mvp.parquet",
                only_mvp_crops=True,
            )
            self.assertTrue(set(mvp_only["crop"]).issubset({"pszenica", "kukurydza", "rzepak"}))
            self.assertGreater(len(mvp_only), 0)

    def test_extract_satellite_indices_from_tiffs_and_cloud_filter(self):
        self.assertEqual(parse_date_from_filename("S2A_33UWU_20240624_0_L2A.tif"), "2024-06-24")
        self.assertEqual(parse_date_from_filename("wycinek_2024-07-05.tif"), "2024-07-05")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Dwa pola w EPSG:32634 (20 m piksel, łatwe współrzędne)
            poly_clean = Polygon([(500040, 5800040), (500140, 5800040), (500140, 5800140), (500040, 5800140)])
            poly_cloudy = Polygon([(500240, 5800040), (500340, 5800040), (500340, 5800140), (500240, 5800140)])
            gdf = gpd.GeoDataFrame(
                {"area_ha": [1.0, 1.0]},
                geometry=[poly_clean, poly_cloudy],
                crs="EPSG:32634",
            ).to_crs("EPSG:4326")
            fields_path = tmp / "fields.geojson"
            gdf.to_file(fields_path, driver="GeoJSON")

            # Tworzymy GeoTIFF w formacie satelite_img_downloader.ipynb (pasma red, nir, swir16, NDVI, NDMI)
            h, w = 20, 30
            transform = from_origin(500000.0, 5800200.0, 20.0, 20.0)
            ndvi_band = np.full((h, w), 0.72, dtype=np.float32)
            ndmi_band = np.full((h, w), 0.34, dtype=np.float32)
            # Zachmurzenie (NaN) na prawie całym drugim polu (kolumny >= 13)
            ndvi_band[:, 13:] = np.nan
            ndmi_band[:, 13:] = np.nan
            dummy = np.full((h, w), 1000.0, dtype=np.float32)

            tif_path = tmp / "s2_2024-06-24.tif"
            with rasterio.open(
                tif_path,
                "w",
                driver="GTiff",
                height=h,
                width=w,
                count=5,
                dtype="float32",
                crs="EPSG:32634",
                transform=transform,
                nodata=np.nan,
            ) as dst:
                dst.write(np.stack([dummy, dummy, dummy, ndvi_band, ndmi_band]))
                for idx, name in enumerate(["red", "nir", "swir16", "NDVI", "NDMI"], start=1):
                    dst.set_band_description(idx, name)

            sat_df = extract_satellite_indices_from_tiffs(
                fields_geojson=fields_path,
                tiff_inputs=[tif_path],
                out_path=tmp / "sat.parquet",
                min_valid_ratio=0.5,
            )
            # Tylko field_0 (czyste) powinno przejść filtr zachmurzenia
            self.assertEqual(len(sat_df), 1)
            self.assertEqual(sat_df.loc[0, "field_id"], "field_0")
            self.assertEqual(sat_df.loc[0, "date"], "2024-06-24")
            self.assertAlmostEqual(sat_df.loc[0, "ndvi"], 0.72, places=3)
            self.assertAlmostEqual(sat_df.loc[0, "ndmi"], 0.34, places=3)
            self.assertAlmostEqual(sat_df.loc[0, "valid_pixel_ratio"], 1.0, places=2)

    def test_bayer_missing_precip_with_imerg_and_open_meteo_adapter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fields_master = pd.DataFrame(
                [
                    {"field_id": "f1", "centroid_lat": 52.60, "centroid_lon": 20.80},
                    {"field_id": "f2", "centroid_lat": 52.62, "centroid_lon": 20.85},
                ]
            )
            fm_path = tmp / "fields_master.parquet"
            fields_master.to_parquet(fm_path, index=False)

            grids = pd.DataFrame(
                [
                    {"grid_id": "g_a", "lat": 52.60, "lon": 20.80},
                    {"grid_id": "g_b", "lat": 52.62, "lon": 20.85},
                ]
            )
            grids_path = tmp / "weather_grids.parquet"
            grids.to_parquet(grids_path, index=False)

            # Bayer BEZ total_precipitation
            bayer_no_precip = pd.DataFrame(
                [
                    {
                        "grid_id": "g_a",
                        "date": "2024-06-01",
                        "avg_temperature": 18.0,
                        "min_temperature": 12.0,
                        "max_temperature": 24.0,
                        "avg_soil_moisture_level_1": 0.21,
                        "avg_soil_moisture_level_2": 0.24,
                        "avg_soil_moisture_level_3": 0.28,
                    },
                    {
                        "grid_id": "g_b",
                        "date": "2024-06-01",
                        "avg_temperature": 19.0,
                        "min_temperature": 13.0,
                        "max_temperature": 25.0,
                        "avg_soil_moisture_level_1": 0.19,
                        "avg_soil_moisture_level_2": 0.22,
                        "avg_soil_moisture_level_3": 0.26,
                    },
                ]
            )
            bayer_path = tmp / "bayer_2024.parquet"
            bayer_no_precip.to_parquet(bayer_path, index=False)

            imerg = pd.DataFrame(
                [
                    {"grid_id": "g_a", "date": "2024-06-01", "total_precipitation": 6.4},
                    {"grid_id": "g_b", "date": "2024-06-01", "total_precipitation": 0.0},
                ]
            )
            imerg_path = tmp / "imerg.parquet"
            imerg.to_parquet(imerg_path, index=False)

            w_bayer = build_weather_table_from_bayer(
                fields_master_parquet=fm_path,
                bayer_weather_parquets=bayer_path,
                weather_grids_parquet=grids_path,
                imerg_daily_parquet=imerg_path,
                out_path=tmp / "weather_bayer.parquet",
            )
            self.assertEqual(len(w_bayer), 2)
            self.assertAlmostEqual(w_bayer.loc[w_bayer["field_id"] == "f1", "precip_sum_mm"].iloc[0], 6.4, places=3)
            self.assertAlmostEqual(w_bayer.loc[w_bayer["field_id"] == "f2", "temp_mean_c"].iloc[0], 19.0, places=3)

            # Open-Meteo adapter
            om_df = pd.DataFrame(
                [
                    {
                        "lat": 52.60,
                        "lon": 20.80,
                        "date": "2026-11-20",
                        "temp_mean_c": 6.0,
                        "temp_min_c": 2.0,
                        "temp_max_c": 9.0,
                        "precip_sum_mm": 1.2,
                        "precip_72h_mm": 3.0,
                        "sm_l1": 0.22,
                        "sm_l2": 0.24,
                        "sm_l3": 0.27,
                    }
                ]
            )
            om_path = tmp / "open_meteo.parquet"
            om_df.to_parquet(om_path, index=False)
            w_om = build_weather_table_from_open_meteo(fm_path, om_path, out_path=tmp / "weather_om.parquet")
            self.assertEqual(len(w_om), 2)
            self.assertAlmostEqual(w_om.loc[0, "precip_sum_mm"], 1.2, places=3)


class TestModelTrainPredictAndCalendar(unittest.TestCase):
    def test_model_shapes_loss_and_scaler_roundtrip(self):
        cfg = ModelConfig(hidden_size=32, num_layers=2)
        model = VegetationLSTM(cfg)
        x_h = torch.randn(4, HISTORY_DAYS, cfg.hist_input_size)
        x_f = torch.randn(4, FORECAST_DAYS, cfg.future_input_size)
        x_s = torch.randn(4, cfg.static_input_size)
        last_t = torch.tensor([[0.5, 0.2]] * 4, dtype=torch.float32)

        pred = model(x_h, x_f, x_s, last_t)
        self.assertEqual(pred.shape, (4, FORECAST_DAYS, 2))
        self.assertTrue(torch.all((pred >= -1.0) & (pred <= 1.0)))

        target = torch.zeros_like(pred)
        mask = torch.zeros_like(pred)
        mask[:, 2, :] = 1.0
        loss = masked_smooth_l1_loss(pred, target, mask)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()

        metrics = compute_masked_metrics(pred.detach(), target, mask)
        self.assertEqual(metrics["valid_points"], 4)
        self.assertTrue(np.isfinite(metrics["ndvi_mae"]))

    def test_end_to_end_demo_train_predict_and_calendar_bridge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            demo_dir = generate_synthetic_demo_dataset(tmp / "demo_data", n_fields=6, n_days=90, seed=7)
            ckpt_path = tmp / "checkpoints" / "demo.pt"

            summary = train_model(
                data_dir=demo_dir,
                checkpoint_path=ckpt_path,
                model_cfg=ModelConfig(hidden_size=32, num_layers=1, dropout=0.0),
                train_cfg=TrainConfig(epochs=2, batch_size=16, split_mode="field", target_mode="observed"),
            )
            self.assertTrue(ckpt_path.exists())
            self.assertGreater(summary["n_train"], 0)
            self.assertGreater(summary["n_val"], 0)
            self.assertTrue(np.isfinite(summary["best_val_loss"]))

            # Inferencja z użyciem checkpointu
            model, scaler, m_cfg = load_trained_model(ckpt_path)
            fields_df = pd.read_parquet(demo_dir / "fields_master.parquet")
            sat_df = pd.read_parquet(demo_dir / "satellite_indices.parquet")
            weather_df = pd.read_parquet(demo_dir / "weather_daily.parquet")

            f0 = fields_df.iloc[0]
            pred = predict_field_7days(
                model=model,
                scaler=scaler,
                model_cfg=m_cfg,
                field_profile=f0,
                satellite_df=sat_df,
                weather_df=weather_df,
            )
            self.assertEqual(len(pred["dates"]), FORECAST_DAYS)
            self.assertEqual(len(pred["ndvi_by_date"]), FORECAST_DAYS)
            self.assertEqual(len(pred["ndmi_by_date"]), FORECAST_DAYS)

            # Bezpośrednie podpięcie do kalendarza z kw/soil_bonification.py
            soil_profile = FieldSoilProfile(
                field_id=str(f0["field_id"]),
                area_ha=float(f0["area_ha"]),
                centroid_lat=float(f0["centroid_lat"]),
                centroid_lon=float(f0["centroid_lon"]),
                h3_cells_count=5,
                sand_pct=float(f0["sand_pct"]),
                silt_pct=float(f0["silt_pct"]),
                clay_pct=float(f0["clay_pct"]),
                soilTexture=str(f0["soilTexture"]),
                ph=float(f0["ph"]),
                bonitation_score=float(f0["bonitation_score"]),
                klasa_bonitacyjna=str(f0["klasa_bonitacyjna"]),
                bonitation_source="Estymacja ISRIC SoilGrids",
                permeability=f0["permeability"],
                water_retention=f0["water_retention"],
                wilting_point=float(f0["wilting_point"]),
                field_capacity=float(f0["field_capacity"]),
            )
            w_sub = weather_df[
                (weather_df["field_id"] == f0["field_id"]) & (weather_df["date"].isin(pred["dates"]))
            ].copy()
            w_sub["precip_72h_mm"] = (
                w_sub["precip_sum_mm"].iloc[::-1].rolling(3, min_periods=1).sum().iloc[::-1]
            )

            cal = evaluate_field_calendar(
                soil=soil_profile,
                field_weather_df=w_sub,
                fertilizer="mocznik_inhibitor",
                crop="kukurydza",
                ndmi_by_date=pred["ndmi_by_date"],
                ndvi_by_date=pred["ndvi_by_date"],
            )
            self.assertEqual(len(cal), FORECAST_DAYS)
            self.assertIn("ndmi_forecast", cal[0])
            self.assertEqual(cal[0]["ndmi_forecast"], pred["ndmi_by_date"][cal[0]["date"]])


if __name__ == "__main__":
    unittest.main()
