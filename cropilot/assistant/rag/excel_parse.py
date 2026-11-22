"""ryzyka_zebrane.xlsx -> risk_conditions.json + chunks (doc_id="ryzyka_zebrane").

Sheets are not clean tables: free-text blocks + several tables with different headers.
Heuristics:
* header row = >= 2 non-empty cells and one of them names a threat column
  (choroba/agrofag/szkodnik) or >= 2 cells name conditions (temperatura/wilgotność...);
* an optional helper row right below (first cell empty, short labels, e.g. "dzień | noc")
  is appended to the column names;
* records follow until an empty row, a single-cell row or the next header;
* everything else becomes `kind="note"` records (grouped consecutive rows under a title).
"""
from __future__ import annotations

import json
import re

import openpyxl

from . import config
from .chunker import ntok, words, write_chunks
from .textfix import norm_ws

SHEET_CROP = {"burak cukrowy": "burak", "kukurydza": "kukurydza", "pszenica": "pszenica",
              "słonecznik": "slonecznik", "ziemniak": "ziemniak"}
THREAT_HDR = re.compile(r"chorob|agrofag|szkodnik", re.I)
COND_HDR = re.compile(r"temperat|wilgot|deszcz|nasłonecz|czynnik|sprzyja|etap", re.I)
TEMP_HDR = re.compile(r"temperat|dzień|noc", re.I)
HUM_HDR = re.compile(r"wilgot|deszcz", re.I)

_N = r"-?\d+(?:[.,]\d+)?"
RANGE_RE = re.compile(rf"({_N})\s*°?\s*C?\s*[-–−]\s*({_N})\s*°?")
APPROX_RE = re.compile(rf"\b(?:ok\.?|około)\s*({_N})", re.I)
GT_RE = re.compile(rf"(?:>|powyżej)\s*({_N})")
LT_RE = re.compile(rf"(?:<|\bdo|poniżej)\s*({_N})\s*°")
OPT_RE = re.compile(rf"optimum\s*({_N})\s*°?\s*C?\s*(?:[-–−]\s*({_N}))?", re.I)


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def parse_temp(raw: str | None) -> dict:
    """'15-25', '4–18', 'ok 20', '25–30°C (optimum 18–22°C)' -> min/max (°C). None if unclear."""
    out = {"temp_min_c": None, "temp_max_c": None, "temp_opt_min_c": None, "temp_opt_max_c": None,
           "temp_approx": False}
    if not raw or not re.search(r"\d", raw):
        return out
    s = raw
    m = OPT_RE.search(s)
    if m:
        out["temp_opt_min_c"] = _f(m.group(1))
        out["temp_opt_max_c"] = _f(m.group(2) or m.group(1))
        s = s[:m.start()] + s[m.end():]
    ranges = RANGE_RE.findall(s)
    if len({r for r in ranges}) > 1:
        return out  # several different ranges (e.g. per species) -> do not guess
    if ranges:
        a, b = _f(ranges[0][0]), _f(ranges[0][1])
        out["temp_min_c"], out["temp_max_c"] = min(a, b), max(a, b)
        return out
    if (m := APPROX_RE.search(s)):
        out["temp_min_c"] = out["temp_max_c"] = _f(m.group(1))
        out["temp_approx"] = True
    elif (m := GT_RE.search(s)):
        out["temp_min_c"] = _f(m.group(1))
    elif (m := LT_RE.search(s)):
        out["temp_max_c"] = _f(m.group(1))
    elif re.fullmatch(rf"\s*{_N}\s*°?\s*C?\s*", s):
        out["temp_min_c"] = out["temp_max_c"] = _f(s.strip(" °C"))
    return out


def _threat_type(header: str) -> str:
    h = header.lower()
    if "szkodnik" in h and "chorob" in h:
        return "inne"
    if "chorob" in h:
        return "choroba"
    if "szkodnik" in h:
        return "szkodnik"
    return "inne"  # e.g. "Agrofag": ambiguous, do not guess


def _cell(v) -> str:
    return norm_ws(str(v)) if v is not None else ""


