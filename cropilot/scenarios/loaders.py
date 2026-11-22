"""
Warstwa pozyskiwania i normalizacji danych wejściowych dla scenariuszy.

Odpowiada za:
- zasilenie tabel słownikowych (`CropClass`, `Threat`, `WeatherGrid`),
- utworzenie obiektów `Field`, `FieldCropYear` oraz `SoilCell` na podstawie geometrii i `DATA_DIR`,
- załadowanie historii pogody (`WeatherDaily`, `WeatherHourly`) z połączeniem opadów IMERG,
- wygenerowanie prognozy 7-dniowej (`WeatherForecastDaily`) dla każdego dnia sezonu,
- dostarczenie deterministycznego generatora zastępczego (fallback), gdy brakuje plików w `DATA_DIR`.
"""

from __future__ import annotations

import glob
import hashlib
import io
import math
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pandas as pd
from django.core.management import call_command
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

from core.models import (
    CropClass,
    DailyWeatherColumns,
    Field,
    FieldCropYear,
    Observation,
    SoilCell,
    Threat,
    WeatherDaily,
    WeatherForecastDaily,
    WeatherGrid,
    WeatherHourly,
)
from scenarios.exceptions import DataSourceError, ScenarioValidationError
from scenarios.schema import FieldSpec, ObservationSpec

from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Warsaw")
MIN_DAYS_PER_YEAR = 300  # fewer stored days than this: the year is (re)loaded, not taken as complete

CLMS_CROP_LEGEND: dict[int, str] = {
    0: "No cropland",
    1110: "Wheat",
    1120: "Barley",
    1130: "Maize",
    1140: "Rice",
    1150: "Other cereals",
    1210: "Fresh vegetables",
    1220: "Dry pulses",
    1310: "Potatoes",
    1320: "Sugar beet",
    1410: "Sunflower",
    1420: "Soybeans",
    1430: "Rapeseed",
    1440: "Flax, cotton and hemp",
    2100: "Grapes",
    2200: "Olives",
    2310: "Fruits",
    2320: "Nuts",
    3100: "Unclassified arable crop",
    3200: "Unclassified permanent crop",
    65535: "Outside area",
}

TO_EPSG_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True).transform


# What the last switch had to invent because DATA_DIR lacked it ("weather", "soil", "crop history", "weather grid").
# ScenarioManager.switch_to() clears it and reports it, so a synthetic demo never passes for the real one.
SYNTHETIC_USED: set[str] = set()


def _region_name_variants(region: str) -> list[str]:
    """Zwraca warianty nazwy województwa uwzględniające błędy kodowania w paczkach organizatora."""
    normalized = region.strip()
    variants = [normalized]
    ascii_map = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    no_diacritics = normalized.translate(ascii_map)
    if no_diacritics not in variants:
        variants.append(no_diacritics)

    # W paczkach danych występują nazwy z uciętą literą 'Ł' (np. 'odzkie', 'Maopolskie')
    stripped_l = normalized.replace("Ł", "").replace("ł", "")
    if stripped_l not in variants:
        variants.append(stripped_l)
    return variants


