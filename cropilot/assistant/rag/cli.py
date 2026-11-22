"""CLI search.

    python -m assistant.rag.cli "w jakiej temperaturze rozwija się septorioza paskowana" --crop pszenica --k 5
    python -m assistant.rag.cli --risk pszenica "rdza brunatna"
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap

from .store import QdrantUnavailable


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?")
    ap.add_argument("--crop")
    ap.add_argument("--audience", choices=["doradcy", "producenci"])
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--mode", choices=["hybrid", "dense", "bm25"], default="hybrid")
    ap.add_argument("--include-doses", action="store_true", help="do not filter out pesticide-dose chunks")
    ap.add_argument("--risk", metavar="CROP", help="look up the risk spreadsheet instead (query = threat)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--full", action="store_true", help="print full text, not the first 300 chars")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    from .search import get_risk_conditions, search

    if a.risk:
        rows = get_risk_conditions(a.risk, a.query)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        if not rows:
            print("Brak dopasowań.")
        for r in rows:
            t = (r["temp_min_c"], r["temp_max_c"])
            print(f"[{r.get('match_score', '-')}] {r['threat']} ({r['threat_type']}) — arkusz „{r['sheet']}”, wiersz {r['row']}")
            print(f"    temperatura: {r['temperature_raw']}  -> min/max °C: {t[0]}/{t[1]}")
            print(f"    wilgotność:  {r['humidity_raw']}")
            if r["other_factors"]:
                print(f"    inne:        {r['other_factors']}")
        return 0

    if not a.query:
        ap.error("podaj zapytanie albo --risk CROP")
    try:
        res = search(a.query, crop=a.crop, audience=a.audience, k=a.k,
                     include_pesticide_doses=a.include_doses, mode=a.mode)
    except QdrantUnavailable as e:
        print(f"BŁĄD: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps([p.to_dict() for p in res], ensure_ascii=False, indent=1))
        return 0
    for i, p in enumerate(res, 1):
        print(f"{i}. [{p.score:.4f}] {p.citation}")
        print(f"   sekcja: {p.section}   ({p.kind}, {p.chunk_id})")
        body = p.text if a.full else p.text[:300].replace("\n", " ") + ("…" if len(p.text) > 300 else "")
        print(textwrap.indent(textwrap.fill(body, 110) if not a.full else body, "   "))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
