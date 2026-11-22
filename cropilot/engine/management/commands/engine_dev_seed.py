"""
python manage.py engine_dev_seed [--bbox W S E N] [--season 2025] [--today 2025-06-15] [--fields-per-crop 3]
python manage.py engine_dev_seed --season 2024 --today 2024-06-15 --crop-from-map --fields-per-crop 2   # demo farm

FOR ENGINE DEVELOPMENT ONLY. Fills an empty database with a small demo farm so predict() can run end
to end before the platform's import exists. The platform's import (Jan + Szymek) replaces it; it
touches only rows it creates (fields named "dev: ..." or with a DEMO_NAMES name), plus the Clock and the threats.

- Fields: wheat and maize parcels of the crop map of season-1 inside --bbox (connected pixels of one
  class, >= 3 ha), simplified to polygons. Their crop for --season comes from the Sentinel-2 NDVI
  curve of that season up to --today (engine.cropmodel when trained, else a simple rule).
  --crop-from-map: parcels of all seven engine crops, crop = the crop map of --season itself (no satellite,
  no network; for a season whose crop map exists, e.g. 2024); fields get Polish names (DEMO_NAMES).
- FieldCropYear from the crop maps 2020-2024, the nearest weather grid cell, H3 level-10 soil cells.
- Weather daily + hourly (+ IMERG precipitation) for the fields' grid cells, seasons season-1 and season.
- Forecast seeded from observed weather (issued D -> D+1..D+7), as the platform does.
"""

from __future__ import annotations

import glob
import zipfile
from datetime import date, timedelta
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import rasterio
import rasterio.enums
import rasterio.features
import rasterio.mask
import rasterio.warp
import rasterio.windows
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from pyproj import Transformer
from scipy import ndimage
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

from core.models import (Clock, CropClass, Field, FieldCropYear, SoilCell, WeatherDaily, WeatherForecastDaily,
                         WeatherGrid, WeatherHourly)

LEGEND = {0: "No cropland", 1110: "Wheat", 1120: "Barley", 1130: "Maize", 1140: "Rice", 1150: "Other cereals",
          1210: "Fresh vegetables", 1220: "Dry pulses", 1310: "Potatoes", 1320: "Sugar beet", 1410: "Sunflower",
          1420: "Soybeans", 1430: "Rapeseed", 1440: "Flax, cotton and hemp", 2100: "Grapes", 2200: "Olives",
          2310: "Fruits", 2320: "Nuts", 3100: "Unclassified arable crop", 3200: "Unclassified permanent crop",
          65535: "Outside area"}
TEST_BBOX = (17.62, 50.32, 17.74, 50.40)  # farmland SW of Krapkowice, Opolskie
ENGINE_CROPS = (1110, 1120, 1130, 1150, 1310, 1320, 1430)
# Field names of the demo farm (--crop-from-map), in the order the fields are made.
DEMO_NAMES = ["Pod Lasem", "Za Stodołą", "Długie", "Przy Drodze", "Nad Stawem", "Klin", "Górka", "Za Torami",
              "Wygon", "Dolne", "Krzyżówka", "Kamionka", "Pod Wierzbami", "Łęgi", "Rozdroże", "Zagonki"]
TO_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True).transform


def data_dir() -> Path:
    base = Path(getattr(settings, "BASE_DIR", "."))
    import os
    return (base / os.environ.get("DATA_DIR", "../field-under-pressure-data")).resolve()