class ReferenceDataLoader:
    """Idempotentny loader tabel referencyjnych wspólnych dla wszystkich scenariuszy."""

    def __init__(self, data_dir: Path) -> None:
        """Inicjalizuje loader ścieżką do katalogu zewnętrznych zbiorów danych.

        Args:
            data_dir: Ścieżka z `settings.DATA_DIR`.
        """
        self.data_dir = data_dir
        self._grids_cache: pd.DataFrame | None = None

    def ensure_crop_classes(self) -> int:
        """Upewnia się, że wszystkie 21 klas CLMS znajduje się w tabeli `CropClass`.

        Returns:
            Liczba klas dostępnych w tabeli `CropClass` po synchronizacji.
        """
        for code, name in CLMS_CROP_LEGEND.items():
            CropClass.objects.update_or_create(code=code, defaults={"name": name})
        return CropClass.objects.count()

    def ensure_threats(self) -> int:
        """Ładuje katalog zagrożeń (`Threat`) przy użyciu kontraktu silnika decyzyjnego.

        Returns:
            Liczba zagrożeń dostępnych w bazie po synchronizacji.

        Raises:
            DataSourceError: Gdy komenda ładowania zagrożeń nie powiedzie się lub tabela pozostanie pusta.
        """
        try:
            call_command("engine_load_threats", verbosity=0)
        except Exception as exc:
            if not Threat.objects.exists():
                raise DataSourceError(f"Nie udało się załadować katalogu zagrożeń (Threat): {exc}") from exc

        count = Threat.objects.count()
        if count == 0:
            raise DataSourceError("Tabela Threat jest pusta po uruchomieniu 'engine_load_threats'.")
        return count

    def resolve_nearest_weather_grid(self, lat: float, lon: float, allow_fallback: bool = True) -> str:
        """Znajduje najbliższy punkt siatki pogodowej `WeatherGrid` i zapisuje go w bazie.

        Args:
            lat: Szerokość geograficzna centroidu pola [WGS84].
            lon: Długość geograficzna centroidu pola [WGS84].
            allow_fallback: Czy utworzyć syntetyczną komórkę siatki przy braku `weather_grids.parquet`.

        Returns:
            Identyfikator `grid_id` najbliższej komórki `WeatherGrid`.

        Raises:
            DataSourceError: Gdy brak pliku siatki w `DATA_DIR` i `allow_fallback=False`.
        """
        grids_df = self._load_grids_table()
        if grids_df is not None and not grids_df.empty:
            cos_lat = math.cos(math.radians(lat))
            dist_sq = (grids_df["lat"] - lat) ** 2 + ((grids_df["lon"] - lon) * cos_lat) ** 2
            nearest = grids_df.loc[dist_sq.idxmin()]
            grid_id = str(nearest["grid_id"])
            WeatherGrid.objects.update_or_create(
                grid_id=grid_id,
                defaults={
                    "lat": float(nearest["lat"]),
                    "lon": float(nearest["lon"]),
                    "geohash4": str(nearest.get("geohash4", "") or ""),
                    "time_zone": str(nearest.get("time_zone", "Europe/Warsaw") or "Europe/Warsaw"),
                },
            )
            return grid_id

        if not allow_fallback:
            raise DataSourceError(
                f"Brak pliku siatki pogodowej: {self.data_dir / 'weather' / 'weather_grids.parquet'}"
            )

        SYNTHETIC_USED.add("siatka pogodowa")
        synthetic_id = f"synth_{lat:.2f}_{lon:.2f}"
        WeatherGrid.objects.update_or_create(
            grid_id=synthetic_id,
            defaults={
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "geohash4": "",
                "time_zone": "Europe/Warsaw",
            },
        )
        return synthetic_id

    def _load_grids_table(self) -> pd.DataFrame | None:
        if self._grids_cache is not None:
            return self._grids_cache

        parquet_path = self.data_dir / "weather" / "weather_grids.parquet"
        if not parquet_path.is_file():
            return None

        df = pd.read_parquet(parquet_path)
        df["lat"] = df["lat"].astype(float)
        df["lon"] = df["lon"].astype(float)
        self._grids_cache = df
        return df


