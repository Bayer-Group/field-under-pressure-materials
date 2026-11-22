"""Sections -> chunks.jsonl (PDF chunks). Excel chunks are added by excel_parse.py.

Rules:
* a chunk never crosses the lowest-level section boundary;
* text is packed by paragraphs (long paragraphs split by sentences) to ~180-280 words,
  hard limit CHUNK_MAX_TOKENS on `embed_text` measured with the model tokenizer;
* overlap: last 1-2 sentences (<= 50 words) of the previous chunk of the same section;
* sections < 60 words are carried into the next chunk of the same parent section;
* tables are separate chunks (markdown), split by rows with the header repeated;
* unnumbered sub-headings (e.g. a disease name) start a new chunk and are kept in
  `subheading` so they also land in the contextual header.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter
from functools import lru_cache

from . import config
from .docs import load_docs, select
from .flags import compute_flags
from .pdf_parse import CAPTION_RE, load_pages
from .toc import NO_SECTION, NUM_ONLY_RE, assign, body_style, is_heading_like, load_sections

SENT_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ„(•–-])")
CROP_LABEL = {"zboza": "zboża", "slonecznik": "słonecznik", "jeczmien": "jęczmień",
              "zyto": "żyto", "pszenzyto": "pszenżyto"}


# ----------------------------------------------------------------------------- tokens
@lru_cache(maxsize=1)
def tokenizer():
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(config.EMBED_MODEL)
    tok.model_max_length = 10**6  # we measure, the model truncates; silence the warning
    return tok


def ntok(text: str) -> int:
    return len(tokenizer()(text, add_special_tokens=True)["input_ids"])


def words(text: str) -> int:
    return len(text.split())


def sentences(text: str) -> list[str]:
    return [s for s in SENT_SPLIT_RE.split(text) if s.strip()]


# ----------------------------------------------------------------------------- helpers
def context_header(doc_title: str, path: list[str], sub: str | None, crop: str) -> str:
    sec = " > ".join(path + ([sub] if sub else []))
    return f"{doc_title} | {sec} | uprawa: {CROP_LABEL.get(crop, crop)}"


def _split_long(text: str, max_tokens: int) -> list[str]:
    """Split by sentences (then by words as a last resort) to fit max_tokens."""
    out, cur = [], ""
    for s in sentences(text):
        cand = f"{cur} {s}".strip()
        if cur and ntok(cand) > max_tokens:
            out.append(cur)
            cur = s
        else:
            cur = cand
    if cur:
        out.append(cur)
    res = []
    for piece in out:
        if ntok(piece) <= max_tokens:
            res.append(piece)
            continue
        # last resort: greedy by words, measured with the tokenizer (Latin names, tables
        # and numbers have far more tokens per word than running Polish text)
        cur_w: list[str] = []
        for w in piece.split():
            if cur_w and ntok(" ".join(cur_w + [w])) > max_tokens:
                res.append(" ".join(cur_w))
                cur_w = []
            cur_w.append(w)
        if cur_w:
            res.append(" ".join(cur_w))
    return res


def _overlap(text: str) -> str:
    sents = sentences(text)
    for n in (2, 1):
        tail = " ".join(sents[-n:])
        if len(sents) > n and words(tail) <= config.OVERLAP_MAX_WORDS:
            return tail
    return ""


# ----------------------------------------------------------------------------- items
def _is_subheading(b: dict, text: str, body: tuple) -> bool:
    """Unnumbered sub-heading (e.g. a disease name). Bold *sentences* are not headings."""
    if not is_heading_like(b, body) or CAPTION_RE.match(text) or text.startswith("•"):
        return False
    if words(text) > 12 or re.search(r"[.!?]\s+[A-ZĄĆĘŁŃÓŚŹŻ]", text):
        return False
    return not (text.endswith(".") and words(text) > 5)


def _items(pages: list[dict], sec: dict) -> list[dict]:
    entries = sec["entries"]
    amap = assign(pages, entries)
    heading_blocks = {(e["pdf_page_start"], e["block_idx"]) for e in entries if e["matched"]}
    body = tuple(sec.get("body_style") or body_style(pages))
    items: list[dict] = []
    for p in pages:
        if p["skip"]:
            continue
        for bi, b in enumerate(p["blocks"]):
            key = (p["pdf_page"], bi)
            if key in heading_blocks:
                continue
            ent = amap.get(key)
            base = {"pdf_page": p["pdf_page"], "printed_page": p["printed_page"], "entry": ent}
            if b["kind"] == "table":
                t = p["tables"][b["table_idx"]]
                items.append(base | {"type": "table", "markdown": t["markdown"], "n_cols": t["n_cols"]})
                continue
            text = b["text"].strip()
            if not text or NUM_ONLY_RE.match(text):
                continue  # empty or a lone heading number ("I.") split from its title
            if b.get("cont"):
                # continuation of a paragraph from the previous page: glue to the last
                # body paragraph of the same section, skipping captions in between
                for prev in reversed(items[-4:]):
                    if prev["type"] == "para" and prev["entry"] == ent and not prev["sub"] \
                            and not CAPTION_RE.match(prev["text"]):
                        prev["text"] = (prev["text"][:-1] + text) if re.search(r"[^\W\d_]-$", prev["text"]) \
                            else f"{prev['text']} {text}"
                        prev["pdf_page_end"] = p["pdf_page"]
                        prev["printed_page_end"] = p["printed_page"]
                        break
                else:
                    items.append(base | {"type": "para", "text": text, "sub": False})
                continue
            sub = _is_subheading(b, text, body)
            items.append(base | {"type": "para", "text": text, "sub": sub,
                                 "sub_label": re.split(r"\s[–-]\s", text)[0].strip() if sub else None})
    return items


# ----------------------------------------------------------------------------- packing
class _Builder:
    def __init__(self, doc: dict, sec: dict):
        self.doc, self.sec = doc, sec
        self.chunks: list[dict] = []
        self.seq: Counter = Counter()
        self.last_table: dict | None = None

    def path_of(self, ent):
        if ent is None:
            return [NO_SECTION], "bez_sekcji"
        e = self.sec["entries"][ent]
        return e["path"], e["section_id"]

    def emit(self, kind, text, ent, sub, pages):
        path, sid = self.path_of(ent)
        header = context_header(self.doc["title"], path, sub, self.doc["crop"])
        embed = f"{header}\n\n{text}"
        if ntok(embed) > config.CHUNK_MAX_TOKENS:
            # hard guarantee of the token limit (e.g. one huge table row, dense Latin text)
            for piece in _split_long(text, config.CHUNK_MAX_TOKENS - ntok(header) - 4):
                self.emit(kind, piece, ent, sub, pages)
            return
        n = self.seq[sid]
        self.seq[sid] += 1
        pdfp = [x[0] for x in pages]
        prp = [x[1] for x in pages if x[1] is not None]
        self.chunks.append({
            "chunk_id": f"{self.doc['doc_id']}:{sid}:{n:04d}",
            "doc_id": self.doc["doc_id"],
            "doc_title": self.doc["title"],
            "crop": self.doc["crop"],
            "audience": self.doc["audience"],
            "section_path": path,
            "section_id": sid,
            "subheading": sub,
            "pdf_page_start": min(pdfp), "pdf_page_end": max(pdfp),
            "printed_page_start": min(prp) if prp else None,
            "printed_page_end": max(prp) if prp else None,
            "kind": kind,
            "text": text,
            "embed_text": embed,
            "n_tokens": ntok(embed),
            "n_words": words(text),
            "flags": compute_flags(text, path),
        })

    def budget(self, ent, sub) -> int:
        path, _ = self.path_of(ent)
        return config.CHUNK_MAX_TOKENS - ntok(context_header(self.doc["title"], path, sub, self.doc["crop"])) - 2

    # -- text
    def pack_text(self, paras: list[dict], ent, prefix: str = "", prefix_pages=()):
        cur: list[str] = [prefix] if prefix else []
        cur_pages: list[tuple] = list(prefix_pages)
        sub = None
        overlap_ok = False

        def flush():
            nonlocal cur, cur_pages, overlap_ok
            text = "\n\n".join(cur).strip()
            if text:
                for piece in self._fit(text, ent, sub):
                    self.emit("text", piece, ent, sub, cur_pages)
                ov = _overlap(text)
                cur = [ov] if ov else []
                overlap_ok = bool(ov)
            else:
                cur = []
            cur_pages = cur_pages[-1:] if cur else []

        for it in paras:
            pg = [(it["pdf_page"], it["printed_page"])]
            if it.get("pdf_page_end"):
                pg.append((it["pdf_page_end"], it.get("printed_page_end")))
            if it["sub"]:
                real = [c for c in cur if c]
                if real and (words("\n\n".join(real)) >= config.SMALL_SECTION_WORDS or overlap_ok):
                    if not (overlap_ok and len(real) == 1):
                        flush()
                    cur, cur_pages = [], []  # no overlap across sub-headings
                sub = it.get("sub_label") or it["text"]
                cur.append(it["text"])
                cur_pages += pg
                overlap_ok = False
                continue
            budget = self.budget(ent, sub)
            for piece in ([it["text"]] if ntok(it["text"]) <= budget * 0.9 else _split_long(it["text"], int(budget * 0.8))):
                cur_text = "\n\n".join(cur)
                w_now, w_new = words(cur_text), words(cur_text) + words(piece)
                if cur and (ntok(cur_text + "\n\n" + piece) > budget
                            or (w_now >= config.CHUNK_TARGET_MIN_WORDS and w_new > config.CHUNK_TARGET_MAX_WORDS)):
                    only_overlap = overlap_ok and len(cur) == 1
                    if not only_overlap:
                        flush()
                    else:
                        cur = []
                cur.append(piece)
                cur_pages += pg
                overlap_ok = False
        real = [c for c in cur if c]
        if real and not (overlap_ok and len(real) == 1):
            flush()

    def _fit(self, text: str, ent, sub) -> list[str]:
        if ntok(text) <= self.budget(ent, sub):
            return [text]
        return _split_long(text, self.budget(ent, sub))

    # -- tables
    def table(self, it: dict, ctx: str, ent):
        md = it["markdown"]
        lines = md.splitlines()
        header, rows = lines[:2], lines[2:]
        cont = bool(re.search(r"\bcd\.?|ciąg dalszy", ctx, re.I)) or not ctx
        lt = self.last_table
        if cont and lt and lt["n_cols"] == it["n_cols"] and lt["entry"] == ent \
                and it["pdf_page"] - lt["pdf_page"] <= 2 and lines[0] != lt["header"][0]:
            rows = lines  # this page's table has no header: reuse the previous one
            header = lt["header"]
            ctx = f"{lt['ctx']} (cd.)" if lt["ctx"] else ctx
        self.last_table = {"n_cols": it["n_cols"], "entry": ent, "pdf_page": it["pdf_page"],
                           "header": header, "ctx": ctx if not re.search(r"\bcd\.", ctx, re.I) else (lt or {}).get("ctx", ctx)}
        path, _ = self.path_of(ent)
        budget = min(config.TABLE_MAX_TOKENS, self.budget(ent, None))
        pre = (ctx + "\n\n") if ctx else ""
        part: list[str] = []
        pages = [(it["pdf_page"], it["printed_page"])]
        for r in rows:
            cand = pre + "\n".join(header + part + [r])
            if part and ntok(cand) > budget:
                self.emit("table", pre + "\n".join(header + part), ent, None, pages)
                part = []
            part.append(r)
        if part:
            self.emit("table", pre + "\n".join(header + part), ent, None, pages)

    # -- driver
    def run(self, items: list[dict]):
        runs: list[tuple] = []
        for it in items:
            if runs and runs[-1][0] == it["entry"]:
                runs[-1][1].append(it)
            else:
                runs.append((it["entry"], [it]))
        carry, carry_pages, carry_path = "", [], None
        for ri, (ent, its) in enumerate(runs):
            path, _ = self.path_of(ent)
            paras = [i for i in its if i["type"] == "para"]
            total_words = sum(words(i["text"]) for i in paras)
            nxt = runs[ri + 1][0] if ri + 1 < len(runs) else None
            nxt_path = self.path_of(nxt)[0] if ri + 1 < len(runs) else None
            prefix, ppages = "", []
            if carry and carry_path is not None:
                prefix, ppages = carry, carry_pages
                carry, carry_pages, carry_path = "", [], None
            # small section with no tables: carry into the next chunk of the same parent
            same_parent = nxt_path is not None and (nxt_path[:len(path) - 1] == path[:-1] or nxt_path[:len(path)] == path)
            if total_words < config.SMALL_SECTION_WORDS and not any(i["type"] == "table" for i in its) \
                    and same_parent and ent is not None:
                title = path[-1]
                body = "\n\n".join(i["text"] for i in paras)
                carry = "\n\n".join(x for x in (prefix, f"{title}: {body}" if body else "") if x)
                carry_pages = ppages + [(i["pdf_page"], i["printed_page"]) for i in paras]
                carry_path = path if carry else None
                continue
            buf: list[dict] = []
            for k, it in enumerate(its):
                if it["type"] == "table":
                    if buf and CAPTION_RE.match(buf[-1]["text"]) and words(buf[-1]["text"]) <= 60:
                        buf.pop()  # the caption becomes the table's context line
                    self.pack_text(buf, ent, prefix, ppages)
                    prefix, ppages, buf = "", [], []
                    prev = its[k - 1] if k else None
                    ctx = ""
                    if prev and prev["type"] == "para":
                        ctx = prev["text"] if CAPTION_RE.match(prev["text"]) and words(prev["text"]) <= 60 \
                            else (sentences(prev["text"]) or [""])[-1]
                        if words(ctx) > 50:
                            ctx = " ".join(ctx.split()[:50]) + "…"
                    self.table(it, ctx, ent)
                else:
                    buf.append(it)
            self.pack_text(buf, ent, prefix, ppages)
        if carry:  # trailing small section with nowhere to go
            self.pack_text([], None if carry_path is None else ent, carry, carry_pages)


def chunk_doc(doc: dict, pages: list[dict], sec: dict) -> list[dict]:
    b = _Builder(doc, sec)
    b.run(_items(pages, sec))
    ch = b.chunks
    for i, c in enumerate(ch):
        c["prev_id"] = ch[i - 1]["chunk_id"] if i else None
        c["next_id"] = ch[i + 1]["chunk_id"] if i + 1 < len(ch) else None
    return ch


# ----------------------------------------------------------------------------- io
def load_chunks(doc_id: str | None = None) -> list[dict]:
    if not config.CHUNKS_JSONL.exists():
        return []
    with open(config.CHUNKS_JSONL) as f:
        return [c for c in map(json.loads, f) if doc_id is None or c["doc_id"] == doc_id]


def write_chunks(new: list[dict], doc_ids: set[str]) -> None:
    keep = [c for c in load_chunks() if c["doc_id"] not in doc_ids]
    with open(config.CHUNKS_JSONL, "w") as f:
        for c in keep + new:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def chunk_stats(ch: list[dict]) -> str:
    if not ch:
        return "0 chunks"
    t = sorted(c["n_tokens"] for c in ch)
    w = [c["n_words"] for c in ch if c["kind"] == "text"]
    p95 = t[min(len(t) - 1, int(0.95 * len(t)))]
    return (f"chunks={len(ch)} text={sum(c['kind'] == 'text' for c in ch)} table={sum(c['kind'] == 'table' for c in ch)} "
            f"tokens min/med/p95/max={t[0]}/{int(statistics.median(t))}/{p95}/{t[-1]} "
            f"words(text) med={int(statistics.median(w)) if w else 0} >{config.CHUNK_MAX_TOKENS}tok={sum(x > config.CHUNK_MAX_TOKENS for x in t)}")


def run(doc_ids: list[str] | None = None, all_crops: bool = False) -> list[dict]:
    docs = load_docs()
    secs = load_sections()
    out = []
    sel = select(doc_ids, all_crops)
    for d in sel:
        t = time.time()
        ch = chunk_doc(docs[d.doc_id], load_pages(d.doc_id), secs[d.doc_id])
        print(f"[chunker] {d.doc_id:22} {chunk_stats(ch)}  {time.time() - t:.1f}s")
        out += ch
    ids = [c["chunk_id"] for c in out]
    assert len(ids) == len(set(ids)), "duplicate chunk_id"
    write_chunks(out, {d.doc_id for d in sel})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append")
    ap.add_argument("--all-crops", action="store_true")
    a = ap.parse_args()
    run(a.doc, a.all_crops)
