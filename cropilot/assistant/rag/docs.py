"""Document registry -> data/processed/docs.json."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

import pymupdf

from . import config
from .textfix import fix_mojibake


@dataclass
class DocInfo:
    doc_id: str
    file: str
    crop: str
    audience: str
    core: bool = True
    title_override: str = ""   # used when page 1 has no usable title
    title: str = ""
    title_source: str = ""
    n_pages: int = 0


REGISTRY: list[DocInfo] = [
    DocInfo("kukurydza_doradcy", "Metodyka_integrowanej_ochrony_kukurydzy_dla_doradcow_2019.pdf", "kukurydza", "doradcy"),
    DocInfo("kukurydza_producenci", "kukurydzy__DLA_PRODUCENTOW.pdf", "kukurydza", "producenci"),
    DocInfo("pszenica_doradcy", "metodyka_-_PSZENICA_-_www.pdf", "pszenica", "doradcy"),
    DocInfo("pszenica_producenci", "pszenicy_ozimej_i_jarej__DLA_PRODUCENTOW.pdf", "pszenica", "producenci",
            title_override="Metodyka integrowanej ochrony pszenicy ozimej i jarej dla producentów"),  # cover = image only
    DocInfo("zboza_giorin", "PORADNIK_METODYCZNY_-_ZBOZA_GIORiN.pdf", "zboza", "producenci",
            title_override="Poradnik metodyczny dla osoby dokonującej monitorowania fuzariozy kłosów, sporyszu zbóż i traw, "
                           "śnieci cuchnącej pszenicy, śnieci karłowej pszenicy, głowni liściowej pszenicy"),
    # --all-crops
    DocInfo("jeczmien_doradcy", "Metodyka_integrowanej_ochrony_jeczmienia_ozimego_i_jarego_DLA_DORADCOW.pdf", "jeczmien", "doradcy", False,
            title_override="Metodyka integrowanej ochrony jęczmienia ozimego i jarego dla doradców"),
    DocInfo("jeczmien_producenci", "jeczmienia_ozimego_i_jarego_DLA_PRODUCENTOW.pdf", "jeczmien", "producenci", False),
    DocInfo("owies_doradcy", "Metodyka_-_OWIES_-_www.pdf", "owies", "doradcy", False),
    DocInfo("owies_producenci", "owsa_DLA_PRODUCENTOW.pdf", "owies", "producenci", False),
    DocInfo("zyto_producenci", "zyta__DLA_PRODUCENTOW.pdf", "zyto", "producenci", False,
            title_override="Metodyka integrowanej ochrony żyta dla producentów"),
    DocInfo("pszenzyto_doradcy", "Metodyka_integrowanej_ochrony_pszenzyta_dla_doradcow.pdf", "pszenzyto", "doradcy", False),
    DocInfo("pszenzyto_producenci", "pszenzyta_ozimego_i_jarego_DLA_PRODUCENTOW.pdf", "pszenzyto", "producenci", False),
    DocInfo("burak_doradcy", "Metodyka_integrowanej_ochrony_buraka_cukrowego_i_pastewnego_DLA_DORADCOW.pdf", "burak", "doradcy", False),
    DocInfo("ziemniak_doradcy", "Metodyka integrowanej ochrony ziemniaka dla doradcow.pdf", "ziemniak", "doradcy", False),
    DocInfo("slonecznik_doradcy", "Metodyka integrowanej ochrony slonecznika dla doradcow (2020).pdf", "slonecznik", "doradcy", False),
]


def select(doc_ids: list[str] | None = None, all_crops: bool = False) -> list[DocInfo]:
    docs = [d for d in REGISTRY if d.core or all_crops]
    if doc_ids:
        unknown = set(doc_ids) - {d.doc_id for d in REGISTRY}
        if unknown:
            raise SystemExit(f"Nieznane doc_id: {sorted(unknown)}")
        docs = [d for d in REGISTRY if d.doc_id in doc_ids]
    return docs


def extract_title(pdf_path) -> str:
    """Title = lines with the largest font on the first page that has text."""
    doc = pymupdf.open(pdf_path)
    for page in list(doc)[:3]:
        lines = []
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                t = "".join(s["text"] for s in l["spans"]).strip()
                if t:
                    lines.append((max(s["size"] for s in l["spans"]), l["bbox"][1], t))
        if not lines:
            continue
        top = max(sz for sz, _, _ in lines)
        sel = sorted((y, t) for sz, y, t in lines if sz >= top * 0.7)
        title = fix_mojibake(re.sub(r"\s+", " ", " ".join(t for _, t in sel)).strip())
        if title:
            return title
    return ""


def _title_ok(t: str) -> bool:
    return bool(re.match(r"(Metodyka|Poradnik)\b", t)) and len(t) < 160


def build_docs_json(docs: list[DocInfo]) -> list[dict]:
    existing = {}
    if config.DOCS_JSON.exists():
        existing = {d["doc_id"]: d for d in json.loads(config.DOCS_JSON.read_text())}
    for d in docs:
        path = config.METODYKI_DIR / d.file
        if not path.exists():
            raise SystemExit(f"Brak pliku {path}")
        extracted = extract_title(path)
        if d.title_override:
            d.title, d.title_source = d.title_override, "registry"
        elif _title_ok(extracted):
            d.title, d.title_source = extracted, "page1"
        else:
            raise SystemExit(f"{d.doc_id}: nie udało się odczytać tytułu z 1. strony ({extracted[:80]!r}); dodaj title_override")
        d.n_pages = pymupdf.open(path).page_count
        existing[d.doc_id] = asdict(d)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.DOCS_JSON.write_text(json.dumps(list(existing.values()), ensure_ascii=False, indent=1))
    return [existing[d.doc_id] for d in docs]


def load_docs() -> dict[str, dict]:
    return {d["doc_id"]: d for d in json.loads(config.DOCS_JSON.read_text())}


if __name__ == "__main__":
    import sys

    for d in build_docs_json(select(all_crops="--all-crops" in sys.argv)):
        print(f"{d['doc_id']:22} {d['n_pages']:4} [{d['title_source']:8}] {d['title']}")