class FieldAndSoilLoader:
    """Loader geometrii pól, historii zmian upraw (`FieldCropYear`) oraz komórek glebowych (`SoilCell`)."""

    def __init__(self, data_dir: Path, reference_loader: ReferenceDataLoader) -> None:
        """Inicjalizuje loader danych przestrzennych pola.

        Args:
            data_dir: Ścieżka do `settings.DATA_DIR`.
            reference_loader: Instancja `ReferenceDataLoader` do rozwiązywania siatki pogodowej.
        """
        self.data_dir = data_dir
        self.reference_loader = reference_loader

    def build_fields(self, specs: list[FieldSpec], region: str, allow_fallback: bool = True) -> list[Field]:
        """Tworzy rekordy `Field`, oblicza ich powierzchnię w EPSG:2180, komórki H3 oraz ładuje glebę i historię upraw.

        Args:
            specs: Lista specyfikacji pól z definicji scenariusza.
            region: Nazwa województwa do odczytu pliku Parquet gleby.
            allow_fallback: Czy użyć domyślnych wartości gleby/historii upraw przy braku rastrów w `DATA_DIR`.

        Returns:
            Lista zapisanych w bazie obiektów `Field`.

        Raises:
            ScenarioValidationError: Gdy geometria pola jest pusta lub odwołuje się do nieznanego `crop_code`.
            DataSourceError: Gdy brak plików źródłowych i `allow_fallback=False`.
        """
        created_fields: list[Field] = []
        all_h3_cells: set[str] = set()

        for spec in specs:
            if not CropClass.objects.filter(code=spec.crop_code).exists():
                raise ScenarioValidationError(
                    f"Pole '{spec.name}' używa nieznanego kodu uprawy crop_code={spec.crop_code}."
                )

            geom = shape(spec.geometry)
            if geom.is_empty:
                raise ScenarioValidationError(f"Pole '{spec.name}' posiada pustą geometrię GeoJSON.")

            centroid = geom.centroid
            area_ha = shp_transform(TO_EPSG_2180, geom).area / 10_000.0
            grid_id = self.reference_loader.resolve_nearest_weather_grid(
                lat=centroid.y,
                lon=centroid.x,
                allow_fallback=allow_fallback,
            )

            h3_cells = self._extract_h3_cells(spec.geometry, centroid_lat=centroid.y, centroid_lon=centroid.x)
            all_h3_cells.update(h3_cells)

            field_obj = Field.objects.create(
                name=spec.name,
                geometry=mapping(geom),
                area_ha=round(float(area_ha), 4),
                centroid_lat=float(centroid.y),
                centroid_lon=float(centroid.x),
                weather_grid_id=grid_id,
                h3_cells=h3_cells,
                crop_id=spec.crop_code,
            )
            self._load_crop_history(field_obj, spec, allow_fallback=allow_fallback)
            created_fields.append(field_obj)

        if all_h3_cells:
            self._load_soil_cells(sorted(all_h3_cells), region=region, allow_fallback=allow_fallback)

        return created_fields

    @staticmethod
    def _extract_h3_cells(geojson_geometry: dict[str, Any], centroid_lat: float, centroid_lon: float) -> list[str]:
        """Wyznacza listę komórek H3 poziomu 10 leżących wewnątrz poligonu (lub komórkę centroidu)."""
        try:
            cells = list(h3.geo_to_cells(geojson_geometry, 10))
        except Exception:
            cells = []

        if not cells:
            cells = [h3.latlng_to_cell(centroid_lat, centroid_lon, 10)]
        return sorted(set(cells))

    def _load_crop_history(self, field: Field, spec: FieldSpec, allow_fallback: bool) -> None:
        """Wypełnia tabelę `FieldCropYear` na podstawie nadpisania w JSON, rastrów CLMS lub generatora fallback."""
        if spec.crop_history:
            rows: list[FieldCropYear] = []
            for year, class_shares in spec.crop_history.items():
                for crop_code, share in class_shares.items():
                    if not CropClass.objects.filter(code=crop_code).exists():
                        raise ScenarioValidationError(
                            f"Nieznany kod uprawy {crop_code} w 'crop_history' dla pola '{field.name}'."
                        )
                    rows.append(
                        FieldCropYear(field=field, year=year, crop_class_id=crop_code, share=float(share))
                    )
            FieldCropYear.objects.bulk_create(rows)
            return

        cropland_dir = self.data_dir / "cropland"
        raster_files = {year: cropland_dir / f"cropland_{year}.tif" for year in range(2020, 2025)}

        if all(path.is_file() for path in raster_files.values()):
            try:
                import rasterio
                import rasterio.mask
            except ImportError as exc:
                if not allow_fallback:
                    raise DataSourceError("Brak biblioteki 'rasterio' do odczytu rastrów upraw.") from exc
            else:
                rows = []
                for year, tif_path in raster_files.items():
                    with rasterio.open(tif_path) as src:
                        arr, _ = rasterio.mask.mask(
                            src, [field.geometry], crop=True, filled=True, nodata=65534
                        )
                    valid = arr[0][arr[0] != 65534]
                    if valid.size == 0:
                        continue
                    codes, counts = np.unique(valid, return_counts=True)
                    for code, cnt in zip(codes, counts):
                        code_int = int(code)
                        if code_int in CLMS_CROP_LEGEND:
                            rows.append(
                                FieldCropYear(
                                    field=field,
                                    year=year,
                                    crop_class_id=code_int,
                                    share=round(float(cnt / valid.size), 6),
                                )
                            )
                if rows:
                    FieldCropYear.objects.bulk_create(rows)
                    return

        if not allow_fallback:
            raise DataSourceError(f"Brak kompletu rastrów upraw 2020–2024 w katalogu: {cropland_dir}")

        # Deterministyczny płodozmian zastępczy (2020–2024)
        rotation_alt = CropClass.MAIZE if spec.crop_code == CropClass.WHEAT else CropClass.WHEAT
        SYNTHETIC_USED.add("historia upraw")
        fallback_rows = [
            FieldCropYear(
                field=field,
                year=year,
                crop_class_id=(spec.crop_code if year % 2 == 0 else rotation_alt),
                share=1.0,
            )
            for year in range(2020, 2025)
        ]
        FieldCropYear.objects.bulk_create(fallback_rows)

    def _load_soil_cells(self, h3_indices: list[str], region: str, allow_fallback: bool) -> None:
        """Ładuje rekordy `SoilCell` z plików ISRIC Parquet z normalizacją nazw kolumn i fallbackiem."""
        soil_file: Path | None = None
        for variant in _region_name_variants(region):
            matches = sorted(glob.glob(str(self.data_dir / "soil" / f"{variant}*.parquet")))
            if matches:
                soil_file = Path(matches[0])
                break

        model_cols = {f.attname for f in SoilCell._meta.concrete_fields}
        loaded_ids: set[str] = set()

        if soil_file is not None and soil_file.is_file():
            df = pd.read_parquet(soil_file, filters=[("h3_index_10", "in", h3_indices)])
            df = df.rename(
                columns={
                    "soilTexture": "soil_texture",
                    "pH": "ph",
                    "BAND_om": "band_om",
                    "BAND_cec": "band_cec",
                    "BAND_pH": "band_ph",
                }
            )
            for band_col in ("band_om", "band_cec", "band_ph"):
                if band_col in df.columns:
                    df[band_col] = df[band_col].apply(
                        lambda v: str(v).strip().lower() if pd.notna(v) and str(v).strip() else None
                    )

            df = df[[c for c in df.columns if c in model_cols]]
            SoilCell.objects.filter(h3_index_10__in=h3_indices).delete()
            records = [
                SoilCell(**{k: (None if pd.isna(v) else v) for k, v in row.items()})
                for row in df.to_dict("records")
            ]
            SoilCell.objects.bulk_create(records)
            loaded_ids = {rec.h3_index_10 for rec in records}

        missing_ids = [idx for idx in h3_indices if idx not in loaded_ids]
        if not missing_ids:
            return

        if not allow_fallback:
            raise DataSourceError(
                f"Brak danych glebowych dla komórek H3 ({len(missing_ids)} brakujących) w regionie '{region}'."
            )

        SYNTHETIC_USED.add("gleba")
        fallback_cells = [
            SoilCell(
                h3_index_10=cell_id,
                ocs_0_30cm_mean=68,
                om=24.1,
                cec=14.3,
                ph=6.4,
                sand=0.21,
                silt=0.61,
                clay=0.18,
                bulk_density=1.32,
                band_om=SoilCell.Band.MODERATE,
                band_cec=SoilCell.Band.MODERATE,
                band_ph=SoilCell.Band.MODERATE,
                soil_texture="silt loam",
            )
            for cell_id in missing_ids
        ]
        SoilCell.objects.bulk_create(fallback_cells, ignore_conflicts=True)


