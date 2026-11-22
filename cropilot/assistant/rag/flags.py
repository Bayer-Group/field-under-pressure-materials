"""Content flags. The assistant must NOT recommend plant-protection products or doses;
`has_pesticide_doses` lets search() filter such chunks out by default."""
from __future__ import annotations

import re

# leaf-section titles whose content is about products/doses
PEST_SECTION_RE = re.compile(
    r"(?<!nie)\bchemiczn\w* (metody|ochron)|łączne stosowanie herbicydów|zaprawianie|"
    r"odporność .*na środki ochrony|dobór środk\w* ochrony roślin",
    re.I,
)
_NUM = r"\d+(?:[.,]\d+)?(?:\s*[-–−]\s*\d+(?:[.,]\d+)?)?"
DOSE_RE = re.compile(rf"{_NUM}\s*(?:l|ml|g|kg)\s*/\s*ha\b", re.I)
PEST_CTX_RE = re.compile(
    r"herbicyd|fungicyd|insektycyd|zapraw|środ(?:ek|ka|ki|ków|kiem|kami)\b|substancj\w* czynn|"
    r"preparat|\b(?:SL|EC|SC|WG|SE|OD|WP|EW|ZC|FS|CS|ME|SG|DC)\b",
)
FERT_RE = re.compile(
    r"kg\s*(?:/\s*ha\s*)?(?:N|P2O5|P₂O₅|K2O|K₂O|MgO|CaO|S)\b|\bP2O5\b|\bK2O\b|\bMgO\b|dawk\w* azotu|"
    r"kg\s*N\s*/\s*ha|N\s*/\s*ha\b",
)
NOT_PEST_DOSE_RE = re.compile(r"ciecz|wod[ayę]|nawo[żz]|azot|wysiew|wysiać|nasion|ziarn|plon", re.I)
LEGAL_RE = re.compile(r"przepis\w* prawn", re.I)


def has_pesticide_dose_text(text: str, window: int = 150) -> bool:
    for m in DOSE_RE.finditer(text):
        ctx = text[max(0, m.start() - window): m.end() + window]
        near = text[max(0, m.start() - 40): m.end() + 40]
        if PEST_CTX_RE.search(ctx) and not FERT_RE.search(near) and not NOT_PEST_DOSE_RE.search(near):
            return True
    return False


def compute_flags(text: str, section_path: list[str]) -> dict:
    leaf = section_path[-1] if section_path else ""
    return {
        "has_pesticide_doses": bool(PEST_SECTION_RE.search(leaf)) or has_pesticide_dose_text(text),
        "has_fertilizer_doses": bool(FERT_RE.search(text)),
        "is_legal": any(LEGAL_RE.search(s) for s in section_path),
    }