def _is_header(cells: dict[int, str]) -> bool:
    if len(cells) < 2:
        return False
    vals = list(cells.values())
    if any(len(v) > 60 for v in vals):
        return False
    return any(THREAT_HDR.search(v) for v in vals) or sum(bool(COND_HDR.search(v)) for v in vals) >= 2


def _is_title(t: str, nxt: dict[int, str] | None) -> bool:
    """A title ends with ':' or is a short line followed by a blank row / a table header."""
    if t.endswith(":"):
        return True
    return len(t) < 80 and not t.endswith(".") and (not nxt or _is_header(nxt))


def parse_sheet(ws) -> list[dict]:
    crop = SHEET_CROP.get(ws.title.strip().lower(), ws.title.strip().lower())
    rows: list[tuple[int, dict[int, str]]] = []
    for r in ws.iter_rows():
        cells = {c.column: _cell(c.value) for c in r if _cell(c.value)}
        rows.append((r[0].row, cells))
    recs: list[dict] = []
    i, title, note_buf, note_title = 0, None, [], None
    title_row: int | None = None

    def flush_note():
        nonlocal note_buf, note_title
        if note_buf:
            text = "\n".join(t for _, t in note_buf)
            recs.append({"kind": "note", "crop": crop, "sheet": ws.title, "row": note_buf[0][0],
                         "row_end": note_buf[-1][0], "title": note_title, "text": text})
            note_title = None  # a title belongs to the first block after it only
        note_buf = []

    while i < len(rows):
        rno, cells = rows[i]
        if not cells:
            flush_note()
            i += 1
            continue
        if _is_header(cells):
            flush_note()
            note_title = None
            names = dict(cells)
            orig = dict(cells)
            tbl_title = title if title_row is not None and rno - title_row <= 2 else None
            j = i + 1
            # helper row (e.g. "dzień | noc"): first column empty, short labels
            if j < len(rows) and rows[j][1] and min(rows[j][1]) > min(cells) \
                    and all(len(v) < 25 for v in rows[j][1].values()):
                for col, sub in rows[j][1].items():
                    parent = orig.get(col) or next((orig[c] for c in sorted(orig, reverse=True) if c < col), "")
                    names[col] = f"{parent} {sub}".strip() if parent and parent != sub else sub
                j += 1
            threat_col = next((c for c in sorted(names) if THREAT_HDR.search(names[c])), min(names))
            # a column whose values are mostly "..°C" is a temperature column whatever its header
            k = j
            body_rows = []
            while k < len(rows) and len(rows[k][1]) >= 2 and not _is_header(rows[k][1]):
                body_rows.append(rows[k][1])
                k += 1
            temp_data_cols = {c for c in names if c != threat_col and body_rows and
                              sum("°" in r.get(c, "") for r in body_rows) >= 0.5 * len(body_rows)}
            header_txt = " | ".join(names[c] for c in sorted(names))
            while j < len(rows) and len(rows[j][1]) >= 2 and not _is_header(rows[j][1]):
                r2, vals = rows[j]
                cols = {names.get(c, f"kol_{c}"): v for c, v in sorted(vals.items())}
                temp_cols = [names[c] for c in sorted(names)
                             if (TEMP_HDR.search(names[c]) or c in temp_data_cols) and c in vals]
                hum_cols = [names[c] for c in sorted(names) if HUM_HDR.search(names[c]) and c in vals and c != threat_col]
                temp_raw = "; ".join(f"{n}: {cols[n]}" if len(temp_cols) > 1 else cols[n] for n in temp_cols) or None
                hum_raw = "; ".join(cols[n] for n in hum_cols) or None
                other = {n: v for n, v in cols.items()
                         if n != names.get(threat_col) and n not in temp_cols and n not in hum_cols}
                rec = {"kind": "row", "crop": crop, "sheet": ws.title, "row": r2,
                       "table_title": tbl_title, "table_header": header_txt,
                       "threat": vals.get(threat_col, ""),
                       "threat_type": _threat_type(names[threat_col]),
                       "temperature_raw": temp_raw, "humidity_raw": hum_raw,
                       "other_factors": "; ".join(f"{k}: {v}" for k, v in other.items()) or None,
                       "columns": cols}
                rec |= parse_temp(cols[temp_cols[0]] if temp_cols else None)
                recs.append(rec)
                j += 1
            i = j
            continue
        # free text
        text = " | ".join(cells.values()) if len(cells) > 1 else next(iter(cells.values()))
        if len(cells) == 2 and len(list(cells.values())[0]) < 40:
            a, b = list(cells.values())
            text = f"{a}: {b}"
        if rno == 1 and len(cells) == 1 and len(text) < 40:
            i += 1  # sheet title row
            continue
        nxt = rows[i + 1][1] if i + 1 < len(rows) else None
        if len(cells) == 1 and not note_buf and _is_title(text, nxt):
            flush_note()
            note_title = text.rstrip(":")
            title, title_row = note_title, rno  # also the title of a table right below
        else:
            note_buf.append((rno, text))
        i += 1
    flush_note()
    return recs


