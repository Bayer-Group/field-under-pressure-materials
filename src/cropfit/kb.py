"""Knowledge bases for crop risk: FungalTraits (genus lifestyle filter) and USDA ARS Fungus-Host (species x host).

Sources (verified 21 Nov 2026, see AGENT.md 3.11 / 3.12):
- FungalTraits, Polme et al. 2020, Fungal Diversity 105:1-16, Table S1 (genus level), official Springer ESM xlsx.
- USDA ARS U.S. National Fungus Collections Fungus-Host Dataset, Ag Data Commons DOI 10.15482/USDA.ADC/1524414,
  snapshot Fungus-Host-Data_20211105.csv (U.S. Public Domain). The live fungi.ars.usda.gov API needs a
  site-internal key and is not used.

Raw downloads land in data/raw/kb/<source>/ (gitignored) with a manifest.json; built tables in data/processed/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import http
from .config import PROCESSED, RAW, RULES

FUNGALTRAITS_URL = ("https://static-content.springer.com/esm/art%3A10.1007%2Fs13225-020-00466-2/"
                    "MediaObjects/13225_2020_466_MOESM4_ESM.xlsx")
FUNGALTRAITS_VERSION = "Polme et al. 2020, Fungal Diversity 105:1-16, Table S1 (ESM 4, genus level)"
USDA_FH_URL = "https://ndownloader.figshare.com/files/43732281"
USDA_FH_VERSION = ("USDA ARS U.S. National Fungus Collections Fungus-Host Dataset, "
                   "Fungus-Host-Data_20211105.csv, DOI 10.15482/USDA.ADC/1524414")

KB_RAW = RAW / "kb"
FUNGALTRAITS_DIR = KB_RAW / "fungaltraits"
USDA_DIR = KB_RAW / "usda_fungus_host"

# Phyla in FungalTraits that are not fungi (oomycetes and other stramenopiles/protists).
NON_FUNGAL_PHYLA = frozenset({"Oomycota", "Labyrinthulidia", "Hypochytriomycota", "Developea", "Pirsonida"})
# Oomycete genera excluded even when a database lists them as plant pathogens: ITS fungal primers miss them.
OOMYCETE_GENERA = frozenset({"Pythium", "Phytophthora", "Aphanomyces", "Globisporangium", "Phytopythium"})

# crop_group values (rules/cdl_codes.csv) that are scored as crops.
SCORED_CROPS = ("corn", "soybean", "winter_wheat", "spring_wheat", "sorghum", "sunflower",
                "alfalfa", "millet", "dry_bean", "barley_oats")
EXCLUDED_CROP_GROUPS = {
    "double_wheat_soy": "rotation, not a crop; scored as winter_wheat and soybean",
    "other_crop": "mixed group of many crops",
    "fallow": "not a crop",
    "grass_pasture": "not a single crop",
    "noncrop": "not a crop",
    "unknown": "not a crop",
}

# Built tables (data/processed/)
GENERA_TABLE = "kb_fungaltraits_genus.parquet"
HOST_TABLE = "kb_genus_crop_host.parquet"
SPECIES_CROP_TABLE = "kb_usda_species_crop.parquet"
META_FILE = "kb_meta.json"

GENERA_COLUMNS = ["genus_raw", "genus", "canonical_genus", "phylum", "primary_lifestyle", "secondary_lifestyle",
                  "plant_pathogenic_capacity", "passes_filter", "passed_by", "exclusion_reason", "duplicate_rows"]
HOST_COLUMNS = ["genus", "crop_group", "n_species_documented", "n_species_on_crop", "h", "species_on_crop",
                "n_records_on_crop", "n_genus_only_records_on_crop", "source_version"]
SPECIES_CROP_COLUMNS = ["canonical_genus", "species", "crop_group", "n_records", "n_refs", "host_names"]

_SUFFIX_RE = re.compile(r"(?:[_\s]+(?:sp|spp|sp\.|spp\.))+$", re.IGNORECASE)


def normalise_genus(name) -> str | None:
    """Clean a genus name for joining: strip, drop `_sp` / ` sp.` / ` spp.` suffixes, capitalise the first letter.

    Returns None for empty values and placeholders (`unclassified_*`, `*Incertae_sedis*`)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = str(name).strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("unclassified") or "incertae" in low or low in {"na", "nan", "none", r"\n"}:
        return None
    s = _SUFFIX_RE.sub("", s).strip(" _")
    if not s:
        return None
    return s[0].upper() + s[1:].lower()


