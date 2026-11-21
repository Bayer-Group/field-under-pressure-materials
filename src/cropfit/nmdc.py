"""NMDC / NEON soil-metagenome parsing: sample names, KO tables, Kraken2, GOTTCHA2.

Unit of analysis is one *metagenome* (up to 3 composite cores share it); it is keyed by
the KO data-object id (or the Kraken2 id when there is no KO table).
"""
from __future__ import annotations

import re
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA, RULES, light_filter

NMDC_DIR = DATA / "nmdc"

# NB: 2022 NEON names have a single depth field (STER_006-M-21-20220607), so y is optional.
NAME_RE = re.compile(
    r"^(?P<site>[A-Z]{4})_(?P<plotnum>\d{3})-(?P<hz>[MO])-(?P<x>[\d.]+)(?:-(?P<y>[\d.]+))?-(?P<date>\d{8})$"
)

MARKERS = ["K03043", "K03553", "K02950", "K02967", "K02982"]
MIN_KO_GENES = 50_000
MIN_MARKER_MEAN = 20

# Used only when rules/ko_panel.csv does not exist.
DEFAULT_PANEL = {
    "n_fixation": {"K02588": "nifH", "K02586": "nifD", "K02591": "nifK"},
    "nitrification": {"K10944": "pmoA-amoA", "K10945": "amoB", "K10946": "amoC", "K10535": "hao"},
    "denitrification": {"K00370": "narG/nxrA", "K00371": "narH/nxrB", "K02567": "napA",
                        "K00368": "nirK", "K15864": "nirS", "K04561": "norB"},
    "nosZ": {"K00376": "nosZ"},
    "dnra": {"K03385": "nrfA", "K00362": "nirB"},
    "urease": {"K01428": "ureC", "K01429": "ureB", "K01430": "ureA"},
    "p_mobilisation": {"K01113": "phoD", "K01077": "phoA", "K00117": "gcd", "K06137": "pqqC", "K01093": "appA"},
    "acdS": {"K01505": "acdS"},
    "chitinase": {"K01183": "chiA"},
    "phlD": {"K15431": "phlD"},
    "hcnA": {"K10814": "hcnA"},
    "marker": {"K03043": "rpoB", "K03553": "recA", "K02950": "rpsL", "K02967": "rpsB", "K02982": "rpsC"},
}

BIO_GROUPS = ["nitrification", "denitrification", "nosZ", "p_mobilisation",
              "n_fixation", "phlD", "acdS", "chitinase"]
BIO_GENERA = ["Bradyrhizobium", "Pseudomonas", "Streptomyces", "Bacillus", "Nitrospira", "Nitrosospira"]
CHEM_COLS = {"ph": "ph_mean", "temp_c": "temp_c", "water_content_g_per_g": "water_content_g_per_g",
             "org_carb_pct": "org_carb_pct", "nitro_pct": "nitro_pct",
             "carb_nitro_ratio": "carb_nitro_ratio", "ammonium_nitrogen": "ammonium_nitrogen"}


# ------------------------------------------------------------------ names / samples
def parse_sample_name(name: str) -> dict | None:
    m = NAME_RE.match(name)
    if not m:
        return None
    d = m.groupdict()
    d["plotID"] = f"{d['site']}_{d['plotnum']}"
    d["date"] = f"{d['date'][:4]}-{d['date'][4:6]}-{d['date'][6:]}"
    return d


