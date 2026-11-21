"""Pobieranie granic pól FTW (GeoParquet) i zapis do GeoJSON.

Siatka kafli:
https://data.source.coop/ftw/global-field-boundaries/download-tiles/ftw-download-grid-v2.geojson
Z features bierzemy id. Plik kafla:
https://data.source.coop/ftw/global-field-boundaries/download-tiles/geoparquet/{year}/{year}_{id}.parquet

    fields = FieldsDownloader([15.697633, 52.584850, 15.845633, 52.674830], year=2024)
    fields.download()
    fields.save("data/fields.geojson")
    fields.cleanup()
"""

import shutil
import time
from pathlib import Path

import duckdb
import geopandas as gpd
import requests
from shapely import from_wkb

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data" / "fields"
GRID_URL = (
    "https://data.source.coop/ftw/global-field-boundaries/download-tiles/"
    "ftw-download-grid-v2.geojson"
)
PARQUET_URL = (
    "https://data.source.coop/ftw/global-field-boundaries/download-tiles/"
    "geoparquet/{year}/{year}_{tile_id}.parquet"
)


class FieldsDownloader:
    """Pola FTW przycięte do bbox, ten sam zapis co FieldsClassificatorResult.save."""

    def __init__(
        self,
        bbox: list[float],
        year: int = 2024,
        data_dir: Path = DATA_DIR,
        verbose: bool = False,
    ):
        """bbox = [min_lon, min_lat, max_lon, max_lat] w WGS84."""
        self.bbox = bbox
        self.year = year
        self.data_dir = Path(data_dir)
        self.verbose = verbose
        self.fields: gpd.GeoDataFrame | None = None
        self._start = time.perf_counter()

    def download(self) -> gpd.GeoDataFrame:
        """Kafle przecinające bbox, potem poligony ucięte dokładnie do bbox.

        Zostaje kolumna area_ha (hektary, układ UTM), jak w fields.geojson.
        """
        self._start = time.perf_counter()
        paths = self._download_tiles()
        clipped = self._clip(paths)
        self.fields = clipped
        self._log(f"po przycięciu: {len(clipped)} pól")
        return clipped

    def save(self, path: str) -> None:
        """Zapisuje poligony w WGS84; format wynika z rozszerzenia (.geojson, .gpkg, .shp)."""
        if self.fields is None:
            self.download()
        self.fields.to_crs(4326).to_file(path)
        self._log(f"zapisano {len(self.fields)} pól do {path}")

    def cleanup(self) -> None:
        """Usuwa pobrane kafle. GeoJSON z save() leży obok, w data/, nie w tym folderze."""
        if not self.data_dir.exists():
            return
        shutil.rmtree(self.data_dir)
        self._log(f"usunięto {self.data_dir}")

    def _download_tiles(self) -> list[Path]:
        """Ściąga tylko kafle 1°, których kwadrat przecina bbox."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._log("pobieram siatkę kafli")
        response = requests.get(GRID_URL, timeout=120)
        response.raise_for_status()
        features = response.json()["features"]
        tiles = [feature for feature in features if self._tile_hits(feature)]
        if not tiles:
            raise ValueError(f"Żaden kafel nie pokrywa bbox {self.bbox} w roku {self.year}")
        self._log(f"kafle w zasięgu: {len(tiles)} / {len(features)}")

        paths = []
        for feature in tiles:
            if self.year not in feature["properties"]["years"]:
                continue
            tile_id = feature["id"]
            path = self.data_dir / f"{self.year}_{tile_id}.parquet"
            paths.append(self._fetch(PARQUET_URL.format(year=self.year, tile_id=tile_id), path))
        if not paths:
            raise ValueError(f"Brak kafli z rokiem {self.year} dla bbox {self.bbox}")
        return paths

    def _clip(self, paths: list[Path]) -> gpd.GeoDataFrame:
        """DuckDB czyta parquet i zwraca tylko poligony ucięte do bbox."""
        min_lon, min_lat, max_lon, max_lat = self.bbox
        con = duckdb.connect()
        con.execute("INSTALL spatial; LOAD spatial;")
        rows = con.execute(
            """
            WITH env AS (SELECT ST_MakeEnvelope(?, ?, ?, ?) AS geom)
            SELECT ST_AsWKB(piece)
            FROM (
                SELECT unnest(ST_Dump(ST_Intersection(p.geometry, env.geom))).geom AS piece
                FROM read_parquet(?) p, env
                WHERE ST_Intersects(p.geometry, env.geom)
            )
            WHERE NOT ST_IsEmpty(piece)
              AND ST_GeometryType(piece) IN ('POLYGON', 'MULTIPOLYGON')
            """,
            [min_lon, min_lat, max_lon, max_lat, [str(path) for path in paths]],
        ).fetchall()
        con.close()
        geometries = [from_wkb(row[0]) for row in rows]
        clipped = gpd.GeoDataFrame(geometry=geometries, crs=4326)
        if clipped.empty:
            return gpd.GeoDataFrame({"area_ha": []}, geometry=[], crs=4326)
        clipped["area_ha"] = clipped.to_crs(clipped.estimate_utm_crs()).area / 10_000
        return clipped[["area_ha", "geometry"]]

    def _tile_hits(self, feature) -> bool:
        lat = feature["properties"]["lat_min"]
        lon = feature["properties"]["lon_min"]
        min_lon, min_lat, max_lon, max_lat = self.bbox
        return lon < max_lon and lon + 1 > min_lon and lat < max_lat and lat + 1 > min_lat

    def _fetch(self, url, path: Path) -> Path:
        if path.exists() and path.stat().st_size > 0:
            self._log(f"plik już pobrany: {path.name}")
            return path
        partial = path.with_suffix(".parquet.part")
        self._log(f"pobieram {path.name}")
        try:
            with requests.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(partial, "wb") as out:
                    shutil.copyfileobj(response.raw, out, length=1 << 20)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        partial.rename(path)
        self._log(f"zapisano {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
        return path

    def _log(self, message):
        if self.verbose:
            print(f"[{time.perf_counter() - self._start:7.1f} s] {message}", flush=True)


if __name__ == "__main__":
    downloader = FieldsDownloader([15.697633, 52.584850, 15.845633, 52.674830], year=2024)
    downloader.download()
    downloader.save(ROOT / "data" / "fields.geojson")
    downloader.cleanup()