@lru_cache(maxsize=None)
def _synonyms_cached(path: str) -> tuple[tuple[str, str], ...]:
    df = pd.read_csv(path, dtype=str)
    pairs = []
    for a, c in zip(df["alias"], df["canonical"]):
        na, nc = normalise_genus(a), str(c).strip()
        if na and nc:
            pairs.append((na, nc))
    return tuple(pairs)


def load_genus_synonyms(path: Path = RULES / "genus_synonyms.csv") -> dict[str, str]:
    """alias -> canonical genus (rules/genus_synonyms.csv). Aliases are normalised; canonical names kept as written."""
    return dict(_synonyms_cached(str(path)))


def canonical_genus(name, synonyms: dict[str, str]) -> str | None:
    """normalise_genus, then map through the synonym table (e.g. Thanatephorus -> Rhizoctonia_complex)."""
    n = normalise_genus(name)
    if n is None:
        return None
    return synonyms.get(n, n)


@dataclass(frozen=True)
class KB:
    """Loaded knowledge base. genera: GENERA_COLUMNS; host: HOST_COLUMNS; synonyms: alias -> canonical;
    meta: contents of kb_meta.json (sources with url, retrieved_utc, bytes, sha256, source_version)."""
    genera: pd.DataFrame
    host: pd.DataFrame
    synonyms: dict[str, str] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


FUNGALTRAITS_FILE = "13225_2020_466_MOESM4_ESM.xlsx"
USDA_FH_FILE = "Fungus-Host-Data_20211105.csv"
USDA_FH_BYTES = 187_658_073
PLANT_PATHOGEN = "plant_pathogen"


# --- download ---------------------------------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_manifest(raw_dir: Path) -> dict:
    p = raw_dir / "manifest.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _write_manifest(raw_dir: Path, entry: dict) -> None:
    m = _read_manifest(raw_dir)
    m[entry["file"]] = entry
    tmp = raw_dir / "manifest.json.part"
    tmp.write_text(json.dumps(m, indent=2, sort_keys=True))
    os.replace(tmp, raw_dir / "manifest.json")


def download_file(url: str, dest: Path, *, refresh: bool = False, source_version: str = "") -> dict:
    """Stream `url` to `dest` (via `<name>.part`, then os.replace) and record it in `dest.parent/manifest.json`.

    An existing file is kept unless refresh=True; its manifest entry is returned (rebuilt from the file if absent).
    Only the input URL is recorded, never the redirect target (presigned S3 URLs carry tokens)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not refresh:
        entry = _read_manifest(dest.parent).get(dest.name)
        if entry is None:
            entry = {"file": dest.name, "url": url, "retrieved_utc": None, "bytes": dest.stat().st_size,
                     "sha256": _sha256_file(dest), "source_version": source_version}
        return entry
    part = dest.with_name(dest.name + ".part")
    h, n = hashlib.sha256(), 0
    try:
        r = http.get(url, stream=True, timeout=(30, 600))
        with open(part, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
        r.close()
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    entry = {"file": dest.name, "url": url, "retrieved_utc": _utc_now(), "bytes": n, "sha256": h.hexdigest(),
             "source_version": source_version}
    _write_manifest(dest.parent, entry)
    return entry


def fetch_fungaltraits(raw_dir: Path = FUNGALTRAITS_DIR, refresh: bool = False, local_file: Path | None = None) -> Path:
    """Download the FungalTraits ESM xlsx into raw_dir (or copy `local_file` there). Returns the file path."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / FUNGALTRAITS_FILE
    if local_file is not None:
        local_file = Path(local_file)
        dest = raw_dir / local_file.name
        if refresh or not dest.exists():
            shutil.copyfile(local_file, dest)
            _write_manifest(raw_dir, {"file": dest.name, "url": f"local:{local_file.name}",
                                      "retrieved_utc": _utc_now(), "bytes": dest.stat().st_size,
                                      "sha256": _sha256_file(dest), "source_version": FUNGALTRAITS_VERSION})
        return dest
    download_file(FUNGALTRAITS_URL, dest, refresh=refresh, source_version=FUNGALTRAITS_VERSION)
    return dest