class WeatherAndForecastLoader:
    """Loader pogody obserwowanej (`WeatherDaily`, `WeatherHourly`) oraz generator prognoz (`WeatherForecastDaily`)."""

    def __init__(self, data_dir: Path) -> None:
        """Inicjalizuje loader danych meteorologicznych.

        Args:
            data_dir: Ścieżka do `settings.DATA_DIR`.
        """
        self.data_dir = data_dir

    def load_observed_weather(
        self,
        grid_ids: list[str],
        region: str,
        years: list[int],
        overrides: list[dict[str, Any]] | None = None,
        allow_fallback: bool = True,
    ) -> tuple[int, int]:
        """Importuje pogodę dzienną i godzinową wraz z opadami satelitarnymi IMERG dla zadanych komórek siatki.

        Args:
            grid_ids: Lista identyfikatorów `WeatherGrid.grid_id`.
            region: Nazwa województwa w nazwach archiwów ZIP.
            years: Lista lat kalendarzowych do załadowania (np. `[2024, 2025]`).
            overrides: Opcjonalne korekty wartości pogodowych z definicji scenariusza.
            allow_fallback: Czy wygenerować syntetyczne szeregi czasowe w razie braku archiwów ZIP.

        Returns:
            Krotka `(liczba_rekordów_daily, liczba_rekordów_hourly)`.

        Raises:
            DataSourceError: Gdy brakuje plików pogodowych w `DATA_DIR` i `allow_fallback=False`.
        """
        unique_grids = sorted(set(grid_ids))
        if not unique_grids:
            return (0, 0)

        for grid_id in unique_grids:
            # a year is loaded only when (nearly) all its days are: one leftover row used to count as a whole year
            has_all_years = all(
                WeatherDaily.objects.filter(grid_id=grid_id, date__year=yr).count() >= MIN_DAYS_PER_YEAR
                and WeatherHourly.objects.filter(grid_id=grid_id, date__year=yr).count() >= MIN_DAYS_PER_YEAR * 20
                for yr in years
            )
            if has_all_years:
                continue

            WeatherDaily.objects.filter(grid_id=grid_id, date__year__in=years).delete()
            WeatherHourly.objects.filter(grid_id=grid_id, date__year__in=years).delete()

            loaded_from_files = self._try_load_grid_from_archives(grid_id=grid_id, region=region, years=years)
            if not loaded_from_files:
                if not allow_fallback:
                    raise DataSourceError(
                        f"Brak archiwów pogodowych dla grid_id='{grid_id}', region='{region}', lata={years}."
                    )
                SYNTHETIC_USED.add("pogoda")
                self._generate_synthetic_weather(grid_id=grid_id, years=years)

        if overrides:
            self._apply_weather_overrides(unique_grids, overrides)

        daily_count = WeatherDaily.objects.filter(grid_id__in=unique_grids, date__year__in=years).count()
        hourly_count = WeatherHourly.objects.filter(grid_id__in=unique_grids, date__year__in=years).count()
        return (daily_count, hourly_count)

    def generate_forecast_series(self, grid_ids: list[str], start: date, end: date) -> int:
        """Generuje 7-dniowe prognozy (`WeatherForecastDaily`) dla każdego dnia `D` z zakresu `[start, end]`.

        Kopiuje wartości z `WeatherDaily` dla dni `D+1..D+7` i przenosi `imerg_total_precipitation`
        do `total_precipitation`, zgodnie z kontraktem `docs/database.md`.

        Args:
            grid_ids: Lista komórek siatki pogodowej.
            start: Pierwszy dzień emisji prognozy (`issued_on`).
            end: Ostatni dzień emisji prognozy (`issued_on`).

        Returns:
            Liczba utworzonych rekordów `WeatherForecastDaily`.
        """
        unique_grids = sorted(set(grid_ids))
        if not unique_grids:
            return 0

        shared_cols = [
            f.attname
            for f in DailyWeatherColumns._meta.concrete_fields
            if f.attname not in ("id", "grid_id", "issued_on", "date")
        ]

        WeatherForecastDaily.objects.filter(
            grid_id__in=unique_grids, issued_on__range=(start, end)
        ).delete()

        lookup_end = end + timedelta(days=7)
        forecast_rows: list[WeatherForecastDaily] = []

        for grid_id in unique_grids:
            observed_by_date = {
                row["date"]: row
                for row in WeatherDaily.objects.filter(grid_id=grid_id, date__range=(start, lookup_end)).values(
                    "date", *shared_cols, "imerg_total_precipitation"
                )
            }
            if not observed_by_date:
                continue

            current_day = start
            while current_day <= end:
                for offset in range(1, 8):
                    target_day = current_day + timedelta(days=offset)
                    src_row = observed_by_date.get(target_day)
                    if src_row is None:
                        continue

                    payload = {col: src_row[col] for col in shared_cols}
                    if payload.get("total_precipitation") is None:
                        payload["total_precipitation"] = src_row.get("imerg_total_precipitation")

                    forecast_rows.append(
                        WeatherForecastDaily(
                            grid_id=grid_id,
                            issued_on=current_day,
                            date=target_day,
                            **payload,
                        )
                    )
                current_day += timedelta(days=1)

        if forecast_rows:
            WeatherForecastDaily.objects.bulk_create(forecast_rows, batch_size=5000)
        return len(forecast_rows)

    def _try_load_grid_from_archives(self, grid_id: str, region: str, years: list[int]) -> bool:
        """Próbuje wczytać pogodę dzienną i godzinową z paczek ZIP w `DATA_DIR`."""
        dcols = {f.attname for f in WeatherDaily._meta.concrete_fields} - {"id"}
        hcols = {f.attname for f in WeatherHourly._meta.concrete_fields} - {"id"}

        for year in years:
            daily_zip = self._find_weather_zip("daily", year, region)
            hourly_zip = self._find_weather_zip("hourly", year, region)
            if daily_zip is None or hourly_zip is None:
                return False

            daily_df = self._read_parquet_from_zip(daily_zip, [grid_id])
            imerg_daily = self._read_imerg_parquet("daily", year, region, [grid_id])
            if not imerg_daily.empty:
                imerg_daily = imerg_daily.rename(columns={"total_precipitation": "imerg_total_precipitation"})[
                    ["grid_id", "date", "imerg_total_precipitation"]
                ]
                daily_df = daily_df.merge(imerg_daily, on=["grid_id", "date"], how="left")

            daily_df = daily_df[[c for c in daily_df.columns if c in dcols]]
            WeatherDaily.objects.bulk_create(
                [
                    WeatherDaily(**{k: (None if pd.isna(v) else v) for k, v in rec.items()})
                    for rec in daily_df.to_dict("records")
                ],
                batch_size=5000,
                ignore_conflicts=True,
            )

            hourly_df = self._read_parquet_from_zip(hourly_zip, [grid_id])
            imerg_hourly = self._read_imerg_parquet("hourly", year, region, [grid_id])
            if not imerg_hourly.empty:
                imerg_hourly = imerg_hourly.rename(columns={"precipitation": "imerg_precipitation"})[
                    ["grid_id", "utc_time", "imerg_precipitation"]
                ]
                hourly_df = hourly_df.merge(imerg_hourly, on=["grid_id", "utc_time"], how="left")

            utc_series = pd.to_datetime(hourly_df["utc_time"])
            if utc_series.dt.tz is None:
                utc_series = utc_series.dt.tz_localize("UTC")
            else:
                utc_series = utc_series.dt.tz_convert("UTC")
            hourly_df["utc_time"] = utc_series

            hourly_df = hourly_df[[c for c in hourly_df.columns if c in hcols]]
            WeatherHourly.objects.bulk_create(
                [
                    WeatherHourly(**{k: (None if pd.isna(v) else v) for k, v in rec.items()})
                    for rec in hourly_df.to_dict("records")
                ],
                batch_size=5000,
                ignore_conflicts=True,
            )

        return True

    def _find_weather_zip(self, cadence: str, year: int, region: str) -> Path | None:
        base = self.data_dir / "raw" / "weather_data" / cadence / str(year)
        for variant in _region_name_variants(region):
            candidate = base / f"weather_{cadence}_{year}_{variant}.zip"
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _read_parquet_from_zip(zip_path: Path, grid_ids: list[str]) -> pd.DataFrame:
        with zipfile.ZipFile(zip_path) as outer:
            names = [n for n in outer.namelist() if not n.startswith("__MACOSX")]
            pq_files = [n for n in names if n.endswith(".parquet")]
            if pq_files:
                return pd.read_parquet(io.BytesIO(outer.read(pq_files[0])), filters=[("grid_id", "in", grid_ids)])

            inner_zips = [n for n in names if n.endswith(".zip")]
            with zipfile.ZipFile(io.BytesIO(outer.read(inner_zips[0]))) as inner:
                inner_pq = [n for n in inner.namelist() if n.endswith(".parquet") and not n.startswith("__MACOSX")]
                return pd.read_parquet(io.BytesIO(inner.read(inner_pq[0])), filters=[("grid_id", "in", grid_ids)])

    def _read_imerg_parquet(self, kind: str, year: int, region: str, grid_ids: list[str]) -> pd.DataFrame:
        archive_path = self.data_dir / "raw" / "weather_data" / f"imerg_precipitation_{kind}.zip"
        if not archive_path.is_file():
            return pd.DataFrame()

        variants = _region_name_variants(region)
        with zipfile.ZipFile(archive_path) as outer:
            member_name = next(
                (
                    n
                    for n in outer.namelist()
                    if "__MACOSX" not in n
                    and any(n.endswith(f"precip_{kind}_{year}_{variant}.zip") for variant in variants)
                ),
                None,
            )
            if member_name is None:
                return pd.DataFrame()

            with zipfile.ZipFile(io.BytesIO(outer.read(member_name))) as inner:
                pq_files = [n for n in inner.namelist() if n.endswith(".parquet") and "__MACOSX" not in n]
                if not pq_files:
                    return pd.DataFrame()
                return pd.read_parquet(io.BytesIO(inner.read(pq_files[0])), filters=[("grid_id", "in", grid_ids)])

    @staticmethod
    def _generate_synthetic_weather(grid_id: str, years: list[int]) -> None:
        """Generuje deterministyczny, sezonowy szereg pogodowy (daily + hourly) dla trybu offline."""
        seed = int(hashlib.sha256(grid_id.encode("utf-8")).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)

        daily_rows: list[WeatherDaily] = []
        hourly_rows: list[WeatherHourly] = []

        for year in years:
            start_day = date(year, 1, 1)
            end_day = date(year, 12, 31)
            total_days = (end_day - start_day).days + 1

            for day_idx in range(total_days):
                current_day = start_day + timedelta(days=day_idx)
                doy = current_day.timetuple().tm_yday
                seasonal_temp = 9.5 + 11.5 * math.sin(2.0 * math.pi * (doy - 110) / 365.0)
                daily_noise = float(rng.normal(0.0, 2.2))
                avg_temp = round(seasonal_temp + daily_noise, 2)
                min_temp = round(avg_temp - 4.5, 2)
                max_temp = round(avg_temp + 5.0, 2)

                is_rainy = rng.random() < 0.28
                rain_mm = round(float(rng.exponential(5.5)), 2) if is_rainy else 0.0
                avg_rh = round(min(96.0, max(45.0, (84.0 if is_rainy else 66.0) + float(rng.normal(0.0, 6.0)))), 1)
                avg_wind = round(max(2.0, 11.0 + float(rng.normal(0.0, 3.5))), 2)
                solar_rad = round(max(2.0, (11.0 + 9.0 * math.sin(2.0 * math.pi * (doy - 80) / 365.0)) * (0.55 if is_rainy else 1.0)), 2)

                daily_rows.append(
                    WeatherDaily(
                        grid_id=grid_id,
                        date=current_day,
                        max_temperature=max_temp,
                        min_temperature=min_temp,
                        midpoint_temperature=round((min_temp + max_temp) / 2.0, 2),
                        avg_temperature=avg_temp,
                        max_dew_point_temperature=round(max_temp - 3.0, 2),
                        min_dew_point_temperature=round(min_temp - 1.5, 2),
                        avg_dew_point_temperature=round(avg_temp - 2.5, 2),
                        total_precipitation=None,
                        imerg_total_precipitation=rain_mm,
                        max_wind_speed=round(avg_wind * 1.4, 2),
                        min_wind_speed=round(avg_wind * 0.5, 2),
                        avg_wind_speed=avg_wind,
                        max_wind_speed_2m=round(avg_wind * 1.1, 2),
                        min_wind_speed_2m=round(avg_wind * 0.4, 2),
                        avg_wind_speed_2m=round(avg_wind * 0.78, 2),
                        max_relative_humidity=min(100.0, round(avg_rh + 12.0, 1)),
                        min_relative_humidity=max(25.0, round(avg_rh - 15.0, 1)),
                        avg_relative_humidity=avg_rh,
                        total_downward_solar_radiation=solar_rad,
                        max_downward_solar_radiation=round(solar_rad / 7.5, 3),
                        avg_soil_temperature_level_1=round(avg_temp * 0.9, 2),
                        avg_soil_moisture_level_1=0.28 if is_rainy else 0.21,
                        eto=round(max(0.4, solar_rad * 0.22), 2),
                        etr=round(max(0.5, solar_rad * 0.27), 2),
                        day_length=round(12.0 + 4.2 * math.sin(2.0 * math.pi * (doy - 80) / 365.0), 2),
                    )
                )

                hourly_rain = round(rain_mm / 6.0, 3) if rain_mm > 0 else 0.0
                for hour in range(24):
                    diurnal = math.sin(2.0 * math.pi * (hour - 8) / 24.0)
                    h_temp = round(avg_temp + 4.5 * diurnal, 2)
                    h_rh = round(min(100.0, max(30.0, avg_rh - 12.0 * diurnal)), 1)
                    h_precip = hourly_rain if 2 <= hour <= 7 else 0.0
                    hourly_rows.append(
                        WeatherHourly(
                            grid_id=grid_id,
                            # the hour of the local (Europe/Warsaw) day, like the organisers' packages
                            utc_time=datetime.combine(current_day, time(hour, 0), tzinfo=LOCAL_TZ).astimezone(timezone.utc),
                            date=current_day,
                            temperature=h_temp,
                            dew_point_temperature=round(h_temp - (100.0 - h_rh) / 5.0, 2),
                            precipitation=None,
                            imerg_precipitation=h_precip,
                            wind_speed=avg_wind,
                            wind_speed_2m=round(avg_wind * 0.78, 2),
                            relative_humidity=h_rh,
                            downward_solar_radiation=round(max(0.0, (solar_rad / 7.5) * diurnal), 3),
                            soil_temperature_level_1=round(avg_temp * 0.9, 2),
                            soil_moisture_level_1=0.28 if is_rainy else 0.21,
                            eto=round(max(0.0, (solar_rad * 0.22) / 12.0), 3),
                            etr=round(max(0.0, (solar_rad * 0.27) / 12.0), 3),
                        )
                    )

        WeatherDaily.objects.bulk_create(daily_rows, batch_size=5000, ignore_conflicts=True)
        WeatherHourly.objects.bulk_create(hourly_rows, batch_size=5000, ignore_conflicts=True)

    @staticmethod
    def _apply_weather_overrides(grid_ids: list[str], overrides: list[dict[str, Any]]) -> None:
        """
        Nadpisuje wybrane kolumny pogodowe dla zadanych przedziałów dat ze scenariusza.

        Godziny dostają przesunięcie, a nie stałą wartość: temperatura i wilgotność każdej godziny zmieniają się o
        różnicę między nową a starą średnią dobową (cykl dobowy zostaje), opad rozkłada się proporcjonalnie do
        godzin, w których padało (albo na 6 godzin nocnych). Stała 18,5 °C przez całą dobę wypadała poza zakres
        septoriozy (4-18 °C), więc "tydzień wybuchu" dawał zero godzin infekcji. Powtórne nałożenie tych samych
        wartości niczego nie zmienia (różnica wynosi 0).
        """
        valid_daily_cols = {f.attname for f in WeatherDaily._meta.concrete_fields} - {"id", "grid_id", "date"}

        for entry in overrides:
            start_str = entry.get("start_date") or entry.get("date")
            end_str = entry.get("end_date") or start_str
            values = entry.get("values")
            if not start_str or not isinstance(values, dict):
                continue
            start_d = date.fromisoformat(str(start_str))
            end_d = date.fromisoformat(str(end_str))
            filtered_values = {k: v for k, v in values.items() if k in valid_daily_cols and v is not None}
            if not filtered_values:
                continue

            for daily in WeatherDaily.objects.filter(grid_id__in=grid_ids, date__range=(start_d, end_d)):
                hours = list(WeatherHourly.objects.filter(grid_id=daily.grid_id, date=daily.date).order_by("utc_time"))
                changed: set[str] = set()
                if "avg_temperature" in filtered_values and daily.avg_temperature is not None:
                    delta = float(filtered_values["avg_temperature"]) - float(daily.avg_temperature)
                    for h in hours:
                        if h.temperature is not None:
                            h.temperature = round(h.temperature + delta, 2)
                            changed.add("temperature")
                    for col in ("min_temperature", "max_temperature"):
                        if col not in filtered_values and getattr(daily, col) is not None:
                            setattr(daily, col, round(getattr(daily, col) + delta, 2))
                if "avg_relative_humidity" in filtered_values and daily.avg_relative_humidity is not None:
                    delta = float(filtered_values["avg_relative_humidity"]) - float(daily.avg_relative_humidity)
                    for h in hours:
                        if h.relative_humidity is not None:
                            h.relative_humidity = round(min(100.0, max(0.0, h.relative_humidity + delta)), 1)
                            changed.add("relative_humidity")
                if "imerg_total_precipitation" in filtered_values and hours:
                    total = float(filtered_values["imerg_total_precipitation"])
                    wet = [h for h in hours if (h.imerg_precipitation or 0) > 0]
                    weights = [float(h.imerg_precipitation) for h in wet] if wet else []
                    if not wet:  # a dry day made wet: six night hours of rain
                        wet = hours[2:8] if len(hours) >= 8 else hours
                        weights = [1.0] * len(wet)
                    for h in hours:
                        h.imerg_precipitation = 0.0
                    s = sum(weights) or 1.0
                    for h, w in zip(wet, weights):
                        h.imerg_precipitation = round(total * w / s, 3)
                    changed.add("imerg_precipitation")
                for col, value in filtered_values.items():
                    setattr(daily, col, value)
                daily.save()
                if changed:
                    WeatherHourly.objects.bulk_update(hours, sorted(changed), batch_size=500)


