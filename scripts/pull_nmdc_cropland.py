#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.28"]
# ///
"""Pull NMDC-processed NEON soil metagenome data for cropland plots.

For every NEON soil metagenome biosample at the requested sites whose plot is
classed as cropland, this script:

1. writes the sample metadata (pH, temperature, moisture, C, N, horizon, depth,
   coordinates, date) to ``samples.csv``;
2. lists every NMDC data object linked to the sample in ``data_objects.csv``
   (including URLs of raw reads, BAMs, MAG bins that are *not* downloaded);
3. downloads the small, analysis-ready outputs (read-based taxonomy, KEGG/EC
   counts, QC and annotation stats) into ``objects/<data_object_id>/`` (one copy per unique object).

Usage:
    uv run scripts/pull_nmdc_cropland.py                 # STER + KONA
    uv run scripts/pull_nmdc_cropland.py --dry-run       # list, don't download
    uv run scripts/pull_nmdc_cropland.py --sites KONA --out data/nmdc
    uv run scripts/pull_nmdc_cropland.py --plots STER_006 STER_010   # these plots only

Light mode (on by default; scripts/00_light_mode.py): only the light-mode plots are pulled, unless --plots or
--all-plots is given. With no data/light_mode.txt those are `light_plots` in config/regions.yaml.

Re-running is safe: files that already exist with the expected size are skipped.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API = "https://api.microbiomedata.org"
NEON_SOIL_STUDY = "nmdc:sty-11-34xj1150"  # NEON soil metagenomes (DP1.10107.001)
CROPLAND_TERM = "area of cropland"  # ENVO term NMDC maps NEON nlcdClass=cultivatedCrops to

# data_object_type -> local file name. Small (~KB-MB) analysis-ready outputs only.
WANTED = {
    "Kraken2 Classification Report": "kraken2_report.tsv",
    "GOTTCHA2 Report Full": "gottcha2_report_full.tsv",
    "Centrifuge output report file": "centrifuge_report.tsv",
    "Annotation KEGG Orthology": "ko.tsv",
    "Annotation Enzyme Commission": "ec.tsv",
    "Annotation Statistics": "annotation_stats.tsv",
    "QC Statistics": "qc_filterStats.txt",
    "Gene Phylogeny tsv": "gene_phylogeny.tsv",   # closest reference lineage per annotated gene (up to ~0.5 GB)
}

# --types keys -> data_object_type (EC / Centrifuge / gene phylogeny are selectable but off by default)
TYPE_KEYS = {
    "kraken2": "Kraken2 Classification Report",
    "gottcha2": "GOTTCHA2 Report Full",
    "centrifuge": "Centrifuge output report file",
    "ko": "Annotation KEGG Orthology",
    "ec": "Annotation Enzyme Commission",
    "annotation_stats": "Annotation Statistics",
    "qc": "QC Statistics",
    "gene_phylogeny": "Gene Phylogeny tsv",
}
DEFAULT_TYPES = ["kraken2", "gottcha2", "ko", "annotation_stats", "qc"]

SAMPLE_FIELDS = [
    "id", "name", "site", "plot", "horizon", "depth_min_m", "depth_max_m",
    "collection_date", "year", "latitude", "longitude", "elev",
    "ph", "temp_c", "water_content_g_per_g", "org_carb_pct", "nitro_pct",
    "carb_nitro_ratio", "ammonium_nitrogen", "tot_nitro_content",
    "env_local_scale", "soil_horizon", "gold_biosample", "insdc_biosample",
    "img_taxon", "n_data_objects", "has_kraken2", "has_ko", "metagenome_key",
]

DO_FIELDS = [
    "biosample_id", "biosample_name", "site", "data_object_id",
    "data_object_type", "name", "file_size_bytes", "md5_checksum", "url",
    "selected", "local_path",
]

REPO = Path(__file__).resolve().parents[1]
LIGHT_FILE = REPO / "data" / "light_mode.txt"


def light_plots() -> list[str] | None:
    """Plots of light mode, None when it is off. Same rules as cropfit.config.read_light_file (this script stays
    standalone): no data/light_mode.txt -> on with `light_plots` of config/regions.yaml; a line "off" -> off;
    otherwise the plots listed ('STER_006' or 'STER 006' per line)."""
    def plot(s: str) -> str | None:
        m = re.match(r"^([A-Z]{4})[\s_-]*(\d{3})", s.strip().upper())
        return f"{m[1]}_{m[2]}" if m else None

    def defaults() -> list[str]:   # the `light_plots: [...]` line; no yaml (only requests under `uv run`)
        m = re.search(r"^light_plots:\s*\[([^\]]*)\]", (REPO / "config" / "regions.yaml").read_text(), re.M)
        if not m:
            sys.exit("config/regions.yaml has no `light_plots: [...]` line; pass --plots or --all-plots")
        return sorted({p for p in map(plot, m[1].split(",")) if p})

    if not LIGHT_FILE.exists():
        return defaults()
    words = [w for w in (line.split("#")[0].strip() for line in LIGHT_FILE.read_text().splitlines()) if w]
    if any(w.lower() == "off" for w in words):
        return None
    return sorted({p for p in map(plot, words) if p}) or defaults()


session = requests.Session()
# NMDC rejects some default client user agents; use a generic one.
session.headers["User-Agent"] = "neon-cropland-pull/0.1"


def get_json(path: str, params: dict | None = None, retries: int = 4) -> dict:
    for attempt in range(retries):
        try:
            r = session.get(f"{API}{path}", params=params, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  retry {path} in {wait}s ({e})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_biosamples(site: str) -> list[dict]:
    """All NEON soil biosamples whose name starts with SITE_, cropland only."""
    out, page = [], 1
    while True:
        r = get_json(
            "/biosamples",
            {
                "filter": f"associated_studies:{NEON_SOIL_STUDY},name.search:{site}_",
                "per_page": 500,
                "page": page,
            },
        )
        out.extend(r["results"])
        if len(out) >= r["meta"]["count"] or not r["results"]:
            break
        page += 1
    return [
        b for b in out
        if b["name"].startswith(f"{site}_")
        and b.get("env_local_scale", {}).get("term", {}).get("name") == CROPLAND_TERM
    ]


def fetch_data_objects(biosample_id: str) -> list[dict]:
    r = get_json(
        "/nmdcschema/linked_instances",
        {"ids": biosample_id, "types": "nmdc:DataObject", "hydrate": "true",
         "max_page_size": 1000},
    )
    return r.get("resources", [])


# ---------------------------------------------------------------- flattening

def _num(v):
    if isinstance(v, dict):
        return v.get("has_numeric_value", v.get("has_raw_value"))
    return v


def _water(v):
    # e.g. ["2.667 g of water/g of dry soil"]
    if isinstance(v, list) and v:
        m = re.match(r"\s*([-\d.eE]+)", str(v[0]))
        return float(m.group(1)) if m else v[0]
    return _num(v)


def flatten_biosample(b: dict, dos: list[dict]) -> dict:
    # Name pattern: SITE_PLOT-HORIZON-TOPcm-BOTTOMcm-YYYYMMDD, e.g. KONA_001-M-16-31.5-20190619
    parts = b["name"].split("-")
    site = b["name"].split("_")[0]
    date = b.get("collection_date", {}).get("has_raw_value", "")
    depth = b.get("depth", {})
    latlon = b.get("lat_lon", {})
    types = {d.get("data_object_type") for d in dos}
    first = lambda k: (b.get(k) or [""])[0]
    return {
        "id": b["id"],
        "name": b["name"],
        "site": site,
        "plot": parts[0],
        "horizon": parts[1] if len(parts) > 1 else "",
        "depth_min_m": depth.get("has_minimum_numeric_value"),
        "depth_max_m": depth.get("has_maximum_numeric_value"),
        "collection_date": date,
        "year": date[:4],
        "latitude": latlon.get("latitude"),
        "longitude": latlon.get("longitude"),
        "elev": b.get("elev"),
        "ph": b.get("ph"),
        "temp_c": _num(b.get("temp")),
        "water_content_g_per_g": _water(b.get("water_content")),
        "org_carb_pct": _num(b.get("org_carb")),
        "nitro_pct": _num(b.get("nitro")),
        "carb_nitro_ratio": _num(b.get("carb_nitro_ratio")),
        "ammonium_nitrogen": _num(b.get("ammonium_nitrogen")),
        "tot_nitro_content": _num(b.get("tot_nitro_content")),
        "env_local_scale": b.get("env_local_scale", {}).get("term", {}).get("name"),
        "soil_horizon": b.get("soil_horizon"),
        "gold_biosample": first("gold_biosample_identifiers"),
        "insdc_biosample": first("insdc_biosample_identifiers"),
        "img_taxon": first("img_identifiers"),
        "n_data_objects": len(dos),
        "has_kraken2": "Kraken2 Classification Report" in types,
        "has_ko": "Annotation KEGG Orthology" in types,
    }


def _wf_version(name: str) -> tuple[int, str]:
    # nmdc_wfmgan-11-q2z6z836.1_ko.tsv -> 1 ; keep highest workflow version per type
    m = re.search(r"\.(\d+)_", name or "")
    return (int(m.group(1)) if m else 0, name or "")


def select_objects(dos: list[dict], types: set[str] | None = None) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for d in dos:
        t = d.get("data_object_type")
        if t in WANTED and d.get("url") and (types is None or t in types):
            if t not in best or _wf_version(d["name"]) > _wf_version(best[t]["name"]):
                best[t] = d
    return best


# ---------------------------------------------------------------- download

def download(url: str, dest: Path, size: int | None, md5: str | None) -> str:
    if dest.exists() and (size is None or dest.stat().st_size == size):
        return "skipped"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.md5()
    for attempt in range(4):
        try:
            with session.get(url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        h.update(chunk)
            break
        except requests.RequestException:
            if attempt == 3:
                raise
            h = hashlib.md5()
            time.sleep(2 ** attempt)
    if md5 and h.hexdigest() != md5:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"md5 mismatch for {url}")
    tmp.replace(dest)
    return "downloaded"


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sites", nargs="+", help="default: STER KONA, or the sites of --plots")
    ap.add_argument("--plots", nargs="+", help="only these plots, e.g. STER_006 (default: light mode's plots)")
    ap.add_argument("--all-plots", action="store_true", help="ignore light mode")
    ap.add_argument("--out", type=Path, default=Path("data/nmdc"))
    ap.add_argument("--dry-run", action="store_true", help="list only, no downloads")
    ap.add_argument("--types", nargs="+", default=DEFAULT_TYPES, choices=sorted(TYPE_KEYS),
                    help="which data object types to download (default: %(default)s)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    wanted_types = {TYPE_KEYS[k] for k in args.types}
    plots = None if args.all_plots else (
        sorted({p.upper().replace(" ", "_") for p in args.plots}) if args.plots else light_plots())
    if args.sites is None:
        args.sites = sorted({p[:4] for p in plots}) if plots else ["STER", "KONA"]
    if plots is not None:
        print(f"light mode: {len(plots)} plots ({', '.join(plots)})", file=sys.stderr)

    samples: list[dict] = []
    do_rows: list[dict] = []
    jobs: dict[Path, tuple[str, Path, int | None, str | None]] = {}  # deduped by data-object id

    for site in args.sites:
        bios = fetch_biosamples(site)
        if plots is not None:
            bios = [b for b in bios if b["name"].split("-")[0] in plots]
        print(f"{site}: {len(bios)} cropland biosamples", file=sys.stderr)
        with ThreadPoolExecutor(args.workers) as ex:
            futs = {ex.submit(fetch_data_objects, b["id"]): b for b in bios}
            linked = {futs[f]["id"]: f.result() for f in as_completed(futs)}
        for b in sorted(bios, key=lambda x: x["name"]):
            dos = linked[b["id"]]
            sel = select_objects(dos, wanted_types)
            row = flatten_biosample(b, dos)
            mg = sel.get("Annotation KEGG Orthology") or sel.get("Kraken2 Classification Report")
            row["metagenome_key"] = mg["id"] if mg else ""
            samples.append(row)
            chosen = {d["id"] for d in sel.values()}
            for d in sorted(dos, key=lambda x: (x.get("data_object_type") or "", x.get("name") or "")):
                local = ""
                if d["id"] in chosen:
                    # shared by all biosamples pooled into the same metagenome
                    local = (args.out / "objects" / d["id"].replace(":", "_")
                             / WANTED[d["data_object_type"]])
                    jobs.setdefault(local, (d["url"], local, d.get("file_size_bytes"), d.get("md5_checksum")))
                do_rows.append({
                    "biosample_id": b["id"], "biosample_name": b["name"], "site": site,
                    "data_object_id": d["id"], "data_object_type": d.get("data_object_type"),
                    "name": d.get("name"), "file_size_bytes": d.get("file_size_bytes"),
                    "md5_checksum": d.get("md5_checksum"), "url": d.get("url"),
                    "selected": d["id"] in chosen, "local_path": str(local),
                })

    write_csv(args.out / "samples.csv", SAMPLE_FIELDS, samples)
    write_csv(args.out / "data_objects.csv", DO_FIELDS, do_rows)

    by_site_year = Counter((s["site"], s["year"]) for s in samples)
    processed = Counter((s["site"], s["year"]) for s in samples if s["has_kraken2"])
    print("\nsite year  samples  with_taxonomy", file=sys.stderr)
    for k in sorted(by_site_year):
        print(f"{k[0]} {k[1]}  {by_site_year[k]:>7}  {processed[k]:>13}", file=sys.stderr)
    jobs = list(jobs.values())
    total = sum(j[2] or 0 for j in jobs)
    print(f"\n{len(jobs)} files selected, {total / 1e6:.1f} MB", file=sys.stderr)
    print(f"wrote {args.out / 'samples.csv'} and {args.out / 'data_objects.csv'}", file=sys.stderr)

    if args.dry_run:
        return

    status: Counter = Counter()
    failed = []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(download, *j): j for j in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                status[f.result()] += 1
            except Exception as e:  # keep going; report at the end
                status["failed"] += 1
                failed.append((futs[f][0], str(e)))
            if i % 100 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} {dict(status)}", file=sys.stderr)
    for url, err in failed:
        print(f"FAILED {url}: {err}", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
