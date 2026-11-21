import duckdb
from pathlib import Path
import zipfile
import urllib.parse
import urllib.request
import geopandas as gpd
import tempfile
import shutil

def get_parquet(url: str, output_dir: str, keep_zip: bool = False):
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    filename = Path(urllib.parse.urlparse(url).path).name or "archive.zip"
    zip_path = out_path / filename
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_path)
    if not keep_zip:
        zip_path.unlink()
    return out_path


def get_presip(
    url: str | Path,
    year: int | str,
    voivodeship: str,
    output_dir: str | Path | None = None,
) -> list[Path]:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    year_str = str(year)
    voj_lower = voivodeship.lower()
    with tempfile.TemporaryDirectory() as tmp_dir:
        main_zip = Path(tmp_dir) / "archive.zip"
        urllib.request.urlretrieve(url, main_zip)

        with zipfile.ZipFile(main_zip, "r") as zf:
            valid_files = [
                m for m in zf.namelist()
                if not m.endswith("/")
                and not m.startswith("__MACOSX/")
                and not Path(m).name.startswith("._")
            ]

            matches = [
                m for m in valid_files
                if year_str in m and voj_lower in m.lower()
            ]

            if not matches:
                raise FileNotFoundError(
                    f"Nie znaleziono pliku dla {year} / {voivodeship}.\n"
                )
            target = matches[0]
            
            if target.endswith(".zip"):
                inner_zip = Path(zf.extract(target, tmp_dir))
                with zipfile.ZipFile(inner_zip, "r") as izf:
                    for im in izf.namelist():
                        if im.endswith("/") or im.startswith("__MACOSX/") or Path(im).name.startswith("._"):
                            continue
                        dest = out_path / Path(im).name
                        with izf.open(im) as src, open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        return dest

            dest = out_path / Path(target).name
            with zf.open(target) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)


def get_weather_df(grid_path, weather_path, boundary_path, precipitation_path, start_date, end_date, output_path, dir = "test"):
    grid = Path(f"{dir}/{grid_path}")
    weather = Path(f"{dir}/{weather_path}")
    boundary = Path(f"{dir}/{boundary_path}")
    precipitation = Path(f"{dir}/{precipitation_path}")

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    df = con.execute(f"""
        SELECT 
            w.avg_temperature,
            w.avg_soil_temperature_level_1,
            w.avg_soil_temperature_level_2,
            p.total_precipitation,
            w.date,
            g.lat,
            g.lon,
            g.geom AS geom
        FROM read_parquet('{weather}') AS w
        INNER JOIN (
            SELECT DISTINCT grid.*
            FROM read_parquet('{grid}') AS grid
            JOIN ST_Read('{boundary}') AS a
                ON ST_Within(grid.geom, a.geom)
        ) AS g
            ON w.grid_id = g.grid_id
        INNER JOIN read_parquet('{precipitation}') AS p
            ON g.grid_id = p.grid_id AND w.date = p.date
        WHERE w.date BETWEEN DATE '{start_date}' AND DATE '{end_date}';

    """).df()
    gdf = gpd.GeoDataFrame(df.drop(columns = ["geom"]), geometry = gpd.GeoSeries.from_wkb([bytes(g) for g in df["geom"]]), crs="EPSG:4326")

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out_file, index=False)
    return gdf

