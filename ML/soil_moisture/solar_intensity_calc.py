"""Report solar exposure for the last completed day over the project's fields."""

import argparse
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import azimuth, zenith

if __package__:
    from .field_geometry import read_field_features
    from .open_meteo import (
        ARCHIVE_URL,
        DAY,
        FORECAST_URL,
        HOUR,
        UTC,
        WeatherError,
        load_hourly_weather,
    )
    from .project_config import earth_engine_project
else:
    from field_geometry import read_field_features
    from open_meteo import (
        ARCHIVE_URL,
        DAY,
        FORECAST_URL,
        HOUR,
        UTC,
        WeatherError,
        load_hourly_weather,
    )
    from project_config import earth_engine_project

WARSAW = ZoneInfo("Europe/Warsaw")
RADIATION_BAND = "shortwave_radiation"
LEVEL_THRESHOLDS = [(0.85, "excellent"), (0.65, "good"), (0.35, "moderate")]


def field_bounds(path=None):
    fields = read_field_features(path)
    points = []
    for field in fields:
        geometry = field["geometry"]
        polygons = geometry["coordinates"]
        if geometry["type"] == "Polygon":
            polygons = [polygons]
        points.extend(position[:2] for polygon in polygons for position in polygon[0])
    if not points:
        raise ValueError("Brak współrzędnych pól.")
    longitude, latitude = zip(*points, strict=True)
    return min(longitude), min(latitude), max(longitude), max(latitude)