def load_samples(nmdc_dir: Path = NMDC_DIR) -> pd.DataFrame:
    """samples.csv with parsed names, horizon M only, rows with a metagenome_key (in light mode its plots only)."""
    s = pd.read_csv(nmdc_dir / "samples.csv")
    parsed = [parse_sample_name(n) for n in s["name"]]
    bad = [n for n, p in zip(s["name"], parsed) if p is None]
    if bad:
        warnings.warn(f"{len(bad)} sample names do not match the regex, dropped: {bad[:3]}")
    s = s[[p is not None for p in parsed]].copy()
    parsed = [p for p in parsed if p is not None]
    for k in ("plotID", "hz", "date"):
        s[k] = [p[k] for p in parsed]
    other = s[s["hz"] != "M"]
    if len(other):
        warnings.warn(f"{len(other)} non-M horizon samples dropped")
    s = s[s["hz"] == "M"]
    nokey = s["metagenome_key"].isna() | (s["metagenome_key"] == "")
    if nokey.any():
        warnings.warn(f"{int(nokey.sum())} samples without a metagenome (no KO/Kraken2 object) dropped")
    return light_filter(s[~nokey]).reset_index(drop=True)


def object_paths(nmdc_dir: Path = NMDC_DIR, root: Path | None = None) -> dict[str, dict[str, Path]]:
    """metagenome_key -> {data_object_type: local file} via samples.csv + data_objects.csv."""
    root = root or nmdc_dir.parents[1]
    s = pd.read_csv(nmdc_dir / "samples.csv")[["id", "metagenome_key"]].dropna()
    do = pd.read_csv(nmdc_dir / "data_objects.csv")
    do = do[do["selected"].astype(str) == "True"].merge(s, left_on="biosample_id", right_on="id")
    out: dict[str, dict[str, Path]] = {}
    for r in do.itertuples():
        p = Path(r.local_path)
        p = p if p.is_absolute() else root / p
        if p.exists():
            out.setdefault(r.metagenome_key, {})[r.data_object_type] = p
    return out


# ------------------------------------------------------------------ KO
def parse_ko_counts(path: Path) -> Counter:
    """Stream a KO table (3rd column 'KO:Kxxxxx', no header); count genes per KO."""
    c: Counter = Counter()
    with open(path) as f:
        for line in f:
            parts = line.split("\t", 3)
            if len(parts) >= 3:
                ko = parts[2].strip()
                if ko.startswith("KO:"):
                    c[ko[3:]] += 1
    return c


def depth_gate(n_ko_genes, marker_mean) -> bool:
    if n_ko_genes is None or marker_mean is None:
        return False
    if pd.isna(n_ko_genes) or pd.isna(marker_mean):
        return False
    return bool(n_ko_genes >= MIN_KO_GENES and marker_mean >= MIN_MARKER_MEAN)


def load_panel() -> pd.DataFrame:
    """rules/ko_panel.csv (ko, gene, function_group) if present, else DEFAULT_PANEL."""
    f = RULES / "ko_panel.csv"
    if f.exists():
        p = pd.read_csv(f)
        p.columns = [c.strip().lower() for c in p.columns]
        p = p.rename(columns={"group": "function_group", "ko_id": "ko"})
        p = p[["ko", "gene", "function_group"]].copy()
        p["ko"] = p["ko"].astype(str).str.replace("^KO:", "", regex=True)
        if not (p["function_group"] == "marker").any():
            p = pd.concat([p, pd.DataFrame([{"ko": k, "gene": g, "function_group": "marker"}
                                            for k, g in DEFAULT_PANEL["marker"].items()])])
        return p.reset_index(drop=True)
    return pd.DataFrame([{"ko": k, "gene": g, "function_group": grp}
                         for grp, d in DEFAULT_PANEL.items() for k, g in d.items()])


# ------------------------------------------------------------------ Kraken2 / GOTTCHA2
def parse_kraken_report(path: Path) -> pd.DataFrame:
    rows = []
    with open(path) as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6:
                continue
            rows.append((float(p[0]), int(p[1]), int(p[2]), p[3].strip(), int(p[4]), p[5].strip()))
    return pd.DataFrame(rows, columns=["pct", "clade_reads", "direct_reads", "rank", "taxid", "name"])


