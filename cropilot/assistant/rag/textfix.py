"""Small text normalisation helpers shared by parsers."""
from __future__ import annotations

import re

# Polish letters rendered through a cp1250->cp1252 font mismatch (seen on editorial
# pages of the IOR "dla producentów" PDFs): Poznañ, redakcj¹, Pawe³, ¿ywności ...
_MOJIBAKE = str.maketrans({
    "¹": "ą", "³": "ł", "¿": "ż", "ñ": "ń", "ê": "ę", "æ": "ć",
    "œ": "ś", "Ÿ": "ź", "¥": "Ą", "£": "Ł", "¯": "Ż", "Ñ": "Ń",
    "Ê": "Ę", "Æ": "Ć", "Œ": "Ś",
})
_STRONG = re.compile("[¹³¿£¯]|[a-z][ñê]|[ñê][a-z]|[A-Z]Ñ|Ñ[A-Z]")

_PUA_BULLETS = re.compile("[]")
_CTRL = re.compile("[\x00-\x08\x0b-\x1f\x7f]")
_WS = re.compile("[ \t    ]+")


def fix_mojibake(text: str) -> str:
    """Repair cp1250/cp1252 mojibake, only if the text clearly contains it."""
    if _STRONG.search(text):
        return text.translate(_MOJIBAKE)
    return text


def norm_ws(text: str) -> str:
    text = text.replace("�", " ").replace("­", "-")
    text = _PUA_BULLETS.sub("•", text)
    text = _CTRL.sub(" ", text)
    return _WS.sub(" ", text).strip()