def completed_day_hours(day):
    start = datetime.combine(day, time.min, WARSAW).astimezone(UTC)
    end = datetime.combine(day + DAY, time.min, WARSAW).astimezone(UTC)
    return [start + index * HOUR for index in range(1, (end - start) // HOUR + 1)]


def reference_energy(observer, hours):
    # Haurwitz clear-sky irradiance, integrated at the midpoint of each 15-minute interval.
    radiation = 0.0
    for end in hours:
        for offset_minutes in (52.5, 37.5, 22.5, 7.5):
            stamp = end - timedelta(minutes=offset_minutes)
            cosine = math.cos(math.radians(zenith(observer, stamp)))
            if cosine > 0:
                radiation += 0.25 * 1098 * cosine * math.exp(-0.059 / cosine)
    return radiation


def weather_energy(observer, hours):
    dates = {
        "start_date": (hours[0] - HOUR).date().isoformat(),
        "end_date": hours[-1].date().isoformat(),
    }
    last_error = None
    for url, source in (
        (ARCHIVE_URL, "archiwum pogody Open-Meteo"),
        (FORECAST_URL, "archiwalna prognoza Open-Meteo"),
    ):
        try:
            values = load_hourly_weather(
                url,
                (observer.longitude, observer.latitude),
                (RADIATION_BAND,),
                timeout=(5, 25),
                **dates,
            )
            # Open-Meteo timestamps each hourly mean at the end of its interval.
            return sum(max(0, values[stamp][0]) for stamp in hours), source
        except (WeatherError, KeyError) as error:
            last_error = error
    raise ValueError(
        "Open-Meteo nie udostępniło pełnych danych o promieniowaniu za tę dobę."
    ) from last_error


def solar_summary(day, observer):
    hours = completed_day_hours(day)
    actual, source = weather_energy(observer, hours)
    return summarize_energy(day, observer, hours, actual, source)


def summarize_energy(day, observer, hours, actual, source):
    reference = reference_energy(observer, hours)
    if reference <= 0:
        raise ValueError("Brak dodatniego promieniowania referencyjnego za tę dobę.")
    ratio = actual / reference
    level = next(
        (name for threshold, name in LEVEL_THRESHOLDS if ratio >= threshold), "poor"
    )
    return {
        "date_local": day.isoformat(),
        "timezone": "Europe/Warsaw",
        "energy_kwh_m2": actual / 1000,
        "clear_sky_kwh_m2": reference / 1000,
        "clear_sky_fraction": ratio,
        "level": level,
        "source": source,
    }


def report(day, observer):
    summary = solar_summary(day, observer)
    actual = summary["energy_kwh_m2"]
    reference = summary["clear_sky_kwh_m2"]
    ratio = summary["clear_sky_fraction"]
    level = summary["level"]
    source = summary["source"]
    print(f"Nasłonecznienie pól za {day.isoformat()} (Europe/Warsaw): {level}")
    print(f"Pogoda: {actual:.2f} kWh/m² | Bezchmurne niebo: {reference:.2f} kWh/m²")
    print(f"Osiągnięto {ratio:.0%} wartości referencyjnej. Źródło: {source}.")
    limits = ", ".join(
        f"{name} od {reference * threshold:.2f}"
        for threshold, name in reversed(LEVEL_THRESHOLDS)
    )
    print(f"Progi dla tej doby (kWh/m²): {limits}")


def export_terrain_rasters(project, bounds, day, observer):
    import ee
    import geemap

    try:
        ee.Initialize(project=project)
        area = ee.Geometry.Rectangle(bounds, proj="EPSG:4326", geodesic=False)
        elevation = ee.Image("USGS/SRTMGL1_003").select("elevation")
        slope = ee.Terrain.slope(elevation).rename("slope")
        aspect = ee.Terrain.aspect(elevation).rename("exposition")
        slope_rad = slope.multiply(math.pi / 180)
        aspect_rad = aspect.multiply(math.pi / 180)
        solar_images = []
        for end in completed_day_hours(day):
            stamp = end - HOUR / 2
            zenith_degrees = zenith(observer, stamp, with_refraction=False)
            if zenith_degrees >= 90:
                continue
            zenith_rad = math.radians(zenith_degrees)
            azimuth_rad = math.radians(azimuth(observer, stamp))
            incidence = (
                slope_rad.cos()
                .multiply(math.cos(zenith_rad))
                .add(
                    slope_rad.sin()
                    .multiply(math.sin(zenith_rad))
                    .multiply(aspect_rad.subtract(azimuth_rad).cos())
                )
            )
            solar_images.append(incidence.max(0).multiply(1361))

        solar_energy = (
            ee.ImageCollection.fromImages(solar_images).sum().rename("solar_Wh_m2")
        )
        for image, filename in (
            (aspect, "ESPOSITION_30m.tif"),
            (slope, "SLOPE_30m.tif"),
            (elevation, "SRTM_30m.tif"),
            (solar_energy, "SOLAR_30m.tif"),
        ):
            geemap.ee_export_image(
                image,
                filename=filename,
                scale=30,
                region=area,
                crs="EPSG:2180",
                file_per_band=False,
            )
    except ee.EEException as error:
        raise ValueError(f"Earth Engine: {error}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Completed day YYYY-MM-DD. Default: yesterday.",
    )
    parser.add_argument(
        "--fields-geojson",
        type=Path,
        help="Optional WGS 84 GeoJSON override. By default read geometry from MongoDB Orchard.",
    )
    parser.add_argument(
        "--export-rasters",
        action="store_true",
        help="Also export the four terrain GeoTIFFs via GEE.",
    )
    parser.add_argument(
        "--project", help="Override the configured Google Cloud project."
    )
    args = parser.parse_args()
    today = datetime.now(WARSAW).date()
    day = args.date or today - DAY
    if day >= today:
        parser.error("Raport wymaga zakończonej doby w strefie Europe/Warsaw.")
    try:
        project = earth_engine_project(args.project) if args.export_rasters else None
        bounds = field_bounds(args.fields_geojson)
        west, south, east, north = bounds
        observer = Observer(latitude=(south + north) / 2, longitude=(west + east) / 2)
        report(day, observer)
        if project is not None:
            export_terrain_rasters(project, bounds, day, observer)
    except (KeyError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