def fetch_usda_fungus_host(raw_dir: Path = USDA_DIR, refresh: bool = False) -> Path:
    """Download the USDA Fungus-Host snapshot CSV (about 179 MB) into raw_dir. Returns the file path."""
    raw_dir = Path(raw_dir)
    dest = raw_dir / USDA_FH_FILE
    entry = download_file(USDA_FH_URL, dest, refresh=refresh, source_version=USDA_FH_VERSION)
    if entry["bytes"] != USDA_FH_BYTES:
        print(f"warning: {dest.name} is {entry['bytes']:,} bytes, expected {USDA_FH_BYTES:,}")
    return dest


# --- parsing ----------------------------------------------------------------------------------------------------

_GENUS_RE = re.compile(r"^[A-Z][A-Za-z-]+$")
_EPITHET_RE = re.compile(r"^[a-z][a-z-]+$")
_NOT_EPITHET = frozenset({"sp", "sp.", "spp", "spp.", "cf.", "cf", "aff.", "aff", "nr.", "x", "\u00d7"})
_HYBRID = "\u00d7"


def parse_binomial(name) -> tuple[str | None, str | None]:
    """Split a scientific name into (genus, epithet); authors, var./subsp./f. sp. and placeholders are ignored.

    'Fusarium oxysporum f. sp. lycopersici' -> ('Fusarium', 'oxysporum'); 'Fusarium sp.' -> ('Fusarium', None)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None, None
    toks = str(name).strip().replace('"', " ").replace("'", " ").split()
    if toks and toks[0].lower() == "x" and len(toks) > 1:
        toks = toks[1:]
    if not toks:
        return None, None
    g = toks[0].lstrip(_HYBRID)
    if not _GENUS_RE.match(g):
        return None, None
    rest = toks[1:]
    if rest and rest[0] in (_HYBRID, "x"):
        rest = rest[1:]
    if not rest:
        return g, None
    e = rest[0].lstrip(_HYBRID)
    if rest[0].lower() in _NOT_EPITHET or not _EPITHET_RE.match(e):
        return g, None
    return g, e


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    v = str(v).strip()
    return v or None


def parse_fungaltraits(path: Path) -> pd.DataFrame:
    """Read FungalTraits (xlsx, csv or tsv); the header row is the one containing the cell GENUS (first 10 rows).

    Returns genus_raw, phylum, primary_lifestyle, secondary_lifestyle, plant_pathogenic_capacity,
    comment_on_lifestyle (stripped strings, empty -> None, lifestyles lowercased)."""
    path = Path(path)
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        raw = pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
    else:
        raw = pd.read_csv(path, header=None, dtype=str, sep="\t" if suf in (".tsv", ".tab") else ",",
                          keep_default_na=False)
    hdr = None
    for i in range(min(10, len(raw))):
        if any(str(c).strip().upper() == "GENUS" for c in raw.iloc[i].tolist()):
            hdr = i
            break
    if hdr is None:
        raise ValueError(f"{path.name}: no header row with a GENUS column in the first 10 rows")
    cols = [str(c).strip().lower() for c in raw.iloc[hdr].tolist()]
    body = raw.iloc[hdr + 1:].reset_index(drop=True)
    body.columns = cols

    def col(name):
        if name.lower() not in cols:
            return pd.Series([None] * len(body), dtype=object)
        return pd.Series([_clean(v) for v in body[name.lower()]], dtype=object)

    out = pd.DataFrame({
        "genus_raw": col("GENUS"),
        "phylum": col("Phylum"),
        "primary_lifestyle": col("primary_lifestyle").map(lambda v: v.lower() if isinstance(v, str) else None),
        "secondary_lifestyle": col("Secondary_lifestyle").map(lambda v: v.lower() if isinstance(v, str) else None),
        "plant_pathogenic_capacity": col("Plant_pathogenic_capacity_template"),
        "comment_on_lifestyle": col("Comment_on_lifestyle_template"),
    })
    return out[out["genus_raw"].notna()].reset_index(drop=True)


def _join_unique(values) -> str | None:
    seen = sorted({str(v) for v in values if v is not None and not (isinstance(v, float) and pd.isna(v))})
    return "|".join(seen) if seen else None


def classify_genera(ft: pd.DataFrame, synonyms: dict[str, str]) -> pd.DataFrame:
    """One row per normalised genus with the plant-pathogen filter (primary or secondary lifestyle) applied.

    Duplicates are aggregated (passes if any row passes). Plant_pathogenic_capacity is reported, never admits."""
    df = ft.copy()
    df["genus"] = df["genus_raw"].map(normalise_genus)
    df = df[df["genus"].notna()].copy()
    prim = df["primary_lifestyle"].eq(PLANT_PATHOGEN)
    sec = df["secondary_lifestyle"].eq(PLANT_PATHOGEN)
    df["_ok"] = prim | sec
    df["_by"] = prim.map({True: "primary_lifestyle", False: None}).where(prim, None)
    df.loc[sec & ~prim, "_by"] = "secondary_lifestyle"
    df.loc[sec & prim, "_by"] = "primary_lifestyle+secondary_lifestyle"
    df["_reason"] = None
    df.loc[~df["_ok"], "_reason"] = "not_plant_pathogen"
    df.loc[df["phylum"].isin(NON_FUNGAL_PHYLA), "_reason"] = "non_fungal"
    df.loc[df["genus"].isin(OOMYCETE_GENERA), "_reason"] = "oomycete"
    df["_pass"] = df["_reason"].isna()
    rows = []
    for g, d in df.groupby("genus", sort=True):
        passing = d[d["_pass"]]
        ok = len(passing) > 0
        ref = passing if ok else d
        reason = None
        if not ok:
            rs = set(d["_reason"])
            reason = next(r for r in ("oomycete", "non_fungal", "not_plant_pathogen") if r in rs)
        rows.append({
            "genus_raw": _join_unique(d["genus_raw"]), "genus": g, "canonical_genus": canonical_genus(g, synonyms),
            "phylum": _join_unique(d["phylum"]), "primary_lifestyle": _join_unique(d["primary_lifestyle"]),
            "secondary_lifestyle": _join_unique(d["secondary_lifestyle"]),
            "plant_pathogenic_capacity": _join_unique(d["plant_pathogenic_capacity"]),
            "passes_filter": ok, "passed_by": _join_unique(passing["_by"]) if ok else None,
            "exclusion_reason": reason, "duplicate_rows": len(d),
        })
        del ref
    return pd.DataFrame(rows, columns=GENERA_COLUMNS)


def read_usda_fungus_host(path: Path, chunksize: int = 500_000, *, with_stats: bool = False):
    """Read the USDA Fungus-Host CSV in chunks and return slim, deduplicated records.

    Columns: fungus_genus, fungus_epithet, host_raw, host_genus, host_epithet, litnum. Rows without a fungus genus
    or host genus are dropped. Malformed lines are skipped and counted in df.attrs['bad_lines'] (also
    df.attrs['rows_read']); with_stats=True returns (df, stats dict)."""
    cache: dict = {}

    def parsed(v):
        r = cache.get(v)
        if r is None:
            r = cache[v] = parse_binomial(v)
        return r

    def run(engine: str, on_bad):
        parts, n_rows = [], 0
        reader = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=["\\N"],
                             usecols=["sciName", "host", "litnum"], chunksize=chunksize, engine=engine,
                             on_bad_lines=on_bad)
        for ch in reader:
            n_rows += len(ch)
            ch = ch.rename(columns={"sciName": "fungus", "host": "host_raw"}).drop_duplicates()
            fp = ch["fungus"].map(parsed)
            hp = ch["host_raw"].map(parsed)
            out = pd.DataFrame({
                "fungus_genus": [normalise_genus(p[0]) for p in fp],
                "fungus_epithet": [p[1] for p in fp],
                "host_raw": ch["host_raw"].to_numpy(),
                "host_genus": [p[0] for p in hp],
                "host_epithet": [p[1] for p in hp],
                "litnum": ch["litnum"].to_numpy(),
            })
            parts.append(out[out["fungus_genus"].notna() & out["host_genus"].notna()].drop_duplicates())
        return parts, n_rows

    # The 2021 snapshot is plain RFC-4180 CSV (doubled quotes, no backslash escapes, unquoted \N): the fast C
    # engine parses it without errors. Only if it ever fails do we fall back to the slow engine, skipping and
    # counting malformed lines.
    bad: list = []
    try:
        parts, n_rows = run("c", "error")
    except pd.errors.ParserError:
        bad.clear()
        parts, n_rows = run("python", lambda line: bad.append(1))
    cols = ["fungus_genus", "fungus_epithet", "host_raw", "host_genus", "host_epithet", "litnum"]
    df = (pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)
          if parts else pd.DataFrame(columns=cols))
    df.attrs["bad_lines"] = len(bad)
    df.attrs["rows_read"] = n_rows
    if with_stats:
        return df, {"bad_lines": len(bad), "rows_read": n_rows}
    return df


# --- host taxa and crop groups ----------------------------------------------------------------------------------

def load_crop_host_taxa(path: Path = RULES / "crop_host_taxa.csv") -> pd.DataFrame:
    """Read rules/crop_host_taxa.csv (host_taxon, rank, crop_group, note) and add host_genus / host_epithet."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = {"host_taxon", "rank", "crop_group"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    if "note" not in df.columns:
        df["note"] = ""
    df = df[["host_taxon", "rank", "crop_group", "note"]].copy()
    for c in ("host_taxon", "rank", "crop_group"):
        df[c] = df[c].str.strip()
    bad = df[~df["rank"].isin(["species", "genus"])]
    if len(bad):
        raise ValueError(f"{path}: rank must be species|genus, got {bad['rank'].unique().tolist()}")
    bad = df[~df["crop_group"].isin(SCORED_CROPS)]
    if len(bad):
        raise ValueError(f"{path}: crop_group not in SCORED_CROPS: {bad['crop_group'].unique().tolist()}")
    gp = df["host_taxon"].map(parse_binomial)
    df["host_genus"] = [p[0] for p in gp]
    df["host_epithet"] = [p[1] for p in gp]
    if df["host_genus"].isna().any():
        raise ValueError(f"{path}: unparsable host_taxon {df.loc[df['host_genus'].isna(), 'host_taxon'].tolist()}")
    sp_no_ep = df[(df["rank"] == "species") & df["host_epithet"].isna()]
    if len(sp_no_ep):
        raise ValueError(f"{path}: species rows without epithet {sp_no_ep['host_taxon'].tolist()}")
    ge_ep = df[(df["rank"] == "genus") & df["host_epithet"].notna()]
    if len(ge_ep):
        raise ValueError(f"{path}: genus rows with an epithet {ge_ep['host_taxon'].tolist()}")
    return df.reset_index(drop=True)


