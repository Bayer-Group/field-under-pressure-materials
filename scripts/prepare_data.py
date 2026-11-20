"""Unzip data/zips/ into a clean, DB-ready layout under data/raw/.

Every dataset lands in one folder with Hive-style partitions and normalised
voivodeship names, so DuckDB can read it with a single glob:

    data/raw/
    ├── weather_grids/                                   *.parquet
    ├── weather_daily/year=2024/voivodeship=mazowieckie/ *.parquet
    ├── weather_hourly/year=2024/voivodeship=mazowieckie/*.parquet
    ├── imerg_daily/                                     *.parquet (layout kept)
    ├── imerg_hourly/                                    *.parquet (layout kept)
    ├── soil/voivodeship=mazowieckie/                    *.parquet
    ├── cropland/year=2024/                              CLMS_HRLVLCC_CTY_PL_*.tif
    ├── cropland/legend/                                 *.clr *.qml *.sld *.lyr
    ├── satellite/<zip name>/                            (layout kept)
    ├── risks/                                           *.pdf *.xlsx
    └── prepare_manifest.json                            what came from which zip

    -- e.g. in DuckDB:
    SELECT * FROM read_parquet('data/raw/weather_daily/**/*.parquet', hive_partitioning = true)

What it fixes on the way:
- voivodeship names: 'Maopolskie' / 'Malopolskie' -> malopolskie, 'odzkie' / 'Łódzkie'
  -> lodzkie, 'Kujawsko_Pomorskie' / 'Kujawsko-Pomorskie' -> kujawsko_pomorskie
- Polish file names stored in legacy cp437 encoding inside the zips
- duplicate uploads (same region under two spellings): identical files are skipped,
  different ones are kept side by side with a warning
- refuses zip entries that would escape the target folder (zip-slip)

Re-running skips zips already prepared (tracked in prepare_manifest.json); --force redoes them.
After preparing, parquet datasets are checked with DuckDB (row count + columns) if installed.

Usage:
    python scripts/prepare_data.py
    python scripts/prepare_data.py --only soil weather_daily
    python scripts/prepare_data.py --delete-zips      # free disk space after success
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = "prepare_manifest.json"

VOIVODESHIPS = [
    "dolnoslaskie", "kujawsko_pomorskie", "lubelskie", "lubuskie", "lodzkie", "malopolskie",
    "mazowieckie", "opolskie", "podkarpackie", "podlaskie", "pomorskie", "slaskie",
    "swietokrzyskie", "warminsko_mazurskie", "wielkopolskie", "zachodniopomorskie",
]
DATASETS = ["weather_grids", "weather_daily", "weather_hourly", "imerg_daily", "imerg_hourly",
            "soil", "cropland", "satellite", "risks", "other"]
PARQUET_DATASETS = ["weather_grids", "weather_daily", "weather_hourly", "imerg_daily",
                    "imerg_hourly", "soil"]
LEGEND_EXT = {".clr", ".qml", ".sld", ".lyr"}


# --------------------------------------------------------------------------- naming
def ascii_fold(s: str) -> str:
    s = s.replace("ł", "l").replace("Ł", "L")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def voiv_slug(raw: str) -> str:
    """Map any spelling of a voivodeship to its canonical ascii slug."""
    s = re.sub(r"[\s\-]+", "_", ascii_fold(raw).lower()).strip("_")
    if s in VOIVODESHIPS:
        return s
    match = difflib.get_close_matches(s, VOIVODESHIPS, n=1, cutoff=0.8)
    if match:
        return match[0]
    print(f"  WARNING: unknown voivodeship {raw!r}, using {s!r}")
    return s


def classify(zip_path: Path) -> tuple[str, Path | None]:
    """Return (dataset, partition subdir) for a zip. Subdir None = keep zip's own layout."""
    name = zip_path.name
    if m := re.match(r"weather_(daily|hourly)_(\d{4})_(.+)\.zip$", name, re.I):
        freq, year, voiv = m.groups()
        return f"weather_{freq.lower()}", Path(f"year={year}") / f"voivodeship={voiv_slug(voiv)}"
    if m := re.match(r"soil_(.+?)_isric_.*\.zip$", name, re.I):
        return "soil", Path(f"voivodeship={voiv_slug(m.group(1))}")
    if m := re.match(r"cropland_.*?(\d{4})\.zip$", name, re.I):
        return "cropland", Path(f"year={m.group(1)}")
    if m := re.match(r"imerg_precipitation_(daily|hourly)\.zip$", name, re.I):
        return f"imerg_{m.group(1).lower()}", None
    if re.match(r"weather_grids.*\.zip$", name, re.I):
        return "weather_grids", Path(".")
    if re.match(r"S2[AB]_.*\.zip$", name, re.I):
        return "satellite", None
    if re.search(r"(metodyk|ryzyk|risk)", name, re.I) or zip_path.suffix.lower() in {".pdf", ".xlsx"}:
        return "risks", Path(".")
    return "other", None


