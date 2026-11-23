#!/usr/bin/env python3
"""Download hackathon data from the organizers' presigned-URL CSV.

The CSV (columns: dataset, original url, presigned url, size_gb) contains
temporary AWS credentials. Keep it in data/ (git-ignored) and never commit it.

Examples:
  python scripts/download_data.py --list
  python scripts/download_data.py --dataset CROPLAND --dataset SOIL
  python scripts/download_data.py --dataset "WEATHER DAILY 2024" --dry-run
  python scripts/download_data.py --dataset SATELLITE --match 33UXR

Files land in data/raw/<path after the bucket name>, e.g.
data/raw/cropland/cropland_pl_4326_2020.zip. Existing complete files are skipped,
partial files are resumed. Presigned links expire (see --list output).
"""
import argparse
import csv
import re
import sys
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "aws_presigned_urls.csv"
DEFAULT_DEST = ROOT / "data" / "raw"
CHUNK = 1024 * 1024


def load_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def s3_key(original_url):
    # s3://bucket/key -> key
    return original_url.split("://", 1)[-1].split("/", 1)[1]


def expiry(url):
    d = re.search(r"X-Amz-Date=(\w+)", url)
    e = re.search(r"X-Amz-Expires=(\d+)", url)
    if not (d and e):
        return None
    start = datetime.strptime(d.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return start + timedelta(seconds=int(e.group(1)))


def print_listing(rows):
    agg = OrderedDict()
    for r in rows:
        n, s = agg.get(r["dataset"], (0, 0.0))
        agg[r["dataset"]] = (n + 1, s + float(r["size_gb"]))
    for name, (n, s) in agg.items():
        print(f"{name:22} {n:4} files {s:8.1f} GB")
    print(f"{'TOTAL':22} {len(rows):4} files {sum(s for _, s in agg.values()):8.1f} GB")
    exp = expiry(rows[0]["presigned url"]) if rows else None
    if exp:
        left = exp - datetime.now(timezone.utc)
        state = "EXPIRED" if left.total_seconds() <= 0 else f"{left.total_seconds() / 3600:.0f} h left"
        print(f"Links expire: {exp:%Y-%m-%d %H:%M} UTC ({state})")


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = dest.stat().st_size if dest.exists() else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    try:
        resp = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        if e.code == 416:  # already complete
            return "skipped"
        raise
    mode = "ab" if resp.status == 206 else "wb"
    with resp, open(dest, mode) as out:
        while chunk := resp.read(CHUNK):
            out.write(chunk)
    return "resumed" if resp.status == 206 else "downloaded"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    p.add_argument("--dataset", action="append", help="dataset name (case-insensitive substring); repeatable")
    p.add_argument("--match", help="extra filter: substring of the S3 key (e.g. a voivodeship name)")
    p.add_argument("--list", action="store_true", help="show datasets with sizes and link expiry")
    p.add_argument("--dry-run", action="store_true", help="show what would be downloaded")
    args = p.parse_args()

    if not args.csv.exists():
        sys.exit(f"CSV not found: {args.csv}")
    rows = load_rows(args.csv)

    if args.list or not args.dataset:
        print_listing(rows)
        if not args.dataset:
            return

    wanted = [d.lower() for d in args.dataset]
    sel = [r for r in rows if any(w in r["dataset"].lower() for w in wanted)]
    if args.match:
        sel = [r for r in sel if args.match.lower() in r["original url"].lower()]
    if not sel:
        sys.exit("No files match the given filters (try --list).")

    total = sum(float(r["size_gb"]) for r in sel)
    print(f"Selected {len(sel)} files, {total:.1f} GB -> {args.dest}")
    for i, r in enumerate(sel, 1):
        dest = args.dest / s3_key(r["original url"])
        label = f"[{i}/{len(sel)}] {dest.relative_to(args.dest)} ({float(r['size_gb']):.2f} GB)"
        if args.dry_run:
            print(label)
            continue
        try:
            print(f"{label}: {download(r['presigned url'], dest)}")
        except urllib.error.HTTPError as e:
            # Never print the URL: it carries a security token.
            print(f"{label}: HTTP {e.code} {'(link expired?)' if e.code == 403 else ''}")
        except urllib.error.URLError as e:
            print(f"{label}: network error: {e.reason}")


if __name__ == "__main__":
    main()
