"""Make the Terranos logo variants used by the GUI and the showcase from images/terranos.png.

The source PNG has faint speckle noise in its transparent background (alpha 1-31), which shows up on
dark backgrounds. This script removes it, trims the logo, and writes:

  web/public/terranos.png            wordmark for light backgrounds (GUI header)
  web/public/terranos-globe.png      the globe from the "o", square (favicon)
  showcase/brand/terranos.png        wordmark for light backgrounds
  showcase/brand/terranos-dark.png   wordmark with light letters, for dark backgrounds (deck, video)
  showcase/brand/terranos-globe.png  the globe, square
  showcase/brand/terranos-dark-letters.png  the dark wordmark without the globe (for animating the two apart)
  showcase/brand/logo.js             where the globe sits in the wordmark, as fractions (window.LOGO)

Run from the repo root:  .venv/bin/python scripts/make_brand_assets.py
"""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "images" / "terranos.png"
NOISE_ALPHA = 32  # pixels below this alpha are background noise
LIGHT_LETTERS = (243, 247, 241)  # --cream in the showcase palette
WORDMARK_WIDTH = 1200
GLOBE_SIZE = 512


def clean(img: Image.Image) -> np.ndarray:
    a = np.array(img.convert("RGBA"))
    a[a[..., 3] < NOISE_ALPHA] = 0
    return a


def trim(a: np.ndarray, pad: int) -> np.ndarray:
    ys, xs = np.nonzero(a[..., 3])
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, a.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, a.shape[1])
    return a[y0:y1, x0:x1]


def grey_mask(a: np.ndarray) -> np.ndarray:
    """Letters are near-neutral grey; the globe is saturated green."""
    rgb = a[..., :3].astype(int)
    return (rgb.max(-1) - rgb.min(-1) < 30) & (a[..., 3] > 0)


def globe(a: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int]]:
    rgb = a[..., :3].astype(int)
    green = (rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2]) > 25) & (a[..., 3] > 128)
    ys, xs = np.nonzero(green)
    cy, cx = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
    r = max(ys.max() - ys.min(), xs.max() - xs.min()) // 2 + 6
    crop = a[cy - r : cy + r, cx - r : cx + r].copy()
    # keep only the disc: the letters "n" and "s" touch the crop's corners
    yy, xx = np.mgrid[: crop.shape[0], : crop.shape[1]]
    crop[(yy - r) ** 2 + (xx - r) ** 2 > (r - 1) ** 2] = 0
    return crop, (cx, cy, r)


def without_globe(a: np.ndarray, cx: int, cy: int, r: int) -> np.ndarray:
    out = a.copy()
    yy, xx = np.mgrid[: a.shape[0], : a.shape[1]]
    out[(yy - cy) ** 2 + (xx - cx) ** 2 <= r**2] = 0
    return out


def save(a: np.ndarray, path: Path, width: int | None = None, size: int | None = None) -> None:
    im = Image.fromarray(a, "RGBA")
    if width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    if size:
        im = im.resize((size, size), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}  {im.width}x{im.height}  {path.stat().st_size // 1024} KB")


def main() -> None:
    a = trim(clean(Image.open(SRC)), pad=8)
    dark = a.copy()
    dark[grey_mask(a), :3] = LIGHT_LETTERS
    g, (cx, cy, r) = globe(a)
    h, w = a.shape[:2]

    save(a, ROOT / "web/public/terranos.png", width=WORDMARK_WIDTH)
    save(g, ROOT / "web/public/terranos-globe.png", size=GLOBE_SIZE)
    save(a, ROOT / "showcase/brand/terranos.png", width=WORDMARK_WIDTH)
    save(dark, ROOT / "showcase/brand/terranos-dark.png", width=WORDMARK_WIDTH)
    save(g, ROOT / "showcase/brand/terranos-globe.png", size=GLOBE_SIZE)
    save(without_globe(dark, cx, cy, r), ROOT / "showcase/brand/terranos-dark-letters.png", width=WORDMARK_WIDTH)
    js = ROOT / "showcase/brand/logo.js"
    js.write_text(
        "// Written by scripts/make_brand_assets.py. Globe position inside the wordmark:\n"
        "// x, y = centre as a fraction of the wordmark's width and height; d = diameter / width; aspect = height / width.\n"
        f"window.LOGO = {{ x: {cx / w:.4f}, y: {cy / h:.4f}, d: {2 * r / w:.4f}, aspect: {h / w:.4f} }}\n"
    )
    print(js.relative_to(ROOT), js.read_text().splitlines()[-1])


if __name__ == "__main__":
    main()
