import json
import re
import shutil
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.mask
import requests
from shapely.geometry import box

ROOT = Path(__file__).parent
URLS_FILE = ROOT / "cropland_urls.txt"
DATA_DIR = ROOT / "data"

NO_CROPLAND = 0
OUTSIDE_AREA = 65535
# Jedyne uprawy, które mogą trafić do crop_type. Pozostałe klasy (Other Cereals,
# Dry Pulses, Fresh Vegetables, Unclassified, No Cropland) dają null.
ACCEPTED_CROPS = {
    1110,  # Wheat
    1120,  # Barley
    1130,  # Maize
    1140,  # Rice
    1310,  # Potatoes
    1320,  # Sugar Beet
    1410,  # Sunflower
    1420,  # Soybeans
    1430,  # Rapeseed
    1440,  # Flax cotton and hemp
    2100,  # Grapes
    2200,  # Olives
    2310,  # Fruits
    2320,  # Nuts
}


class CropDetector:
    def __init__(
        self,
        year: int,
        min_share: float = 0.5,  # uprawa musi zająć więcej niż tyle pola
        min_candidate_share: float = 0.05,  # klasy poniżej tego udziału nie są możliwościami
        max_candidates: int = 3,
        urls_file: Path = URLS_FILE,
        data_dir: Path = DATA_DIR,
        verbose: bool = True,
    ):
        self.year = year
        self.min_share = min_share
        self.min_candidate_share = min_candidate_share
        self.max_candidates = max_candidates
        self.urls_file = Path(urls_file)
        self.data_dir = Path(data_dir)
        self.tiles_dir = self.data_dir / f"cropland_{year}"
        self.verbose = verbose
        self._start = time.perf_counter()
        self.legend: dict[int, str] = {}  # kod klasy -> nazwa

    def detect(self, fields_path: str | Path = ROOT / "fields.geojson") -> gpd.GeoDataFrame:
        """Pola z kolumnami crop_code, crop_type, crop_share i candidates.

        crop_type jest pusty, gdy dominująca klasa nie należy do ACCEPTED_CROPS
        albo nie zajmuje ponad min_share pola; wtedy candidates podaje
        najczęstsze klasy z udziałem w procentach.
        """
        self._start = time.perf_counter()
        fields = self.load_fields(fields_path)
        tiles = self._tiles(fields.total_bounds)
        self._log(f"analizuję {len(fields)} pól na {len(tiles)} kaflach")

        results = [self._classify(geom, tiles) for geom in fields.geometry]
        fields["crop_code"] = [r[0] for r in results]
        fields["crop_type"] = [r[1] for r in results]
        fields["crop_share"] = [r[2] for r in results]
        fields["candidates"] = [r[3] for r in results]
        found = fields["crop_type"].notna().sum()
        self._log(f"gotowe: typ uprawy dla {found}/{len(fields)} pól")
        return fields

    def download(self) -> Path:
        """Pobiera ZIP z rasterem dla self.year do data_dir."""
        url = self._url()
        path = self.data_dir / re.search(r"[^/]+\.zip", url).group(0)
        if path.exists():
            self._log(f"plik już pobrany: {path}")
            return path
        self.data_dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".zip.part")
        self._log(f"pobieram {path.name}")
        try:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with open(partial, "wb") as out:
                    shutil.copyfileobj(response.raw, out, length=1 << 20)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        partial.rename(path)
        self._log(f"zapisano {path} ({path.stat().st_size / 1e6:.0f} MB)")
        return path

    def load_fields(self, path: str | Path) -> gpd.GeoDataFrame:
        """Pola w EPSG:4326, tym samym układzie co raster."""
        fields = gpd.read_file(path).to_crs(4326)
        self._log(f"wczytano {len(fields)} pól z {path}")
        return fields

    def _url(self):
        pattern = re.compile(rf"cropland_\w+_{self.year}\.zip")
        urls = [line.strip() for line in self.urls_file.read_text().splitlines() if line.strip()]
        for url in urls:
            if pattern.search(url):
                return url
        years = sorted(re.search(r"_(\d{4})\.zip", u).group(1) for u in urls)
        raise ValueError(f"Brak danych dla roku {self.year}. Dostępne lata: {', '.join(years)}")

    def _tiles(self, bounds):
        """Ścieżki kafli przecinających bounds; brakujące pobiera i wypakowuje.

        index.json w tiles_dir trzyma zasięgi wszystkich kafli i legendę, więc
        ZIP jest potrzebny tylko wtedy, gdy brakuje któregoś kafla.
        """
        index_path = self.tiles_dir / "index.json"
        if index_path.exists():
            index = json.loads(index_path.read_text())
            needed = _intersecting(index["tiles"], bounds)
            if all((self.tiles_dir / name).exists() for name in needed):
                self._set_legend(index["legend"])
                return [self.tiles_dir / name for name in needed]

        archive = self.download()
        index = self._extract(archive, bounds)
        index_path.write_text(json.dumps(index, indent=1))
        archive.unlink()
        self._log(f"usunięto archiwum {archive.name}")
        self._set_legend(index["legend"])
        return [self.tiles_dir / name for name in _intersecting(index["tiles"], bounds)]

    def _extract(self, archive, bounds):
        """Wypakowuje do tiles_dir kafle przecinające bounds; zwraca indeks wszystkich kafli.

        Kafle w ZIP są skompresowane, a losowy odczyt przez /vsizip musiałby
        rozpakowywać je od początku, więc trafiają na dysk bez struktury katalogów z ZIP.
        """
        self.tiles_dir.mkdir(parents=True, exist_ok=True)
        tiles = {}
        with zipfile.ZipFile(archive) as zf:
            qml = next(n for n in zf.namelist() if n.endswith(".qml"))
            items = ET.fromstring(zf.read(qml)).iter("item")
            legend = {item.get("value"): item.get("label") for item in items}
            members = [n for n in zf.namelist() if n.endswith(".tif")]
            for name in members:
                with rasterio.open(f"/vsizip/{archive}/{name}") as src:
                    tiles[Path(name).name] = list(src.bounds)
            needed = _intersecting(tiles, bounds)
            if not needed:
                raise ValueError(f"Żaden kafel z {archive.name} nie pokrywa obszaru {list(bounds)}")
            for name in members:
                path = self.tiles_dir / Path(name).name
                if path.name in needed and not path.exists():
                    self._log(f"wypakowuję {path.name}")
                    with zf.open(name) as source, open(path, "wb") as target:
                        shutil.copyfileobj(source, target, length=1 << 20)
        return {"tiles": tiles, "legend": legend}

    def _set_legend(self, legend):
        # Starsze index.json trzymają [nazwa, kolor] — kolor był tylko do podglądu.
        self.legend = {
            int(code): (entry[0] if isinstance(entry, (list, tuple)) else entry)
            for code, entry in legend.items()
        }

    def _classify(self, geom, tiles):
        """(kod, nazwa, udział, możliwości) dla jednego poligonu."""
        counts = self._pixel_counts(geom, tiles)
        counts.pop(OUTSIDE_AREA, None)
        total = sum(counts.values())
        if total == 0:
            return None, None, 0.0, "brak danych"
        shares = sorted(((n / total, code) for code, n in counts.items()), reverse=True)

        share, code = shares[0]
        if code in ACCEPTED_CROPS and share > self.min_share:
            return code, self._name(code), round(share, 3), ""

        candidates = [
            f"{self._name(code)} {share:.0%}"
            for share, code in shares[: self.max_candidates]
            if share >= self.min_candidate_share
        ]
        return None, None, round(share, 3), ", ".join(candidates)

    def _pixel_counts(self, geom, tiles):
        """Liczba pikseli każdej klasy w poligonie, z kafla, który ma tam dane.

        Kafle zachodzą na siebie, a poza swoim zasięgiem mają 0 (jak "No
        Cropland"), bez wartości nodata. Sumowanie kafli dublowałoby pole
        z samymi zerami, więc wygrywa kafel z największą liczbą niezerowych pikseli.
        """
        best: dict[int, int] = {}
        for path in tiles:
            with rasterio.open(path) as src:
                if not box(*src.bounds).intersects(geom):
                    continue
                data, _ = rasterio.mask.mask(src, [geom], crop=True, filled=False)
            values, n = np.unique(data.compressed(), return_counts=True)
            counts = dict(zip(values.tolist(), n.tolist()))
            nonzero = sum(c for v, c in counts.items() if v not in (NO_CROPLAND, OUTSIDE_AREA))
            best_nonzero = sum(c for v, c in best.items() if v not in (NO_CROPLAND, OUTSIDE_AREA))
            if not best or nonzero > best_nonzero:
                best = counts
        return best

    def _name(self, code):
        return self.legend.get(code, f"klasa {code}")

    def _log(self, message):
        if self.verbose:
            print(f"[{time.perf_counter() - self._start:7.1f} s] {message}", flush=True)


def _intersecting(tiles, bounds):
    """Nazwy kafli (z indeksu nazwa -> [left, bottom, right, top]) przecinających bounds."""
    area = box(*bounds)
    return [name for name, tile_bounds in tiles.items() if box(*tile_bounds).intersects(area)]


if __name__ == "__main__":
    detector = CropDetector(year=2024)
    fields = detector.detect(ROOT / "fields.geojson")
    fields.drop(columns=["crop_type", "crop_share", "candidates"]).to_file(
        ROOT / "fields_crops.geojson"
    )
    print(fields["crop_type"].value_counts(dropna=False).to_string())
    unknown = fields[fields["crop_type"].isna()]
    for index, row in unknown.iterrows():
        print(f"pole {index} ({row['area_ha']:.1f} ha): możliwości: {row['candidates']}")
    print(f"Zapisano {len(fields)} pól do fields_crops.geojson")
