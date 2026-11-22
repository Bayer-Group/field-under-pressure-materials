"""
Output guard: the assistant never gives plant-protection product doses (project rule).

A dose = a number + l/ha, ml/ha, g/ha, kg/ha or l/100 l within ~8 words of a plant-protection
word. Fertiliser doses (kg N/ha, P2O5, K2O, MgO, "nawożenie", "azot") and sowing rates are allowed.
"""
from __future__ import annotations

import re

from assistant.domain import fold

_NUM = r"\d+(?:[.,]\d+)?(?:\s*[-–−]\s*\d+(?:[.,]\d+)?)?"
DOSE_RE = re.compile(rf"{_NUM}\s*(?:l|ml|g|kg|dm3|cm3)\s*(?:/|na)\s*(?:ha|hektar\w*|100\s*l)\b", re.I)
PEST_WORDS = re.compile(
    r"herbicyd|fungicyd|insektycyd|zoocyd|akarycyd|moluskocyd|zapraw|srod\w*\s+ochrony|srod(?:ek|ka|ki|kow|kiem|kami)\b|"
    r"preparat|substancj\w*\s+czynn|oprysk|opryskiw|zabieg\w*\s+chemiczn", re.I)
FERT_WORDS = re.compile(r"\b(?:n|p2o5|k2o|mgo|cao|so3)\b|nawoz|nawoze|azot|fosfor|potas|magnez|wapn|siew|wysiew|nasion|ziarna\s+siewn", re.I)
SPRAY_VOLUME = re.compile(r"ciecz|\bwody\b|\bwoda\b", re.I)  # "200 l/ha cieczy użytkowej" is not a product dose

SAFE_MESSAGE = ("Nie podaję nazw ani dawek środków ochrony roślin. Dobór środka i dawki zawsze według aktualnej "
                "etykiety środka, a w razie wątpliwości skonsultuj się z doradcą rolniczym (ODR). "
                "Mogę za to opisać progi szkodliwości, terminy lustracji i metody niechemiczne.")
REGENERATE_NOTE = ("Twoja poprzednia odpowiedź zawierała dawkę środka ochrony roślin. Napisz ją ponownie BEZ "
                   "żadnych dawek i nazw środków; zamiast tego odeślij do etykiety środka i doradcy.")


def find_doses(text: str, window_words: int = 8) -> list[str]:
    """Pesticide-dose snippets found in text (empty list = safe)."""
    hits = []
    for m in DOSE_RE.finditer(text):
        before = text[: m.start()].split()[-window_words:]
        after = text[m.end():].split()[:window_words]
        ctx = fold(" ".join(before + [m.group(0)] + after))
        near = fold(" ".join(before[-3:] + after[:3]))
        per_ha = not re.search(r"100\s*l$", m.group(0), re.I)  # l/100 l = concentration, always a dose
        if PEST_WORDS.search(ctx) and not FERT_WORDS.search(near) and not (per_ha and SPRAY_VOLUME.search(near)):
            hits.append(m.group(0))
    return hits


def check(text: str) -> bool:
    """True when the text is safe (no pesticide doses)."""
    return not find_doses(text)