def kraken_summary(rep: pd.DataFrame) -> dict:
    un = rep[rep["name"] == "unclassified"]
    root = rep[rep["name"] == "root"]
    bact = rep[(rep["name"] == "Bacteria") & (rep["rank"] == "D")]
    unreads = int(un["clade_reads"].iloc[0]) if len(un) else 0
    rootreads = int(root["clade_reads"].iloc[0]) if len(root) else 0
    total = unreads + rootreads
    return {
        "kraken_total_reads": total,
        "kraken_bacteria_reads": int(bact["clade_reads"].iloc[0]) if len(bact) else 0,
        "kraken_unclassified_pct": 100 * unreads / total if total else np.nan,
    }


def kraken_genus(rep: pd.DataFrame) -> pd.DataFrame:
    """genus, reads, pct_of_bacteria (genus clade reads / Bacteria clade reads x 100)."""
    bact = rep[(rep["name"] == "Bacteria") & (rep["rank"] == "D")]
    b = int(bact["clade_reads"].iloc[0]) if len(bact) else 0
    g = rep[rep["rank"] == "G"][["name", "clade_reads"]].rename(columns={"name": "genus", "clade_reads": "reads"})
    g = g.groupby("genus", as_index=False)["reads"].sum()
    g["pct_of_bacteria"] = 100 * g["reads"] / b if b else np.nan
    g["filtered"] = False
    return g


LINEAGE_RANKS = {"D": "domain", "P": "phylum", "C": "class", "O": "order", "F": "family", "G": "genus"}
_RANK_ORDER = "RDKPCOFGS"
PROKARYOTES = ("Bacteria", "Archaea")


def kraken_lineage(rep: pd.DataFrame, domains=PROKARYOTES) -> pd.DataFrame:
    """Clade reads per taxon at the main ranks, with the taxon's domain and phylum; prokaryotes only.

    Columns: rank (domain|phylum|class|order|family|genus), name, domain, phylum, reads. The report is
    depth-first, so the last taxon seen at each higher rank is the current row's ancestor. Intermediate ranks
    (D1, P2, ...) are skipped; a taxon with no phylum in its lineage gets phylum None."""
    current: dict[str, str] = {}
    rows = []
    for rank, name, reads in zip(rep["rank"], rep["name"], rep["clade_reads"]):
        base = rank[:1]
        if base not in _RANK_ORDER or base in ("U",):
            continue
        if len(rank) == 1:              # a main rank resets everything below it
            for r in _RANK_ORDER[_RANK_ORDER.index(base):]:
                current.pop(r, None)
            current[base] = name
        if rank in LINEAGE_RANKS and current.get("D") in domains:
            rows.append((LINEAGE_RANKS[rank], name, current["D"], current.get("P"), int(reads)))
    out = pd.DataFrame(rows, columns=["rank", "name", "domain", "phylum", "reads"])
    return out.groupby(["rank", "name", "domain", "phylum"], as_index=False, dropna=False)["reads"].sum()


def gottcha_genus(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, sep="\t", dtype={"NOTE": str})
    d = d[d["LEVEL"] == "genus"].copy()
    note = d["NOTE"].fillna("")
    return pd.DataFrame({"genus": d["NAME"].values, "reads": d["READ_COUNT"].values,
                         "pct_of_bacteria": np.nan,
                         "filtered": note.str.contains("Filtered out", case=False).values})


# ------------------------------------------------------------------ percentiles
def pct_within(df: pd.DataFrame, col: str, by=("site", "year"), mask=None) -> tuple[pd.Series, pd.Series]:
    """Average-rank percentile (0-100) of col within groups, over rows where mask is True."""
    mask = pd.Series(True, index=df.index) if mask is None else mask
    out = pd.Series(np.nan, index=df.index)
    n = pd.Series(np.nan, index=df.index)
    for _, idx in df[mask & df[col].notna()].groupby(list(by)).groups.items():
        out.loc[idx] = df.loc[idx, col].rank(pct=True, method="average") * 100
        n.loc[idx] = len(idx)
    return out, n
