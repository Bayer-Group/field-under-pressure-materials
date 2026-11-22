"""PDF -> pages.jsonl.

Each page record:
  {doc_id, pdf_page (1-based), printed_page, printed_page_source, text, tables,
   blocks, font_stats, skip, skip_reason}

`blocks` is the ordered page content used downstream (toc.py, chunker.py):
  {"kind": "para", "text", "font", "size", "bold", "y0", "y1", "x0", "n_lines"}
  {"kind": "table", "table_idx", "y0", "y1"}
`text` = paragraphs joined by blank lines (tables excluded, they live in `tables`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

import pymupdf

from . import config
from .docs import load_docs, select
from .textfix import fix_mojibake, norm_ws

BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi", re.I)
LONE_NUM_RE = re.compile(r"^\d{1,4}$")
TERMINAL_RE = re.compile(r"[.:;!?)]$")
BULLET_RE = re.compile(r"^([•▪●■◦·\-–—]\s|\d{1,2}\)\s|[a-z]\)\s)")
TOC_LINE_RE = re.compile(r"(\.{3,}|…{2,}|\s{2,}|\t)\s*\d{1,3}\s*$|\.{6,}\s*$")  # also columnar TOCs
TABLES_CACHE_VERSION = 5
CAPTION_RE = re.compile(r"^(Tabela|Tab\.|Ryc\.|Rycina|Rys\.|Fot\.|Wykres|Schemat)\s*\d", re.I)
EDITORIAL_RE = re.compile(r"\bISBN\b|Nakład|Wszelkie prawa zastrzeżone|Korekta redakcyjna|Skład i łamanie|"
                          r"Autorzy zdjęć|Recenzen|Opracowanie zbiorowe|Autorzy opracowania", re.I)
PAGE_NUM_RE = re.compile(r"^\d{1,3}$")


# ----------------------------------------------------------------------------- tables
def _count_rules(page: pymupdf.Page) -> tuple[int, int]:
    h = v = 0
    for g in page.get_drawings():
        for it in g["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 1 and abs(a.x - b.x) > 20:
                    h += 1
                elif abs(a.x - b.x) < 1 and abs(a.y - b.y) > 8:
                    v += 1
            elif it[0] == "re":
                r = it[1]
                if r.height < 2 and r.width > 20:
                    h += 1
                elif r.width < 2 and r.height > 8:
                    v += 1
                elif r.width > 20 and r.height > 8:
                    h += 2
                    v += 2
    return h, v


def _cell(c) -> str:
    return norm_ws(fix_mojibake((c or "").replace("\n", " ")))


def _cell_text(words: list, bbox) -> str:
    """Words whose centre lies in the cell, in MuPDF reading order (block, line, word).

    Reading order (not y) matters: some header cells hold rotated text.
    """
    x0, y0, x1, y1 = bbox
    inside = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    lines: dict[tuple, list] = {}
    for w in inside:
        lines.setdefault((w[5], w[6]), []).append(w)
    out = ""
    for key in sorted(lines):
        txt = " ".join(w[4] for w in sorted(lines[key], key=lambda w: w[7]))
        out = _join(out, txt) if out else txt
    return _cell(out)


def _table_to_markdown(rows: list[list[str]]) -> str:
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    esc = lambda s: s.replace("|", "\\|")
    out = ["| " + " | ".join(esc(c) for c in rows[0]) + " |", "|" + "---|" * ncol]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _extract_tables(args: tuple[str, list[int]]) -> dict[int, list[dict]]:
    """Worker: run find_tables on the given 0-based pages. Returns page -> tables."""
    path, pages = args
    doc = pymupdf.open(path)
    out: dict[int, list[dict]] = {}
    for pno in pages:
        page = doc[pno]
        found = []
        words = page.get_text("words")
        cell = lambda c: _cell_text(words, c) if c else ""
        for t in page.find_tables().tables:
            # t.extract() garbles numbers ("78,9" -> "789 ,") and get_textbox() bleeds
            # into neighbouring cells, so assign words to cells by their centre point.
            rows = [[cell(c) for c in row.cells] for row in t.rows]
            if t.header.external and t.header.cells:
                rows.insert(0, [cell(c) for c in t.header.cells])
            # drop exact consecutive duplicates (multi-row headers come out repeated)
            dedup = [r for i, r in enumerate(rows) if i == 0 or r != rows[i - 1]]
            dedup = [r for r in dedup if any(r)]
            cells = [c for r in dedup for c in r]
            ncol = max((len(r) for r in dedup), default=0)
            empty = sum(1 for c in cells if not c) / max(len(cells), 1)
            if ncol < 2 or len(dedup) < 2 or empty > config.TABLE_MAX_EMPTY:
                continue  # junk: leave the page text untouched
            found.append({
                "bbox": [round(x, 1) for x in t.bbox],
                "markdown": _table_to_markdown(dedup),
                "n_rows": len(dedup),
                "n_cols": ncol,
            })
        if found:
            out[pno] = found
    return out


def find_all_tables(path: Path, n_pages: int) -> dict[int, list[dict]]:
    """find_tables on pages with ruling lines; cached by PDF sha1 (it is ~1 s/page).

    Note: a process pool made it slower on macOS (MuPDF), so this runs serially.
    """
    sha = hashlib.sha1(path.read_bytes()).hexdigest()[:16]
    cache = config.INDEX_DIR / f"tables_{sha}_v{TABLES_CACHE_VERSION}.json"
    if cache.exists():
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}
    doc = pymupdf.open(path)
    cand = [i for i in range(n_pages) if min(_count_rules(doc[i])) >= config.TABLE_MIN_RULES]
    res = _extract_tables((str(path), cand)) if cand else {}
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res, ensure_ascii=False))
    return res


# ----------------------------------------------------------------------------- lines
def _raw_lines(page: pymupdf.Page) -> list[dict]:
    lines = []
    d = page.get_text("dict", sort=True)
    for bi, b in enumerate(d["blocks"]):
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"]]
            text = norm_ws("".join(s["text"] for s in spans))
            if not text:
                continue
            dom = max(spans, key=lambda s: len(s["text"].strip()))
            bold_chars = sum(len(s["text"].strip()) for s in spans
                             if s["flags"] & 16 or BOLD_RE.search(s["font"]))
            nchar = sum(len(s["text"].strip()) for s in spans) or 1
            lines.append({
                "block": bi,
                "text": text,
                "x0": l["bbox"][0], "y0": l["bbox"][1], "x1": l["bbox"][2], "y1": l["bbox"][3],
                "font": dom["font"].split("+")[-1],
                "size": round(dom["size"], 1),
                "bold": bold_chars / nchar > 0.6,
            })
    return lines


def _sig(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def _in_band(l: dict, h: float, frac: float = config.HEADER_FOOTER_FRAC) -> bool:
    band = frac * h
    return l["y0"] <= band or l["y1"] >= h - band


def _in_bbox(l: dict, bbox) -> bool:
    cx, cy = (l["x0"] + l["x1"]) / 2, (l["y0"] + l["y1"]) / 2
    return bbox[0] - 2 <= cx <= bbox[2] + 2 and bbox[1] - 2 <= cy <= bbox[3] + 2


def _family(font: str) -> str:
    return re.split(r"[-,]", font)[0].replace("MT", "").replace("PS", "").lower()


# ----------------------------------------------------------------------------- paragraphs
def _join(prev: str, nxt: str) -> str:
    # hyphenation: "słowo-" + "kontynuacja" (letter before '-', lowercase after)
    if re.search(r"[^\W\d_]-$", prev) and re.match(r"[a-ząćęłńóśźż]", nxt):
        return prev[:-1] + nxt
    return prev + " " + nxt


def _style(l: dict) -> tuple:
    return (_family(l["font"]), round(l["size"]), l["bold"])


def _build_paragraphs(lines: list[dict]) -> list[dict]:
    paras: list[dict] = []
    by_block: dict[int, list[dict]] = {}
    for l in lines:
        by_block.setdefault(l["block"], []).append(l)
    for blines in by_block.values():
        bx0 = min(l["x0"] for l in blines)
        bx1 = max(l["x1"] for l in blines)
        cur = None
        prev = None
        for l in blines:
            new = cur is None
            if not new:
                if _style(l) != _style(prev):
                    new = True
                elif (l["x0"] - bx0 > 4 and prev["x0"] - bx0 <= 4
                      and not re.match(r"[a-ząćęłńóśźż]", l["text"])):
                    new = True  # first-line indent (not a hanging indent of a wrapped line)
                elif prev["x1"] < bx1 - 25 and TERMINAL_RE.search(prev["text"]):
                    new = True  # previous line ended short with a full stop
                elif BULLET_RE.match(l["text"]):
                    new = True
                elif l["y0"] - prev["y1"] > max(prev["size"], l["size"]) * 0.9:
                    new = True  # vertical gap
            if new:
                if cur:
                    paras.append(cur)
                cur = {"kind": "para", "text": l["text"], "font": l["font"], "size": l["size"],
                       "bold": l["bold"], "y0": round(l["y0"], 1), "y1": round(l["y1"], 1),
                       "x0": round(l["x0"], 1), "n_lines": 1}
            else:
                cur["text"] = _join(cur["text"], l["text"])
                cur["y1"] = round(l["y1"], 1)
                cur["n_lines"] += 1
            prev = l
        if cur:
            paras.append(cur)
    # merge paragraphs split across blocks (e.g. text flowing around a figure)
    merged: list[dict] = []
    for p in paras:
        q = merged[-1] if merged else None
        if (q and q["kind"] == "para" and _style(q) == _style(p)
                and not TERMINAL_RE.search(q["text"]) and re.match(r"[a-ząćęłńóśźż]", p["text"])
                and 0 <= p["y0"] - q["y1"] < 3 * p["size"]):
            q["text"] = _join(q["text"], p["text"])
            q["y1"] = p["y1"]
            q["n_lines"] += p["n_lines"]
        else:
            merged.append(p)
    return merged


# ----------------------------------------------------------------------------- main
def parse_pdf(doc_id: str, path: Path) -> list[dict]:
    doc = pymupdf.open(path)
    n = doc.page_count
    tables = find_all_tables(path, n)

    raw = []
    for pno in range(n):
        page = doc[pno]
        lines = _raw_lines(page)
        for l in lines:
            l["text"] = fix_mojibake(l["text"])
        raw.append((page.rect.height, lines))

    # running heads / feet: signature repeats on >=30% of pages, or >=3 pages inside the band
    band_count: Counter = Counter()
    for h, lines in raw:
        band_count.update({_sig(l["text"]) for l in lines if _in_band(l, h) and not LONE_NUM_RE.match(l["text"])})
    repeat_min = max(3, int(config.HEADER_REPEAT_FRAC * n)) if n < 10 else 3
    running = {s for s, c in band_count.items() if c >= repeat_min}

    # dominant body size of the document (by characters)
    size_count: Counter = Counter()
    for _, lines in raw:
        for l in lines:
            size_count[l["size"]] += len(l["text"])
    body_size = size_count.most_common(1)[0][0] if size_count else 11.0

    pages = []
    for pno, (h, lines) in enumerate(raw):
        printed = None
        keep = []
        removed = 0
        for l in lines:
            if PAGE_NUM_RE.match(l["text"]) and _in_band(l, h, config.PAGE_NUM_FRAC):
                printed = printed or int(l["text"])
                removed += 1
                continue
            if _in_band(l, h):
                if _sig(l["text"]) in running:
                    removed += 1
                    continue
            if LONE_NUM_RE.match(l["text"]) and len(l["text"]) <= 3:
                removed += 1  # chart axis labels, stray numbers
                continue
            keep.append(l)
        ptables = tables.get(pno, [])
        if ptables:
            keep = [l for l in keep if not any(_in_bbox(l, t["bbox"]) for t in ptables)]
        paras = _build_paragraphs(keep)
        # chart/figure labels: short, smaller than body text, not a caption
        paras = [p for p in paras
                 if not (p["size"] < body_size * 0.95 and len(p["text"].split()) < 6
                         and not CAPTION_RE.match(p["text"]))]
        # paragraph continued from the previous page (starts lowercase, body size)
        for p in paras:
            if p["size"] >= body_size * 0.95 and not CAPTION_RE.match(p["text"]):
                if re.match(r"[a-ząćęłńóśźż]", p["text"]):
                    p["cont"] = True
                break
        blocks = list(paras)
        for ti, t in enumerate(ptables):
            blocks.append({"kind": "table", "table_idx": ti, "y0": t["bbox"][1], "y1": t["bbox"][3]})
        blocks.sort(key=lambda b: b["y0"])
        text = "\n\n".join(p["text"] for p in paras)
        sizes = Counter()
        for l in keep:
            sizes[(l["font"], l["size"])] += len(l["text"])
        dom = sizes.most_common(1)[0][0] if sizes else (None, None)
        pages.append({
            "doc_id": doc_id,
            "pdf_page": pno + 1,
            "printed_page": printed,
            "printed_page_source": "detected" if printed is not None else None,
            "text": text,
            "tables": ptables,
            "blocks": blocks,
            "font_stats": {"dominant_font": dom[0], "dominant_size": dom[1],
                           "n_chars": sum(sizes.values()), "removed_lines": removed},
            "skip": False,
            "skip_reason": None,
        })

    _infer_printed_pages(pages)
    _mark_skips(pages)
    return pages


def _infer_printed_pages(pages: list[dict]) -> None:
    """Fill missing printed pages from the nearest detected page (constant offset)."""
    det = [(p["pdf_page"], p["printed_page"] - p["pdf_page"]) for p in pages if p["printed_page"] is not None]
    if not det:
        return
    # drop outliers: an offset must be shared by >=2 detected pages
    cnt = Counter(o for _, o in det)
    det = [(pp, o) for pp, o in det if cnt[o] >= 2]
    for p in pages:
        if p["printed_page"] is not None:
            if cnt[p["printed_page"] - p["pdf_page"]] >= 2:
                continue
            p["printed_page"] = None  # outlier (e.g. a number in a figure), re-infer below
        if not det:
            continue
        prev = [d for d in det if d[0] < p["pdf_page"]]
        pp, off = prev[-1] if prev else det[0]
        val = p["pdf_page"] + off
        if val >= 1:
            p["printed_page"] = val
            p["printed_page_source"] = "inferred"
        else:
            p["printed_page_source"] = None


def _mark_skips(pages: list[dict]) -> None:
    toc_seen_at = None
    for p in pages:
        text = p["text"]
        head = "\n".join(text.split("\n\n")[:4]).lower()
        words = len(text.split())
        lines = [b["text"] for b in p["blocks"] if b["kind"] == "para"]
        toc_like = sum(bool(TOC_LINE_RE.search(t)) for t in lines) / max(len(lines), 1)
        reason = None
        if p["pdf_page"] == 1:
            reason = "cover"
        elif "spis treści" in head:
            reason, toc_seen_at = "toc", p["pdf_page"]
        elif toc_seen_at and p["pdf_page"] - toc_seen_at <= 2 and toc_like >= 0.4:
            reason, toc_seen_at = "toc", p["pdf_page"]
        elif p["pdf_page"] <= 6 and EDITORIAL_RE.search(text):
            reason = "editorial"
        elif words < config.MIN_WORDS_PAGE and not p["tables"]:
            reason = "near_empty"
        if reason:
            p["skip"], p["skip_reason"] = True, reason


def load_pages(doc_id: str | None = None) -> list[dict]:
    out = []
    with open(config.PAGES_JSONL) as f:
        for line in f:
            p = json.loads(line)
            if doc_id is None or p["doc_id"] == doc_id:
                out.append(p)
    return out


def write_pages(new_pages: list[dict], doc_ids: set[str]) -> None:
    """Replace records of `doc_ids` in pages.jsonl, keep the other documents."""
    keep = []
    if config.PAGES_JSONL.exists():
        keep = [p for p in load_pages() if p["doc_id"] not in doc_ids]
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.PAGES_JSONL, "w") as f:
        for p in keep + new_pages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def page_stats(pages: list[dict]) -> str:
    skips = Counter(p["skip_reason"] for p in pages if p["skip"])
    srcs = Counter(p["printed_page_source"] for p in pages)
    nt = sum(len(p["tables"]) for p in pages)
    words = sum(len(p["text"].split()) for p in pages if not p["skip"])
    return (f"pages={len(pages)} skip={dict(skips)} printed_page={dict(srcs)} "
            f"tables={nt} (on {sum(bool(p['tables']) for p in pages)} pages) words(kept)={words}")


def run(doc_ids: list[str] | None = None, all_crops: bool = False) -> None:
    docs = load_docs()
    sel = select(doc_ids, all_crops)
    allp = []
    for d in sel:
        t = time.time()
        pages = parse_pdf(d.doc_id, config.METODYKI_DIR / docs[d.doc_id]["file"])
        print(f"[pdf_parse] {d.doc_id:22} {page_stats(pages)}  {time.time() - t:.1f}s")
        allp += pages
    write_pages(allp, {d.doc_id for d in sel})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append")
    ap.add_argument("--all-crops", action="store_true")
    a = ap.parse_args()
    run(a.doc, a.all_crops)
