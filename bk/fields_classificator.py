"""Wykrywanie pól uprawnych na zdjęciach Sentinel-2.

Inferencja jak w fields-of-the-planet (eval): okno B, potem okno A, dzielenie
przez 3000, uśrednienie 8 odbić obrazu (D4 TTA) i argmax 3 klas.
Sąsiednie pola o innym kolorze rozcina próg zmiany NDVI.
Model PlanetScope z tego repo wymaga płatnych zdjęć, więc wagi są z bliźniaczej
konfiguracji Sentinel-2: FTW v3, U-Net + EfficientNet-B3
(github.com/fieldsoftheworld/ftw-baselines).
Dane: Sentinel-2 L2A z Element 84 Earth Search (bez konta AWS).

    result = FieldsClassificator(year=2025).generate([17.66, 50.34, 17.76, 50.40])
    result.simplify(15).save("fields.geojson")
"""

import os
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # zapis do pliku, bez okna

# Musi być ustawione PRZED importem rasterio (publiczny odczyt COG z AWS)
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
# Zerwane połączenie z S3 kończy się błędem zamiast wiecznego czekania
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import rasterio.features
import segmentation_models_pytorch as smp
import torch
from pystac_client import Client
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from scipy.ndimage import binary_dilation, distance_transform_edt, find_objects, label
from shapely.geometry import MultiPolygon, Polygon, box, shape

STAC_URL = "https://earth-search.aws.element84.com/v1"
MODEL_URL = "https://github.com/fieldsoftheworld/ftw-baselines/releases/download/v3.1/prue_efnetb3_ccby_checkpoint.ckpt"
BANDS = ["red", "green", "blue", "nir"]
MAX_SIZE_PX = 2048  # największy bok obszaru (ok. 20 km przy pikselu 10 m)
TMP_DIR = Path(__file__).parent / "tmp"


class FieldsClassificatorResult:
    """Wykryte pola: `fields` to GeoDataFrame z poligonami w UTM (metry)."""

    def __init__(self, fields: gpd.GeoDataFrame, scenes: list[str], image: np.ndarray, transform):
        self.fields = fields
        self.scenes = scenes  # identyfikatory użytych scen Sentinel-2
        self._image = image  # (8, H, W): dwie sceny x red, green, blue, nir
        self._transform = transform  # piksel -> metry UTM

    def simplify(self, tolerance_m: float = 15.0) -> "FieldsClassificatorResult":
        """Domknięcie wcięć: bufor +d i -d w metrach (układ UTM sceny).

        Wcięcie węższe niż 2 * tolerance_m znika, bo ścianki schodzą się przy
        rozszerzaniu. join_style=2 (mitre) zostawia ostre narożniki pola.
        """
        fields = self.fields.copy()
        closed = fields.geometry.buffer(tolerance_m, join_style=2).buffer(-tolerance_m, join_style=2)
        fields.geometry = closed
        fields = fields[~closed.is_empty & closed.is_valid].reset_index(drop=True)
        fields["area_ha"] = fields.area / 10_000
        return FieldsClassificatorResult(fields, self.scenes, self._image, self._transform)

    def save(self, path: str) -> None:
        """Zapisuje poligony w WGS84; format wynika z rozszerzenia (.geojson, .gpkg, .shp)."""
        self.fields.to_crs(4326).to_file(path)

    def plot(self, path: str, dpi: int = 150) -> None:
        """Granice pól nałożone na zdjęcia obu scen (red, green, blue), obok siebie."""
        _, h, w = self._image.shape
        # Zasięg w metrach: imshow liczy y od góry, więc y1 (północ) jest pierwsze
        x0, y1 = self._transform * (0, 0)
        x1, y0 = self._transform * (w, h)

        fig, axes = plt.subplots(1, 2, figsize=(w / dpi * 2, h / dpi), dpi=dpi)
        for ax, scene, title in zip(axes, (0, 4), ("początek sezonu", "koniec sezonu")):
            rgb = self._image[scene : scene + 3].transpose(1, 2, 0)
            lo, hi = np.percentile(rgb, 2), np.percentile(rgb, 98)
            ax.imshow(np.clip((rgb - lo) / (hi - lo), 0, 1), extent=(x0, x1, y0, y1))
            self.fields.boundary.plot(ax=ax, color="yellow", linewidth=0.4)
            ax.set_title(f"{title}\n{self.scenes[scene // 4]}", fontsize=8)
            ax.set_axis_off()
        fig.tight_layout()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path)
        plt.close(fig)