# --------------------------------------------------------------------------- unzip
def entry_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if not info.flag_bits & 0x800:  # not flagged UTF-8 -> Python decoded it as cp437
        try:
            name = name.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def safe_extract(zip_path: Path, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    out = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = entry_name(info)
            if name.startswith("__MACOSX/") or Path(name).name.startswith("._"):
                continue  # macOS resource-fork junk
            dest = (target / name).resolve()
            if root not in dest.parents:
                raise ValueError(f"unsafe path in {zip_path.name}: {name!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as fh:
                shutil.copyfileobj(src, fh, 1 << 20)
            out.append(dest)
    return out


def place(src: Path, dest: Path, warnings: list[str]) -> Path | None:
    """Move src to dest; handle collisions from duplicate uploads. Returns final path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.stat().st_size == src.stat().st_size:
            src.unlink()
            warnings.append(f"duplicate skipped (same size): {dest.name}")
            return None
        i = 1
        while (alt := dest.with_name(f"{dest.stem}__dup{i}{dest.suffix}")).exists():
            i += 1
        warnings.append(f"name clash, kept both: {dest.name} -> {alt.name}")
        dest = alt
    shutil.move(str(src), dest)
    return dest


def prepare_zip(zip_path: Path, dst: Path, staging: Path) -> dict:
    dataset, part = classify(zip_path)
    warnings: list[str] = []
    stage = staging / zip_path.stem
    shutil.rmtree(stage, ignore_errors=True)

    if zip_path.suffix.lower() != ".zip":  # plain file (e.g. xlsx / pdf)
        stage.mkdir(parents=True, exist_ok=True)
        tmp = stage / zip_path.name
        shutil.copy2(zip_path, tmp)
        files = [tmp]
    else:
        files = safe_extract(zip_path, stage)

    outputs = []
    for f in files:
        rel_in_zip = f.relative_to(stage)
        if dataset == "cropland" and f.suffix.lower() in LEGEND_EXT:
            dest = dst / "cropland" / "legend" / f.name
        elif part is None:  # keep the zip's own folder structure
            dest = dst / dataset / (zip_path.stem if dataset in {"satellite", "other"} else "") / rel_in_zip
        else:  # flatten into the partition folder
            dest = dst / dataset / part / f.name
        final = place(f, dest, warnings)
        if final:
            outputs.append(str(final.relative_to(dst)).replace("\\", "/"))

    shutil.rmtree(stage, ignore_errors=True)
    return {"dataset": dataset, "zip_size": zip_path.stat().st_size, "files": outputs,
            "warnings": warnings, "prepared": time.strftime("%Y-%m-%d %H:%M:%S")}


# --------------------------------------------------------------------------- validate
def validate(dst: Path, datasets: list[str]) -> None:
    try:
        import duckdb
    except ImportError:
        print("\n(duckdb not installed - skipping validation: pip install duckdb)")
        return
    print("\nValidation (DuckDB):")
    con = duckdb.connect()
    for ds in datasets:
        folder = dst / ds
        if ds not in PARQUET_DATASETS or not any(folder.rglob("*.parquet")):
            continue
        glob = (folder / "**" / "*.parquet").as_posix()
        try:
            src = f"read_parquet('{glob}', hive_partitioning = true, union_by_name = true)"
            rel = con.sql(f"SELECT * FROM {src} LIMIT 0")
            n = con.execute(f"SELECT count(*) FROM {src}").fetchall()[0][0]  # fetchall drains it
            files = sum(1 for _ in folder.rglob("*.parquet"))
            print(f"  {ds:15s} {files:4d} files  {n:>14,} rows  {len(rel.columns)} cols")
            print(f"  {'':15s} columns: {', '.join(rel.columns[:12])}"
                  + (" ..." if len(rel.columns) > 12 else ""))
        except Exception as e:  # report and continue with the other datasets
            print(f"  {ds:15s} FAILED to read: {e}")
    tifs = list((dst / "cropland").rglob("*.tif")) if (dst / "cropland").exists() else []
    if tifs:
        years = sorted({p.parent.name for p in tifs})
        print(f"  {'cropland':15s} {len(tifs):4d} GeoTIFF tiles  ({', '.join(years)})")


# --------------------------------------------------------------------------- main
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", type=Path, default=REPO / "data" / "zips", help="downloaded zips")
    p.add_argument("--dst", type=Path, default=REPO / "data" / "raw", help="output folder")
    p.add_argument("--only", nargs="+", choices=DATASETS, help="prepare only these datasets")
    p.add_argument("--force", action="store_true", help="redo zips already prepared")
    p.add_argument("--delete-zips", action="store_true", help="delete each zip after it succeeds")
    p.add_argument("--no-validate", action="store_true", help="skip the DuckDB check")
    args = p.parse_args()

    zips = sorted(f for f in args.src.rglob("*") if f.is_file()
                  and f.suffix.lower() in {".zip", ".pdf", ".xlsx"} and not f.name.endswith(".part"))
    if args.only:
        zips = [z for z in zips if classify(z)[0] in args.only]
    if not zips:
        print(f"Nothing to prepare under {args.src}")
        return 1

    args.dst.mkdir(parents=True, exist_ok=True)
    manifest_path = args.dst / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    staging = args.dst / "_staging"

    t0, errors, done_datasets = time.time(), 0, set()
    print(f"Preparing {len(zips)} archives: {args.src} -> {args.dst}")
    for i, z in enumerate(zips, 1):
        key = z.relative_to(args.src).as_posix()
        dataset = classify(z)[0]
        done_datasets.add(dataset)
        prev = manifest.get(key)
        if prev and prev.get("zip_size") == z.stat().st_size and not args.force:
            print(f"[{i}/{len(zips)}] skip    {key}  (already prepared)")
            continue
        t = time.time()
        try:
            entry = prepare_zip(z, args.dst, staging)
        except (zipfile.BadZipFile, ValueError, OSError) as e:
            errors += 1
            print(f"[{i}/{len(zips)}] FAILED  {key}: {e}")
            continue
        manifest[key] = entry
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        part = entry["files"][0].rsplit("/", 1)[0] if entry["files"] else "-"
        print(f"[{i}/{len(zips)}] ok      {key}  -> {part}  "
              f"({len(entry['files'])} files, {time.time() - t:.1f}s)")
        for w in entry["warnings"]:
            print(f"          ! {w}")
        if args.delete_zips:
            z.unlink()

    shutil.rmtree(staging, ignore_errors=True)
    print(f"\nDone in {time.time() - t0:.0f}s. Output: {args.dst}"
          + (f"  ({errors} failed)" if errors else ""))
    if not args.no_validate:
        validate(args.dst, [d for d in DATASETS if d in done_datasets])
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