class ObservationLoader:
    """Loader początkowych raportów rolnika (`core.Observation`) zdefiniowanych w scenariuszu."""

    def load_observations(self, specs: list[ObservationSpec], fields_by_name: dict[str, Field]) -> int:
        """Zapisuje obserwacje scenariusza w tabeli `core.Observation`.

        Args:
            specs: Lista specyfikacji obserwacji z definicji scenariusza.
            fields_by_name: Mapa `{Field.name: Field}` do powiązania raportów z polami.

        Returns:
            Liczba utworzonych rekordów `Observation`.

        Raises:
            ScenarioValidationError: Gdy obserwacja wskazuje nieistniejące pole lub nieznany `threat_code`.
        """
        if not specs:
            return 0

        rows: list[Observation] = []
        for idx, spec in enumerate(specs):
            field_obj: Field | None = None
            if spec.field_name is not None:
                field_obj = fields_by_name.get(spec.field_name)
                if field_obj is None:
                    raise ScenarioValidationError(
                        f"Obserwacja #{idx} wskazuje nieznane pole '{spec.field_name}'."
                    )

            threat_obj: Threat | None = None
            if spec.threat_code:
                threat_obj = Threat.objects.filter(code=spec.threat_code).first()
                if threat_obj is None:
                    raise ScenarioValidationError(
                        f"Obserwacja #{idx} odwołuje się do nieznanego zagrożenia '{spec.threat_code}'."
                    )

            rows.append(
                Observation(
                    field=field_obj,
                    observed_on=spec.observed_on,
                    kind=spec.kind,
                    category=spec.category,
                    threat=threat_obj,
                    severity=spec.severity,
                    distance_m=spec.distance_m,
                    details=dict(spec.details),
                    text=spec.text,
                    idempotency_key=f"scenario:{idx}:{spec.kind}:{spec.observed_on.isoformat()}",
                )
            )

        Observation.objects.bulk_create(rows)
        return len(rows)