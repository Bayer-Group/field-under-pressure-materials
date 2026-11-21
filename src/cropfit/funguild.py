"""FUNGuild: ecological guild of fungal genera (Nguyen et al. 2016, Fungal Ecology 20:241-248).

The database is one JSON list served at FUNGUILD_URL (keyless). Each record names a taxon, its trophic mode, its
guilds (one marked as primary with |pipes|) and a confidence ranking (Possible / Probable / Highly Probable).
Used by the soil-functions view to say what the fungi of one sample do (decomposers, plant pathogens,
mycorrhizal partners, parasites of other fungi). Genus level only: a genus marked "Plant Pathogen" also contains
harmless species.
"""
from __future__ import annotations

import json
import re

import pandas as pd

from . import http
from .config import PROCESSED, RAW

FUNGUILD_URL = "http://www.stbates.org/funguild_db.php"
RAW_FILE = RAW / "kb" / "funguild" / "funguild_db.json"
OUT_FILE = PROCESSED / "fungal_guilds.parquet"
GENUS_LEVEL = "13"

# primary guild -> category shown to users
CATEGORY = [
    ("Arbuscular Mycorrhizal", "arbuscular_mycorrhizal"),
    ("Ectomycorrhizal", "other_mycorrhizal"), ("Ericoid Mycorrhizal", "other_mycorrhizal"),
    ("Orchid Mycorrhizal", "other_mycorrhizal"),
    ("Fungal Parasite", "fungal_parasite"),
    ("Plant Pathogen", "plant_pathogen"), ("Plant Parasite", "plant_pathogen"),
    ("Endophyte", "endophyte"),
    ("Saprotroph", "saprotroph"),
    ("Animal Pathogen", "animal_or_lichen"), ("Animal Parasite", "animal_or_lichen"),
    ("Lichen", "animal_or_lichen"),
]


def parse_records(text: str) -> pd.DataFrame:
    """The served page wraps a JSON list in HTML; return its records as a table."""
    return pd.DataFrame(json.loads(text[text.index("["): text.rindex("]") + 1]))


def primary_guild(guild: str) -> str | None:
    """'Endophyte-|Plant Pathogen|-Plant Saprotroph' -> 'Plant Pathogen' (the |marked| one, else the only one)."""
    if not isinstance(guild, str) or not guild.strip():
        return None
    m = re.search(r"\|([^|]+)\|", guild)
    if m:
        return m.group(1).strip()
    parts = [p.strip() for p in guild.split("-") if p.strip()]
    return parts[0] if len(parts) == 1 else None


def category(guild: str | None) -> str:
    if not isinstance(guild, str) or not guild:
        return "unknown"
    return next((c for key, c in CATEGORY if key in guild), "other")


def guild_table(records: pd.DataFrame) -> pd.DataFrame:
    """One row per genus: trophic mode, all guilds, primary guild, its category, whether any guild is a plant
    pathogen, and FUNGuild's confidence."""
    g = records[records["taxonomicLevel"].astype(str) == GENUS_LEVEL].copy()
    g["guilds"] = g["guild"].fillna("").str.replace("|", "", regex=False)
    g["primary_guild"] = g["guild"].map(primary_guild)
    g["category"] = g["primary_guild"].map(category)
    g["can_be_plant_pathogen"] = g["guilds"].str.contains("Plant Pathogen|Plant Parasite", regex=True)
    g["can_parasitise_fungi"] = g["guilds"].str.contains("Fungal Parasite", regex=False)
    g["confidence"] = g["confidenceRanking"].replace({"Higly Probable": "Highly Probable"})
    g = g.rename(columns={"taxon": "genus", "trophicMode": "trophic_mode"})
    rank = {"Highly Probable": 0, "Probable": 1, "Possible": 2}
    g = g.sort_values("confidence", key=lambda s: s.map(rank).fillna(3)).drop_duplicates("genus")
    return g[["genus", "trophic_mode", "guilds", "primary_guild", "category", "can_be_plant_pathogen",
              "can_parasitise_fungi", "confidence"]].sort_values("genus").reset_index(drop=True)


def fetch() -> pd.DataFrame:
    """Download the database once (kept under data/raw/kb/funguild/) and write fungal_guilds.parquet."""
    if not RAW_FILE.exists():
        RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
        text = http.get(FUNGUILD_URL, timeout=180).text
        tmp = RAW_FILE.with_suffix(".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(RAW_FILE)
    t = guild_table(parse_records(RAW_FILE.read_text(encoding="utf-8")))
    t.to_parquet(OUT_FILE, index=False)
    return t