class FieldsClassificator:
    def __init__(
        self,
        year: int = 2025,
        early: tuple[str, str] = ("04-01", "05-31"),  # początek sezonu (MM-DD)
        late: tuple[str, str] = ("08-15", "10-15"),  # koniec sezonu (MM-DD)
        max_cloud: float = 20,  # maks. zachmurzenie sceny w %
        min_area_m2: float = 30_000,  # 3 ha; mniejsze poligony są odrzucane
        ndvi_edge: float = 0.12,  # cięcie, gdy NDVI zmienia się o tyle na jednym pikselu; 0 wyłącza
        model_url: str = MODEL_URL,
        verbose: bool = True,
    ):
        self.verbose = verbose
        self._start = time.perf_counter()
        self.year = year
        self.early = early
        self.late = late
        self.max_cloud = max_cloud
        self.min_area_m2 = min_area_m2
        self.ndvi_edge = ndvi_edge
        self.model_url = model_url
        self._model = None

    def generate(self, boundingbox: list[float]) -> FieldsClassificatorResult:
        """boundingbox = [min_lon, min_lat, max_lon, max_lat] w WGS84."""
        self._start = time.perf_counter()
        self._log(f"bbox {boundingbox}")
        scenes = self._find_scenes(boundingbox)
        self._log(f"sceny: {[s.id for s in scenes]}")
        image, transform, crs = self._read(scenes, boundingbox)
        self._log(f"obraz {image.shape[2]}x{image.shape[1]} px, {crs}")
        classes = self._predict(image)
        fields = self._polygonize(classes, image, transform, crs)
        self._log(f"gotowe: {len(fields)} pól")
        return FieldsClassificatorResult(fields, [s.id for s in scenes], image, transform)

    def _log(self, message):
        if self.verbose:
            print(f"[{time.perf_counter() - self._start:7.1f} s] {message}", flush=True)

    def _search(self, bbox, dates):
        """Sceny z danego okna dat, które w całości pokrywają bbox."""
        self._log(f"szukam scen {self.year}-{dates[0]} .. {self.year}-{dates[1]} w Earth Search")
        search = Client.open(STAC_URL, timeout=60).search(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime=f"{self.year}-{dates[0]}/{self.year}-{dates[1]}",
            query={"eo:cloud_cover": {"lt": self.max_cloud}},
        )
        return [i for i in search.items() if shape(i.geometry).contains(box(*bbox))]

    def _find_scenes(self, bbox):
        """Najmniej zachmurzona para scen (wczesna, późna) z tego samego kafla."""
        early, late = self._search(bbox, self.early), self._search(bbox, self.late)
        pairs = [
            (a, b)
            for a in early
            for b in late
            if a.properties["grid:code"] == b.properties["grid:code"]
        ]
        if not pairs:
            raise ValueError(
                f"Brak pary scen Sentinel-2 pokrywających bbox w roku {self.year} "
                f"(wczesnych: {len(early)}, późnych: {len(late)}). "
                "Poszerz zakresy dat, zwiększ max_cloud albo zmniejsz bbox."
            )
        return min(pairs, key=lambda p: sum(s.properties["eo:cloud_cover"] for s in p))

    def _read(self, scenes, bbox):
        """Wycina bbox z obu scen: tablica (8, H, W) = 2 sceny x 4 pasma."""
        with rasterio.open(scenes[0].assets[BANDS[0]].href) as src:
            crs = src.crs
            w = from_bounds(*transform_bounds("EPSG:4326", crs, *bbox), transform=src.transform)
            window = Window(round(w.col_off), round(w.row_off), round(w.width), round(w.height))
            window = window.intersection(Window(0, 0, src.width, src.height))
            transform = src.window_transform(window)
        if max(window.width, window.height) > MAX_SIZE_PX:
            raise ValueError(
                f"Obszar {window.width}x{window.height} px jest za duży "
                f"(limit {MAX_SIZE_PX} px, ok. {MAX_SIZE_PX // 100} km). Zmniejsz bbox."
            )
        layers = []
        for scene in scenes:
            # Nowsze przetworzenia (baseline >= 04.00) mają wartości zawyżone o 1000,
            # chyba że Earth Search już to skorygował.
            props = scene.properties
            offset = (
                1000
                if float(props["s2:processing_baseline"]) >= 4
                and not props.get("earthsearch:boa_offset_applied")
                else 0
            )
            for band in BANDS:
                self._log(f"pobieram {scene.id} / {band}")
                with rasterio.open(scene.assets[band].href) as src:
                    data = src.read(1, window=window).astype(np.float32)
                layers.append(np.clip(data - offset, 0, None))
        return np.stack(layers), transform, crs

    def _load_model(self):
        path = Path(__file__).parent / "models" / self.model_url.rsplit("/", 1)[-1]
        if not path.exists():
            self._log(f"pobieram wagi modelu do {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            torch.hub.download_url_to_file(self.model_url, str(path))
        ckpt = torch.load(path, map_location="cpu", weights_only=True)
        hp = ckpt["hyper_parameters"]
        model = smp.Unet(
            encoder_name=hp["backbone"],
            encoder_weights=None,
            in_channels=hp["in_channels"],
            classes=hp["num_classes"],
        )
        model.load_state_dict(
            {
                k.removeprefix("model."): v
                for k, v in ckpt["state_dict"].items()
                if k.startswith("model.")
            }
        )
        return model.eval()

    @torch.inference_mode()
    def _predict(self, image):
        """Klasa każdego piksela: 0 = tło, 1 = pole, 2 = granica pola.

        Wejście modelu to okno B (koniec sezonu), potem okno A (początek), tak
        jak w ftw_planet.datasets. Predykcja jest średnią z 8 odbić i obrotów.
        """
        if self._model is None:
            self._model = self._load_model()
        device = (
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        ordered = np.concatenate([image[4:], image[:4]], axis=0)
        h, w = ordered.shape[1:]
        # Boki podzielne przez 32 i nie mniejsze niż 512, jak pad_to_min w eval
        pad_h = max(-(-h // 32) * 32, 512) - h
        pad_w = max(-(-w // 32) * 32, 512) - w
        x = torch.nn.functional.pad(torch.from_numpy(ordered / 3000)[None], (0, pad_w, 0, pad_h))
        x = x.to(device)
        model = self._model.to(device)
        total = None
        for step, (forward, inverse) in enumerate(_d4_pairs(), 1):
            self._log(f"model na {device}: przebieg {step}/8")
            probs = inverse(model(forward(x)).softmax(dim=1))
            total = probs if total is None else total + probs
        # Na GPU przebiegi są kolejkowane, faktyczne liczenie czeka tutaj
        classes = (total / 8).argmax(dim=1)[0, :h, :w].cpu().numpy()
        self._log("model skończył")
        return classes

    def _polygonize(self, classes, image, transform, crs):
        """Każdy spójny obszar klasy "pole" staje się poligonem.

        Sąsiednie pola o innym kolorze model często skleja, bo nie stawia między
        nimi klasy "granica". Dodatkowe cięcie idzie wzdłuż ostrej zmiany NDVI
        na początku albo na końcu sezonu.
        """
        model_field = classes == 1
        field = model_field
        min_px = self.min_area_m2 / transform.a**2
        if self.ndvi_edge > 0 and field.any():
            edges = _color_edges(image)
            field = field & (edges < self.ndvi_edge)
            # Słabsza granica koloru rozcina pole tylko wtedy, gdy obie części
            # zostają większe niż min_area. Inaczej niższy próg kruszy pola.
            field = _split_joined_fields(field, edges, min_px, seam=self.ndvi_edge * 0.67)
        instances = label(field)[0].astype(np.int32)
        self._log(f"łączę fragmenty ({instances.max()} obszarów)")
        instances = _regrow(instances, model_field)
        instances = _merge_small(instances, min_px)
        self._log("wektoryzacja")
        shapes = rasterio.features.shapes(instances, mask=instances > 0, transform=transform)
        fields = gpd.GeoDataFrame(
            geometry=[_drop_holes(shape(geom)) for geom, _ in shapes], crs=crs
        )
        fields = fields[fields.area >= self.min_area_m2].reset_index(drop=True)
        fields["area_ha"] = fields.area / 10_000
        return fields


def _color_edges(image):
    """Największa zmiana NDVI albo zieleni względem czerwieni, na obu datach."""
    edges = np.zeros(image.shape[1:], np.float32)
    for left, right in ((3, 0), (7, 4), (1, 0), (5, 4)):
        value = (image[left] - image[right]) / np.maximum(image[left] + image[right], 1)
        gy, gx = np.gradient(value)
        edges = np.maximum(edges, np.hypot(gx, gy))
    return edges


def _split_joined_fields(field, edges, min_px, seam):
    """Rozcina poligon, w którym dwa duże obszary rozdziela zmiana koloru."""
    out = field.copy()
    components = label(field)[0]
    for index, area in enumerate(np.bincount(components.ravel())):
        if index == 0 or area < 2 * min_px:
            continue
        region = components == index
        # Pogrubienie o piksel zamyka szczelinę, przez którą dwa pola zostają sklejone
        wall = binary_dilation(region & (edges >= seam))
        pieces = label(region & ~wall)[0]
        counts = np.bincount(pieces.ravel())
        counts[0] = 0
        if len(counts) < 3 or np.sort(counts)[-2] < min_px:
            continue
        largest, second = np.argsort(counts)[-2:]
        between = binary_dilation(pieces == largest) & binary_dilation(pieces == second)
        out[region & wall & between] = False
    return out


def _regrow(instances, field, max_px=3):
    """Oddaje piksele wycięte na granicach koloru najbliższemu polu."""
    distance, (rows, cols) = distance_transform_edt(instances == 0, return_indices=True)
    gap = field & (instances == 0) & (distance <= max_px)
    out = instances.copy()
    out[gap] = instances[rows[gap], cols[gap]]
    return out


def _merge_small(instances, min_px):
    """Dokleja fragmenty mniejsze niż min_px do sąsiada o najdłuższej wspólnej krawędzi."""
    instances = instances.copy()
    areas = np.bincount(instances.ravel())
    boxes = [None] + find_objects(instances)
    for index in np.argsort(areas):
        if index == 0 or not 0 < areas[index] < min_px:
            continue
        rows, cols = boxes[index]
        window = (
            slice(max(rows.start - 1, 0), rows.stop + 1),
            slice(max(cols.start - 1, 0), cols.stop + 1),
        )
        part = instances[window]
        region = part == index
        neighbours = part[binary_dilation(region) & ~region]
        neighbours = neighbours[neighbours > 0]
        if neighbours.size == 0:
            continue
        target = np.bincount(neighbours).argmax()
        part[region] = target
        areas[target] += areas[index]
        areas[index] = 0
        boxes[target] = tuple(
            slice(min(a.start, b.start), max(a.stop, b.stop)) for a, b in zip(boxes[target], (rows, cols))
        )
    return instances


def _drop_holes(geom):
    """Zostawia obrys zewnętrzny. Koła nawadniania nie wycinają dziur w polu."""
    if geom.geom_type == "Polygon":
        return Polygon(geom.exterior)
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([Polygon(part.exterior) for part in geom.geoms])
    return geom


def _d4_pairs():
    """Osiem przekształceń D4 i ich odwrotności, jak _d4_transforms w repo."""

    def rot90(tensor):
        return torch.rot90(tensor, 1, dims=(-2, -1))

    def rot270(tensor):
        return torch.rot90(tensor, 3, dims=(-2, -1))

    return [
        (lambda tensor: tensor, lambda tensor: tensor),
        (lambda tensor: torch.flip(tensor, dims=(-1,)), lambda tensor: torch.flip(tensor, dims=(-1,))),
        (lambda tensor: torch.flip(tensor, dims=(-2,)), lambda tensor: torch.flip(tensor, dims=(-2,))),
        (
            lambda tensor: torch.flip(tensor, dims=(-2, -1)),
            lambda tensor: torch.flip(tensor, dims=(-2, -1)),
        ),
        (rot90, rot270),
        (rot270, rot90),
        (
            lambda tensor: torch.flip(rot90(tensor), dims=(-1,)),
            lambda tensor: rot270(torch.flip(tensor, dims=(-1,))),
        ),
        (
            lambda tensor: torch.flip(rot90(tensor), dims=(-2,)),
            lambda tensor: rot270(torch.flip(tensor, dims=(-2,))),
        ),
    ]


if __name__ == "__main__":
    result = FieldsClassificator(year=2024, min_area_m2=30_000, ndvi_edge=0.12).generate(
        [15.697633, 52.584850, 15.845633, 52.674830]
    )
    result = result.simplify(30)
    result.save("fields.geojson")
    result.plot(TMP_DIR / "fields_preview.png")
    print(f"Sceny: {result.scenes}")
    print(f"Zapisano {len(result.fields)} pól do fields.geojson i tmp/fields_preview.png")

    result2 = FieldsClassificator(year=2024, min_area_m2=30_000, ndvi_edge=0.12).generate(
        [22.155178, 51.438826, 22.299418, 51.528806]
    )
    result2 = result2.simplify(30)
    result2.save("fields2.geojson")
    result2.plot(TMP_DIR / "fields_preview2.png")
    print(f"Sceny: {result2.scenes}")
    print(f"Zapisano {len(result2.fields)} pól do fields2.geojson i tmp/fields_preview2.png")