def _row_text(r: dict) -> str:
    lines = [f"Zagrożenie: {r['threat']} ({r['threat_type']})"]
    for k, v in r["columns"].items():
        if v != r["threat"]:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def to_chunks(recs: list[dict]) -> list[dict]:
    out = []
    for r in recs:
        if r["kind"] == "row":
            path = [f"arkusz: {r['sheet']}", r["table_title"] or r["table_header"]]
            text = _row_text(r)
            kind = "excel_row"
            sid = f"{r['crop']}.r{r['row']:03d}"
        else:
            path = [f"arkusz: {r['sheet']}", r["title"] or "notatka"]
            text = (f"{r['title']}:\n" if r["title"] else "") + r["text"]
            kind = "excel_note"
            sid = f"{r['crop']}.n{r['row']:03d}"
        header = f"{config.EXCEL_TITLE} | {' > '.join(path)} | uprawa: {r['crop']}"
        embed = f"{header}\n\n{text}"
        out.append({
            "chunk_id": f"{config.EXCEL_DOC_ID}:{sid}",
            "doc_id": config.EXCEL_DOC_ID, "doc_title": config.EXCEL_TITLE,
            "crop": r["crop"], "audience": "zestawienie",
            "section_path": path, "section_id": sid, "subheading": None,
            "pdf_page_start": None, "pdf_page_end": None,
            "printed_page_start": None, "printed_page_end": None,
            "sheet": r["sheet"], "row": r["row"], "row_end": r.get("row_end", r["row"]),
            "kind": kind, "text": text, "embed_text": embed,
            "n_tokens": ntok(embed), "n_words": words(text),
            "flags": {"has_pesticide_doses": False, "has_fertilizer_doses": False, "is_legal": False},
            "prev_id": None, "next_id": None,
        })
    return out


def run(all_sheets: bool = True) -> tuple[list[dict], list[dict]]:
    wb = openpyxl.load_workbook(config.EXCEL_FILE, data_only=True)
    recs = []
    for ws in wb.worksheets:
        recs += parse_sheet(ws)
    for n, r in enumerate(recs):
        r["id"] = f"{r['crop']}:{r['kind']}:{r['row']}"
    config.RISK_JSON.write_text(json.dumps(recs, ensure_ascii=False, indent=1))
    ch = to_chunks(recs)
    write_chunks(ch, {config.EXCEL_DOC_ID})
    over = [c["chunk_id"] for c in ch if c["n_tokens"] > config.CHUNK_MAX_TOKENS]
    by = {}
    for r in recs:
        by.setdefault(r["sheet"], {"row": 0, "note": 0, "temp_parsed": 0})
        by[r["sheet"]][r["kind"]] += 1
        by[r["sheet"]]["temp_parsed"] += r.get("temp_min_c") is not None or r.get("temp_max_c") is not None
    print(f"[excel] records={len(recs)} chunks={len(ch)} >{config.CHUNK_MAX_TOKENS}tok={len(over)} per sheet={by}")
    return recs, ch


if __name__ == "__main__":
    run()