class Command(BaseCommand):
    help = "Engine development seed: a small demo farm with weather, soil and crop history (dev only)."

    def add_arguments(self, p):
        p.add_argument("--bbox", type=float, nargs=4, default=TEST_BBOX)
        p.add_argument("--season", type=int, default=2025)
        p.add_argument("--today", type=date.fromisoformat, default=date(2025, 6, 15))
        p.add_argument("--fields-per-crop", type=int, default=3)
        p.add_argument("--region", default="Opolskie")
        p.add_argument("--crop-from-map", action="store_true",
                       help="All engine crops, crop from the crop map of --season (no satellite); Polish field names.")

    def handle(self, *a, bbox, season, today, fields_per_crop, region, crop_from_map=False, **o):
        D = data_dir()
        self.stdout.write(f"data dir: {D}")
        for code, name in LEGEND.items():
            CropClass.objects.update_or_create(code=code, defaults={"name": name})
        if crop_from_map:
            parcels = self.parcels(D, bbox, season, fields_per_crop * 3, codes=ENGINE_CROPS)
            self.stdout.write(f"{len(parcels)} candidate parcels from the {season} crop map")
            crops = [p["crop_prev"] for p in parcels]  # the class in the --season map itself
        else:
            parcels = self.parcels(D, bbox, season - 1, fields_per_crop * 6)
            self.stdout.write(f"{len(parcels)} candidate parcels from the {season - 1} crop map")
            crops = self.crop_this_season(parcels, season, today)
        grids = pd.read_parquet(D / "weather" / "weather_grids.parquet", columns=["grid_id", "lat", "lon"])
        grids[["lat", "lon"]] = grids[["lat", "lon"]].astype(float)  # stored as decimals in the source
        chosen = {c: [] for c in (ENGINE_CROPS if crop_from_map else (1110, 1130))}
        for p, crop in zip(parcels, crops):
            if p.get("crop_model"):
                self.stdout.write(f"  parcel ({p['crop_prev']} last year): model says {p['crop_model'].get('label')} {p['crop_model'].get('confidence', 0):.0%}")
            if crop in chosen and len(chosen[crop]) < fields_per_crop:
                chosen[crop].append(p | {"crop": crop})
        with transaction.atomic():
            Field.objects.filter(name__startswith="dev: ").delete()
            Field.objects.filter(name__in=DEMO_NAMES).delete()
            made = []
            names = iter(DEMO_NAMES)
            for crop, items in chosen.items():
                for i, p in enumerate(items, 1):
                    made.append(self.make_field(D, p, i, grids, name=next(names) if crop_from_map else None))
            self.stdout.write(f"{len(made)} fields: " + ", ".join(f.name for f in made))
            grid_ids = sorted({f.weather_grid_id for f in made})
            self.load_weather(D, region, grid_ids, [season - 1, season])
            self.seed_forecast(grid_ids, date(season - 2, 12, 1), date(season, 12, 31))
            self.load_soil(D, region, {c for f in made for c in f.h3_cells})
            Clock(today=today).save()
        call_command("engine_load_threats")
        self.stdout.write(self.style.SUCCESS(f"Dev farm ready. Clock = {today}. Run: python manage.py engine_predict --season"))

    # --- fields ---------------------------------------------------------------------------------
    def parcels(self, D: Path, bbox, year: int, n: int, codes=(1110, 1130)) -> list[dict]:
        """
        Candidate parcels: pixels of one class in BOTH `year` and `year - 1` (parcel borders persist, so
        neighbouring parcels with the same crop in one year are split by the other year), 5-40 ha.
        Patches of one crop in a single year merge several farmers' parcels into one huge "field".
        """
        with rasterio.open(D / "cropland" / f"cropland_{year}.tif") as src:
            win = rasterio.windows.from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
            a = src.read(1, window=win)
            t = rasterio.windows.transform(win, src.transform)
        with rasterio.open(D / "cropland" / f"cropland_{year - 1}.tif") as src:
            wb = rasterio.windows.from_bounds(*bbox, transform=src.transform).round_offsets().round_lengths()
            b = np.zeros_like(a)
            rasterio.warp.reproject(src.read(1, window=wb, boundless=True, fill_value=65535), b,
                                    src_transform=rasterio.windows.transform(wb, src.transform), src_crs=src.crs,
                                    dst_transform=t, dst_crs=src.crs, resampling=rasterio.enums.Resampling.nearest)
        px_ha = 0.0134  # pixel area in this EPSG:4326 grid at ~50.4° N (≈ 10.6 m x 12.6 m)
        out = []
        for code in codes:
            stable = (a == code) & (b != 65535) & (b != 0)
            mask = ndimage.binary_opening(stable, iterations=2)
            # split by last year's class: a parcel is one class this year AND one class last year
            lab = np.zeros(a.shape, dtype=np.int32); k = 0
            for prev_code in np.unique(b[mask]):
                l2, k2 = ndimage.label(ndimage.binary_opening(mask & (b == prev_code), iterations=1))
                lab[l2 > 0] = l2[l2 > 0] + k; k += k2
            sizes = ndimage.sum(lab > 0, lab, range(1, k + 1))
            order = [i for i in np.argsort(-sizes) if 5 <= sizes[i] * px_ha <= 40][: n]
            for idx in order:
                comp = (lab == idx + 1).astype("uint8")
                geoms = [shape(g) for g, v in rasterio.features.shapes(comp, mask=comp == 1, transform=t) if v == 1]
                poly = max(geoms, key=lambda g: g.area).simplify(0.00008).buffer(-0.00005)
                if poly.is_empty:
                    continue
                if poly.geom_type == "MultiPolygon":
                    poly = max(poly.geoms, key=lambda g: g.area)
                out.append({"geom": poly, "crop_prev": code})
        return out

    def crop_this_season(self, parcels: list[dict], season: int, today: date) -> list[int | None]:
        """Crop of each parcel this season from Sentinel-2, as of `today` (no peeking past it)."""
        from engine.satellite.earthsearch import read_ndvi_window
        from engine.satellite.season import composite, season_bounds
        if not parcels:
            return []
        minx = min(p["geom"].bounds[0] for p in parcels); miny = min(p["geom"].bounds[1] for p in parcels)
        maxx = max(p["geom"].bounds[2] for p in parcels); maxy = max(p["geom"].bounds[3] for p in parcels)
        start, _ = season_bounds(season)
        scenes = read_ndvi_window((minx, miny, maxx, maxy), start.isoformat(), today.isoformat())
        if scenes is None:
            return [None] * len(parcels)
        comp = composite(scenes.dates, scenes.ndvi, season)
        try:
            from engine.cropmodel import predict_pixels
        except Exception:
            predict_pixels = None
        to_utm = Transformer.from_crs("EPSG:4326", scenes.crs, always_xy=True).transform
        crops = []
        for p in parcels:
            g = shp_transform(to_utm, p["geom"])
            m = rasterio.features.geometry_mask([mapping(g)], out_shape=comp.shape[1:], transform=scenes.transform, invert=True)
            curve = np.nanmedian(comp[:, m], axis=1) if m.any() else np.full(comp.shape[0], np.nan)
            crop = None
            if predict_pixels is not None and m.any():
                try:
                    res = predict_pixels(comp[:, m].T, season, today)
                    crop = res.get("crop") if res.get("confidence", 0) >= 0.6 else None
                    p["crop_model"] = res
                except FileNotFoundError:
                    predict_pixels = None
            if predict_pixels is None:  # simple rule on the median curve: green in spring -> winter cereal, bare in spring -> maize
                spring = np.nanmean(curve[13:16])  # Mar b .. Apr b
                if np.isfinite(spring):
                    crop = 1110 if spring > 0.6 else (1130 if spring < 0.4 else None)
            crops.append(crop)
        return crops

    def make_field(self, D: Path, p: dict, i: int, grids: pd.DataFrame, name: str | None = None) -> Field:
        g = p["geom"]
        c = g.centroid
        area_ha = shp_transform(TO_2180, g).area / 10_000
        dist = (grids["lat"] - c.y) ** 2 + ((grids["lon"] - c.x) * np.cos(np.radians(c.y))) ** 2
        gr = grids.loc[dist.idxmin()]
        WeatherGrid.objects.update_or_create(grid_id=gr.grid_id, defaults={"lat": gr.lat, "lon": gr.lon})
        cells = list(h3.geo_to_cells(mapping(g), 10)) or [h3.latlng_to_cell(c.y, c.x, 10)]
        crop_name = "wheat" if p["crop"] == 1110 else "maize"
        f = Field.objects.create(
            name=name or f"dev: {crop_name} {i}", geometry=mapping(g), area_ha=round(area_ha, 2),
            centroid_lat=c.y, centroid_lon=c.x, weather_grid_id=gr.grid_id, h3_cells=cells, crop_id=p["crop"],
        )
        rows = []
        for year in range(2020, 2025):
            with rasterio.open(D / "cropland" / f"cropland_{year}.tif") as src:
                arr, _ = rasterio.mask.mask(src, [mapping(g)], crop=True, filled=True, nodata=65534)
            v = arr[0][arr[0] != 65534]
            codes, counts = np.unique(v, return_counts=True)
            for code, cnt in zip(codes, counts):
                if int(code) in LEGEND:
                    rows.append(FieldCropYear(field=f, year=year, crop_class_id=int(code), share=float(cnt / v.size)))
        FieldCropYear.objects.bulk_create(rows)
        return f

    # --- weather --------------------------------------------------------------------------------
    def _read_zip_parquet(self, zpath: Path, grid_ids: list[str]) -> pd.DataFrame:
        """Reads the parquet inside a (possibly nested) zip, filtered to grid_ids."""
        import io
        with zipfile.ZipFile(zpath) as z:
            names = [n for n in z.namelist() if not n.startswith("__MACOSX")]
            pq = [n for n in names if n.endswith(".parquet")]
            if pq:
                df = pd.read_parquet(io.BytesIO(z.read(pq[0])), filters=[("grid_id", "in", grid_ids)])
                return df
            inner = [n for n in names if n.endswith(".zip")]
            with zipfile.ZipFile(io.BytesIO(z.read(inner[0]))) as z2:
                pq = [n for n in z2.namelist() if n.endswith(".parquet") and not n.startswith("__MACOSX")]
                return pd.read_parquet(io.BytesIO(z2.read(pq[0])), filters=[("grid_id", "in", grid_ids)])

    def _imerg(self, D: Path, kind: str, year: int, region: str, grid_ids):
        import io
        with zipfile.ZipFile(D / "raw" / "weather_data" / f"imerg_precipitation_{kind}.zip") as z:
            name = next((n for n in z.namelist() if n.endswith(f"precip_{kind}_{year}_{region}.zip") and "__MACOSX" not in n), None)
            if name is None:
                return pd.DataFrame()
            with zipfile.ZipFile(io.BytesIO(z.read(name))) as z2:
                pq = [n for n in z2.namelist() if n.endswith(".parquet") and "__MACOSX" not in n]
                return pd.read_parquet(io.BytesIO(z2.read(pq[0])), filters=[("grid_id", "in", grid_ids)])

    def load_weather(self, D: Path, region: str, grid_ids: list[str], years: list[int]):
        dcols = {f.attname for f in WeatherDaily._meta.concrete_fields} - {"id"}
        hcols = {f.attname for f in WeatherHourly._meta.concrete_fields} - {"id"}
        WeatherDaily.objects.filter(grid_id__in=grid_ids).delete()
        WeatherHourly.objects.filter(grid_id__in=grid_ids).delete()
        nd = nh = 0
        for year in years:
            dz = D / "raw" / "weather_data" / "daily" / str(year) / f"weather_daily_{year}_{region}.zip"
            d = self._read_zip_parquet(dz, grid_ids)
            im = self._imerg(D, "daily", year, region, grid_ids)
            if not im.empty:
                im = im.rename(columns={"total_precipitation": "imerg_total_precipitation"})[["grid_id", "date", "imerg_total_precipitation"]]
                d = d.merge(im, on=["grid_id", "date"], how="left")
            d = d[[c for c in d.columns if c in dcols]]
            WeatherDaily.objects.bulk_create([WeatherDaily(**{k: (None if pd.isna(v) else v) for k, v in r.items()})
                                              for r in d.to_dict("records")], batch_size=5000, ignore_conflicts=True)
            nd += len(d)
            hz = D / "raw" / "weather_data" / "hourly" / str(year) / f"weather_hourly_{year}_{region}.zip"
            h = self._read_zip_parquet(hz, grid_ids)
            imh = self._imerg(D, "hourly", year, region, grid_ids)
            if not imh.empty:
                imh = imh.rename(columns={"precipitation": "imerg_precipitation"})[["grid_id", "utc_time", "imerg_precipitation"]]
                h = h.merge(imh, on=["grid_id", "utc_time"], how="left")
            h["utc_time"] = pd.to_datetime(h["utc_time"]).dt.tz_localize("UTC")
            h = h[[c for c in h.columns if c in hcols]]
            WeatherHourly.objects.bulk_create([WeatherHourly(**{k: (None if pd.isna(v) else v) for k, v in r.items()})
                                               for r in h.to_dict("records")], batch_size=5000, ignore_conflicts=True)  # year files overlap by an hour
            nh += len(h)
        self.stdout.write(f"weather: {nd} daily, {nh} hourly rows for {len(grid_ids)} grid cells")

    def seed_forecast(self, grid_ids, start: date, end: date):
        cols = [f.attname for f in WeatherForecastDaily._meta.concrete_fields if f.attname not in ("id", "grid_id", "issued_on", "date")]
        WeatherForecastDaily.objects.filter(grid_id__in=grid_ids).delete()
        rows = []
        for g in grid_ids:
            obs = {r["date"]: r for r in WeatherDaily.objects.filter(grid_id=g, date__range=(start, end))
                   .values("date", *cols, "imerg_total_precipitation")}
            for issued in sorted(obs):
                for k in range(1, 8):
                    r = obs.get(issued + timedelta(days=k))
                    if r:
                        r = {c: v for c, v in r.items() if c != "imerg_total_precipitation"}
                        if r.get("total_precipitation") is None:  # the weather packages have no rain: IMERG, as the platform seed does
                            r["total_precipitation"] = obs[issued + timedelta(days=k)]["imerg_total_precipitation"]
                        rows.append(WeatherForecastDaily(grid_id=g, issued_on=issued, **r))
        WeatherForecastDaily.objects.bulk_create(rows, batch_size=5000)
        self.stdout.write(f"forecast: {len(rows)} rows")

    # --- soil -----------------------------------------------------------------------------------
    def load_soil(self, D: Path, region: str, cells: set[str]):
        files = glob.glob(str(D / "soil" / f"{region}*.parquet"))
        if not files:
            self.stdout.write("soil: no parquet found, skipped")
            return
        s = pd.read_parquet(files[0], filters=[("h3_index_10", "in", sorted(cells))])
        s = s.rename(columns={"soilTexture": "soil_texture"})
        cols = {f.attname for f in SoilCell._meta.concrete_fields} - {"band_om", "band_cec", "band_ph"}  # bands are text in the source, float in the model
        s = s[[c for c in s.columns if c in cols]]
        SoilCell.objects.filter(h3_index_10__in=cells).delete()
        SoilCell.objects.bulk_create([SoilCell(**{k: (None if pd.isna(v) else v) for k, v in r.items()}) for r in s.to_dict("records")])
        self.stdout.write(f"soil: {len(s)} of {len(cells)} H3 cells")
