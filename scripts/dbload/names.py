"""Voivodeship names -> partition slugs (e.g. 'Kujawsko-Pomorskie' -> 'kujawsko_pomorskie')."""
from __future__ import annotations

import re
import unicodedata

# Some delivered file names lost the Polish letters 'Ł' / 'ł' (e.g. 'odzkie', 'Maopolskie').
_LOST_LETTER = {"odzkie": "lodzkie", "maopolskie": "malopolskie"}


def voiv_slug(name: str) -> str:
    """Lower-case ASCII slug with underscores; also maps the names that lost their Polish letters."""
    s = name.replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return _LOST_LETTER.get(s, s)
