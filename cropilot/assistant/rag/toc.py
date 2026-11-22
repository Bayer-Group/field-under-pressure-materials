"""Section structure: TOC parsing + heading matching -> sections.json.

sections.json: {doc_id: {"method": "toc"|"fonts", "entries": [...], "unmatched": [...],
                         "coverage": float, "body_style": [...]}}
entry: {section_id, number, level, title, printed_page, pdf_page_start, block_idx,
        matched, path}
`path` is the list of titles from the top level down to this entry (with numbers).

Use `assign(pages, entries)` to annotate every block with its section entry index.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

import pymupdf
from rapidfuzz import fuzz

from . import config
from .docs import load_docs, select
from .pdf_parse import load_pages
from .textfix import fix_mojibake, norm_ws

ROMAN_RE = re.compile(r"^(?P<num>[IVXL]+)\.\s*(?P<title>.*)$")
ARABIC_RE = re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,2})*)\.?\s+(?P<title>\D.*)$")
LEADER_RE = re.compile(r"^(?P<body>.*?)\s*(?:\.{2,}|…+|(?<=[a-ząćęłńóśźżA-Z)])\.)\s*(?P<page>\d{1,3})\s*$")
NUM_ONLY_RE = re.compile(r"^(?:[IVXL]+|\d{1,2}(?:\.\d{1,2})*)\.?$")
NO_SECTION = "(bez sekcji)"


# ----------------------------------------------------------------------------- TOC
def _toc_lines(pdf: pymupdf.Document, pdf_pages: list[int]) -> list[list[str]]:
    """Cleaned TOC lines, one list per TOC page (page numbers kept: columnar TOCs need them)."""
    out = []
    for pp in pdf_pages:
        raw = pdf[pp - 1].get_text("text")
        raw = re.sub(r"\ufffd+|\t", " .... ", raw)  # leader glyphs / tabs -> dots
        lines = []
        for line in raw.splitlines():
            line = norm_ws(fix_mojibake(line))
            if not line or re.match(r"spis treści", line, re.I):
                continue
            lines.append(line)
        out.append(lines)
    return out


PAGE_ONLY_RE = re.compile(r"^\.*\s*(\d{1,3})$")
DOTS_END_RE = re.compile(r"(\.{2,}|…+)\s*$")


def parse_toc(pages: list[list[str]]) -> list[dict]:
    """'number title ..... page' entries; wrapped lines are joined.

    Two layouts:
    * inline: the page number ends the line (most guides);
    * columnar: titles end with dots and the page numbers come as a separate column
      (e.g. barley for advisors); numbers are then matched to titles in order, per page.
    """
    entries: list[dict] = []
    for lines in pages:
        inline, buf = [], ""
        titles, numbers, tbuf = [], [], ""
        for line in lines:
            if PAGE_ONLY_RE.match(line) and not tbuf:
                numbers.append(int(PAGE_ONLY_RE.match(line).group(1)))
                continue
            if NUM_ONLY_RE.match(line) and "." not in line.rstrip("."):
                continue  # a lone chapter number column ("1.", "2.", ...); "3.6." stays
            buf = f"{buf} {line}".strip() if buf else line
            m = LEADER_RE.match(buf)
            if m:
                body = re.sub(r"(\s*\.{2,}\s*)+", " ", m.group("body")).strip(" .")
                inline.append(_parse_number(body) | {"printed_page": int(m.group("page"))})
                buf, tbuf = "", ""
                continue
            tbuf = f"{tbuf} {line}".strip() if tbuf else line
            if DOTS_END_RE.search(tbuf):
                titles.append(re.sub(r"(\s*(\.{2,}|…+)\s*)+$", "", tbuf).strip())
                tbuf, buf = "", ""
        if len(titles) > len(inline) and numbers:
            # columnar page: pair titles with the number column in reading order
            for title, page in zip(titles, numbers):
                entries.append(_parse_number(title) | {"printed_page": page})
        else:
            entries += inline
    return _assign_levels(_infer_chapter_numbers(entries))


def _infer_chapter_numbers(entries: list[dict]) -> list[dict]:
    """Unnumbered chapter titles in an arabic-numbered TOC get N from the next 'N.x.' entry,
    else previous chapter + 1 (barley: 'WSTĘP' = 1, 'PRZEPISY PRAWNE …' = 2 because 2.1 follows)."""
    if not any(e["kind"] == "arabic" for e in entries) or any(e["kind"] == "roman" for e in entries):
        return entries
    if sum(e["kind"] == "none" for e in entries) < 3:
        return entries  # a few unnumbered extras (e.g. "Literatura") stay as they are
    last = 0
    for i, e in enumerate(entries):
        if e["kind"] == "arabic" and "." not in e["number"].rstrip("."):
            last = int(e["number"].rstrip("."))
        if e["kind"] != "none":
            continue
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        sub_of = int(nxt["number"].split(".")[0]) if nxt and nxt["kind"] == "arabic" \
            and nxt["number"].count(".") >= 2 else None
        n = sub_of if sub_of and sub_of > last else last + 1
        e.update(kind="arabic", number=f"{n}.")
        last = n
    return entries


def _parse_number(body: str) -> dict:
    m = ROMAN_RE.match(body)
    if m and m.group("title"):
        return {"number": m.group("num") + ".", "kind": "roman", "title": m.group("title").strip()}
    m = ARABIC_RE.match(body)
    if m:
        return {"number": m.group("num") + ".", "kind": "arabic", "title": m.group("title").strip()}
    return {"number": None, "kind": "none", "title": body.strip()}


def _assign_levels(entries: list[dict]) -> list[dict]:
    has_roman = any(e["kind"] == "roman" for e in entries)
    roman = None
    for e in entries:
        if e["kind"] == "roman":
            roman = e["number"].rstrip(".")
            e["level"] = 1
            e["section_id"] = roman
        elif e["kind"] == "arabic":
            parts = e["number"].rstrip(".").split(".")
            e["level"] = len(parts) + (1 if has_roman else 0)
            e["section_id"] = ".".join(([roman] if has_roman and roman else []) + parts)
        else:
            e["level"] = 1
            e["section_id"] = _slug(e["title"])
    return entries


_PL = str.maketrans("ąćęłńóśźż", "acelnoszz")


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", t.lower().translate(_PL)).strip("_")[:30]


# ----------------------------------------------------------------------------- matching
def _norm_words(t: str) -> str:
    t = re.sub(r"^\s*(?:[IVXL]+|\d{1,2}(?:\.\d{1,2})*)\.?\s+", "", t)
    return " ".join(re.sub(r"[^a-ząćęłńóśźż0-9 ]+", " ", t.lower()).split())


def body_style(pages: list[dict]) -> tuple:
    c: Counter = Counter()
    for p in pages:
        for b in p["blocks"]:
            if b["kind"] == "para":
                c[(b["font"], b["size"])] += len(b["text"])
    return c.most_common(1)[0][0] if c else ("", 0)


def is_heading_like(b: dict, body: tuple) -> bool:
    if b["kind"] != "para" or len(b["text"]) > 160:
        return False
    def fam(f):
        return re.split(r"[-,]", f or "")[0].replace("MT", "").replace("PS", "").lower()
    return (b["size"] > body[1] * 1.04 or b["bold"]
            or (fam(b["font"]) != fam(body[0]) and b["size"] >= body[1] * 0.98))


def _printed_to_pdf(pages: list[dict]) -> dict[int, int]:
    m = {}
    for p in pages:
        if p["printed_page"] is not None and p["printed_page"] not in m:
            m[p["printed_page"]] = p["pdf_page"]
    return m


def match_entries(entries: list[dict], pages: list[dict]) -> None:
    body = body_style(pages)
    p2p = _printed_to_pdf(pages)
    offs = Counter(p["pdf_page"] - p["printed_page"] for p in pages if p["printed_page"] is not None)
    off = offs.most_common(1)[0][0] if offs else 0
    by_pdf = {p["pdf_page"]: p for p in pages}
    last = (0, -1)
    for e in entries:
        exp = p2p.get(e["printed_page"], e["printed_page"] + off)
        target = _norm_words(e["title"])
        best = None
        for pp in [exp, exp + 1, exp - 1, exp + 2, exp - 2, exp + 3]:
            page = by_pdf.get(pp)
            if not page:
                continue
            for bi, b in enumerate(page["blocks"]):
                if b["kind"] != "para" or (pp, bi) <= last:
                    continue
                head = b["text"][: len(e["title"]) + 40]
                cand = _norm_words(head)
                if not cand:
                    continue
                score = fuzz.ratio(target, cand[: len(target) + 3])
                if score < 80:
                    continue
                starts_num = bool(e["number"]) and bool(
                    re.match(re.escape(e["number"].rstrip(".")) + r"\.?\s", b["text"]))
                styled = is_heading_like(b, body)
                if not (styled or starts_num):
                    continue
                score += 10 * starts_num + 5 * styled - 2 * abs(pp - exp)
                if score >= 85 and (best is None or score > best[0]):
                    best = (score, pp, bi)
            if best and best[0] >= 100:
                break
        if best:
            e.update(pdf_page_start=best[1], block_idx=best[2], matched=True)
            last = (best[1], best[2])
        else:
            e.update(pdf_page_start=exp, block_idx=0, matched=False)


# ----------------------------------------------------------------------------- fallback
def detect_headings(pages: list[dict]) -> list[dict]:
    """No TOC: headings = bold (non-italic) or large-font short lines."""
    sizes = Counter()
    for p in pages:
        for b in p["blocks"]:
            if b["kind"] == "para":
                sizes[b["size"]] += len(b["text"])
    med = sizes.most_common(1)[0][0] if sizes else 11
    entries = []
    top = None
    for p in pages:
        if p["skip"]:
            continue
        for bi, b in enumerate(p["blocks"]):
            if b["kind"] != "para" or len(b["text"]) > config.HEADING_MAX_CHARS:
                continue
            if "italic" in (b["font"] or "").lower():
                continue
            if not (b["bold"] or b["size"] >= med * config.HEADING_SIZE_RATIO):
                continue
            t = b["text"].strip()
            m = ARABIC_RE.match(t)
            letters = [c for c in re.split(r"\s[–-]\s", t)[0] if c.isalpha()]
            upper = sum(c.isupper() for c in letters) / max(len(letters), 1)
            if m and top is not None:
                parts = m.group("num").split(".")
                entries.append({"number": m.group("num") + ".", "kind": "arabic", "title": m.group("title"),
                                "level": 1 + len(parts), "section_id": f"{top}.{'.'.join(parts)}",
                                "printed_page": p["printed_page"], "pdf_page_start": p["pdf_page"],
                                "block_idx": bi, "matched": True})
            elif upper > 0.6 and len(letters) >= 6:
                prev = entries[-1] if entries else None
                if prev and prev["level"] == 1 and prev["pdf_page_start"] == p["pdf_page"] \
                        and prev["block_idx"] == bi - 1:
                    prev["title"] += "; " + t  # two diseases described together
                    continue
                top = _slug(t.split("–")[0])
                entries.append({"number": None, "kind": "none", "title": t, "level": 1,
                                "section_id": top, "printed_page": p["printed_page"],
                                "pdf_page_start": p["pdf_page"], "block_idx": bi, "matched": True})
    return entries


# ----------------------------------------------------------------------------- paths / assign
def build_paths(entries: list[dict]) -> None:
    stack: list[dict] = []
    for e in entries:
        while stack and stack[-1]["level"] >= e["level"]:
            stack.pop()
        stack.append(e)
        e["path"] = [(f"{x['number']} {x['title']}" if x["number"] else x["title"]) for x in stack]


def assign(pages: list[dict], entries: list[dict]) -> dict[tuple[int, int], int]:
    """(pdf_page, block_idx) -> entry index (the last entry starting at or before it)."""
    starts = sorted(((e["pdf_page_start"], e["block_idx"], i) for i, e in enumerate(entries)))
    out = {}
    j, cur = 0, None
    for p in pages:
        for bi, _ in enumerate(p["blocks"]):
            while j < len(starts) and (starts[j][0], starts[j][1]) <= (p["pdf_page"], bi):
                cur = starts[j][2]
                j += 1
            if cur is not None:
                out[(p["pdf_page"], bi)] = cur
    return out


def build_sections(doc_id: str, pdf_path) -> dict:
    pages = load_pages(doc_id)
    toc_pages = [p["pdf_page"] for p in pages if p["skip_reason"] == "toc"]
    body = body_style([p for p in pages if not p["skip"]])
    if toc_pages:
        pdf = pymupdf.open(pdf_path)
        entries = parse_toc(_toc_lines(pdf, toc_pages))
        match_entries(entries, pages)
        method = "toc"
    else:
        entries = detect_headings(pages)
        method = "fonts"
    # keep document order even if a match landed out of order
    entries.sort(key=lambda e: (e["pdf_page_start"], e["block_idx"]))
    build_paths(entries)
    a = assign(pages, entries)
    content = [p for p in pages if not p["skip"]]
    covered = sum(1 for p in content if any((p["pdf_page"], bi) in a for bi in range(len(p["blocks"]))))
    return {
        "method": method,
        "body_style": list(body),
        "entries": entries,
        "unmatched": [f"{e['number'] or ''} {e['title']} (s. {e['printed_page']})" for e in entries if not e["matched"]],
        "coverage": round(covered / max(len(content), 1), 3),
    }


def load_sections() -> dict:
    return json.loads(config.SECTIONS_JSON.read_text())


def run(doc_ids: list[str] | None = None, all_crops: bool = False, verbose: bool = False) -> None:
    docs = load_docs()
    out = load_sections() if config.SECTIONS_JSON.exists() else {}
    for d in select(doc_ids, all_crops):
        s = build_sections(d.doc_id, config.METODYKI_DIR / docs[d.doc_id]["file"])
        out[d.doc_id] = s
        n = len(s["entries"])
        lv = Counter(e["level"] for e in s["entries"])
        print(f"[toc] {d.doc_id:22} method={s['method']:5} entries={n:3} levels={dict(sorted(lv.items()))} "
              f"matched={n - len(s['unmatched'])}/{n} page_coverage={s['coverage']:.1%}")
        for u in s["unmatched"]:
            print(f"      unmatched: {u}")
        if verbose:
            for e in s["entries"]:
                print(f"      {'  ' * (e['level'] - 1)}{e['section_id']:12} pdf={e['pdf_page_start']:3}"
                      f"/b{e['block_idx']:<2} s.{e['printed_page']} {'' if e['matched'] else '!!'} {e['title'][:70]}")
    config.SECTIONS_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append")
    ap.add_argument("--all-crops", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    run(a.doc, a.all_crops, a.verbose)