def assign_crop_groups(usda: pd.DataFrame, taxa: pd.DataFrame) -> pd.DataFrame:
    """usda rows joined to crop_group. Species taxa match host genus + epithet (so varieties match); genus taxa match
    host genus only for host records without an epithet. A record on several crops is repeated."""
    sp = (taxa[taxa["rank"] == "species"][["host_genus", "host_epithet", "crop_group"]].drop_duplicates())
    ge = (taxa[taxa["rank"] == "genus"][["host_genus", "crop_group"]].drop_duplicates())
    a = usda[usda["host_epithet"].notna()].merge(sp, on=["host_genus", "host_epithet"], how="inner")
    b = usda[usda["host_epithet"].isna()].merge(ge, on="host_genus", how="inner")
    return pd.concat([a, b], ignore_index=True)


def build_genus_crop_host(usda_slim: pd.DataFrame, taxa: pd.DataFrame, synonyms: dict[str, str],
                          crops=SCORED_CROPS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Host table (HOST_COLUMNS) and species x crop table (SPECIES_CROP_COLUMNS).

    H = n_species_on_crop / n_species_documented per canonical genus; species need a genus and an epithet,
    genus-only fungus records are counted only in n_genus_only_records_on_crop."""
    crops = tuple(crops)
    u = usda_slim.copy()
    u["canonical_genus"] = u["fungus_genus"].map(lambda g: canonical_genus(g, synonyms))
    u = u[u["canonical_genus"].notna()]
    has_ep = u["fungus_epithet"].notna()
    u.loc[has_ep, "species"] = u.loc[has_ep, "fungus_genus"] + " " + u.loc[has_ep, "fungus_epithet"]
    sp_all = u[has_ep]
    documented = sp_all.groupby("canonical_genus")["species"].nunique()

    ac = assign_crop_groups(u, taxa)
    ac = ac[ac["crop_group"].isin(crops)]
    ac_sp = ac[ac["fungus_epithet"].notna()].drop_duplicates(["species", "host_raw", "litnum", "crop_group"])
    ac_go = ac[ac["fungus_epithet"].isna()].drop_duplicates(["canonical_genus", "fungus_genus", "host_raw", "litnum", "crop_group"])

    on_crop = ac_sp.groupby(["canonical_genus", "crop_group"]).agg(
        n_species_on_crop=("species", "nunique"),
        species_on_crop=("species", lambda s: "; ".join(sorted(set(s)))),
        n_records_on_crop=("species", "size"))
    go = ac_go.groupby(["canonical_genus", "crop_group"]).size().rename("n_genus_only_records_on_crop")

    idx = pd.MultiIndex.from_product([documented.index, list(crops)], names=["genus", "crop_group"])
    host = pd.DataFrame(index=idx).reset_index()
    host["n_species_documented"] = host["genus"].map(documented).astype(int)
    key = list(zip(host["genus"], host["crop_group"]))
    oc = on_crop.reindex(key)
    host["n_species_on_crop"] = oc["n_species_on_crop"].fillna(0).astype(int).to_numpy()
    host["h"] = host["n_species_on_crop"] / host["n_species_documented"]
    host["species_on_crop"] = oc["species_on_crop"].fillna("").to_numpy()
    host["n_records_on_crop"] = oc["n_records_on_crop"].fillna(0).astype(int).to_numpy()
    host["n_genus_only_records_on_crop"] = go.reindex(key).fillna(0).astype(int).to_numpy()
    host["source_version"] = USDA_FH_VERSION
    host = host[HOST_COLUMNS]

    sc = ac_sp.groupby(["canonical_genus", "species", "crop_group"]).agg(
        n_records=("species", "size"), n_refs=("litnum", "nunique"),
        host_names=("host_raw", lambda s: "; ".join(sorted(set(s))))).reset_index()
    return host.reset_index(drop=True), sc[SPECIES_CROP_COLUMNS]


# --- build / load -----------------------------------------------------------------------------------------------

def _file_meta(path: Path, rel: str) -> dict:
    df = pd.read_csv(path, dtype=str)
    return {"path": rel, "sha256": _sha256_file(path), "rows": int(len(df))}


def build_kb(refresh: bool = False, out_dir: Path = PROCESSED, fungaltraits_file: Path | None = None) -> dict:
    """Fetch both databases, build the three tables and kb_meta.json in out_dir. Returns the meta dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ft_path = fetch_fungaltraits(refresh=refresh, local_file=fungaltraits_file)
    us_path = fetch_usda_fungus_host(refresh=refresh)
    syn_path = RULES / "genus_synonyms.csv"
    taxa_path = RULES / "crop_host_taxa.csv"
    synonyms = load_genus_synonyms(syn_path)
    genera = classify_genera(parse_fungaltraits(ft_path), synonyms)
    usda, st = read_usda_fungus_host(us_path, with_stats=True)
    taxa = load_crop_host_taxa(taxa_path)
    host, sc = build_genus_crop_host(usda, taxa, synonyms)
    genera.to_parquet(out_dir / GENERA_TABLE, index=False)
    host.to_parquet(out_dir / HOST_TABLE, index=False)
    sc.to_parquet(out_dir / SPECIES_CROP_TABLE, index=False)
    ft_m, us_m = _read_manifest(ft_path.parent), _read_manifest(us_path.parent)
    meta = {
        "sources": {"fungaltraits": ft_m.get(ft_path.name, {}), "usda_fungus_host": us_m.get(us_path.name, {})},
        "build_utc": _utc_now(),
        "crop_host_taxa": _file_meta(taxa_path, "rules/crop_host_taxa.csv"),
        "genus_synonyms": _file_meta(syn_path, "rules/genus_synonyms.csv"),
        "counts": {"genera": int(len(genera)), "genera_passing": int(genera["passes_filter"].sum()),
                   "host_genera": int(host["genus"].nunique()),
                   "species_documented": int(host.drop_duplicates("genus")["n_species_documented"].sum()),
                   "usda_rows": int(len(usda)), "usda_bad_lines": int(st["bad_lines"])},
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, indent=2))
    c = meta["counts"]
    print(f"KB built: {c['genera']} FungalTraits genera ({c['genera_passing']} pass), {c['host_genera']} USDA genera "
          f"with documented species, {c['usda_rows']} USDA records ({c['usda_bad_lines']} bad lines) -> {out_dir}")
    return meta


def load_kb(processed: Path = PROCESSED) -> KB:
    """Load the built tables, meta and synonyms. Raises FileNotFoundError if the KB has not been built."""
    processed = Path(processed)
    files = [processed / n for n in (GENERA_TABLE, HOST_TABLE, META_FILE)]
    if not all(f.exists() for f in files):
        raise FileNotFoundError("Knowledge base not built: run scripts/12_build_kb.py")
    return KB(genera=pd.read_parquet(files[0]), host=pd.read_parquet(files[1]),
              synonyms=load_genus_synonyms(), meta=json.loads(files[2].read_text()))
