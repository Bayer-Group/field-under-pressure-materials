"""Retrieval evaluation: hit@1/3/5 and MRR for dense / bm25 / hybrid x stemming variants.

    python assistant/eval/run_eval.py      # from the repo root
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from assistant.rag.flags import has_pesticide_dose_text  # noqa: E402
from assistant.rag.search import _store, search  # noqa: E402

CONFIGS = [  # (label, mode, stemmer)
    ("dense", "dense", None),
    ("bm25/stempel", "bm25", "stempel"),
    ("bm25/trunc6", "bm25", "trunc6"),
    ("hybrid/stempel", "hybrid", "stempel"),
    ("hybrid/trunc6", "hybrid", "trunc6"),
]


def is_hit(p, exp: list[dict]) -> bool:
    text = p.text.lower()
    for e in exp:
        phrases = e["contains"] if isinstance(e["contains"], list) else [e["contains"]]
        if p.doc_id == e["doc_id"] and all(x.lower() in text for x in phrases):
            return True
    return False


def evaluate(questions: list[dict], mode: str, stemmer: str | None, k: int = 5):
    hits = {1: 0, 3: 0, 5: 0}
    rr = 0.0
    fails = []
    for q in questions:
        res = search(q["q"], crop=q.get("crop"), k=k, mode=mode, bm25_stemmer=stemmer)
        rank = next((i for i, p in enumerate(res, 1) if is_hit(p, q["expected"])), None)
        for n in hits:
            hits[n] += rank is not None and rank <= n
        rr += 1 / rank if rank else 0
        if rank is None or rank > 5:
            fails.append((q, res))
    n = len(questions)
    return {f"hit@{x}": hits[x] / n for x in hits} | {"MRR": rr / n}, fails


def check_traps(traps: list[dict]):
    store = _store()
    out = []
    for q in traps:
        res = search(q["q"], crop=q.get("crop"), k=5)
        flagged = []
        # verify against the stored flag of every chunk (merged passages included)
        payloads = store.get_by_chunk_id([p.chunk_id for p in res])
        for p in res:
            if payloads.get(p.chunk_id, {}).get("has_pesticide_doses"):
                flagged.append(p.chunk_id)
        dose_text = [p.chunk_id for p in res if has_pesticide_dose_text(p.text)]
        out.append((q["q"], flagged, dose_text, res))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(Path(__file__).with_name("questions.yaml")))
    ap.add_argument("--show-failures", action="store_true", default=True)
    a = ap.parse_args()
    qs = yaml.safe_load(open(a.file))
    normal = [q for q in qs if q.get("type") != "trap"]
    traps = [q for q in qs if q.get("type") == "trap"]
    print(f"{len(normal)} pytań + {len(traps)} pułapek o dawki\n")

    results = {}
    for label, mode, stem in CONFIGS:
        results[label] = evaluate(normal, mode, stem)
    print(f"{'tryb':18} {'hit@1':>6} {'hit@3':>6} {'hit@5':>6} {'MRR':>6}")
    for label, (m, _) in results.items():
        print(f"{label:18} {m['hit@1']:6.2f} {m['hit@3']:6.2f} {m['hit@5']:6.2f} {m['MRR']:6.3f}")

    for label in ("hybrid/stempel",):
        fails = results[label][1]
        print(f"\nPorażki ({label}, brak trafienia w top 5): {len(fails)}")
        for q, res in fails:
            print(f"  ✗ {q['q']}  [crop={q.get('crop')}]")
            for i, p in enumerate(res[:5], 1):
                print(f"      {i}. {p.doc_id:20} {p.section[-70:]!s:70} | {p.text[:70]!r}")

    print("\nPułapki (domyślne filtry, top 5):")
    ok = True
    for q, flagged, dose_text, _ in check_traps(traps):
        status = "OK" if not flagged else "BŁĄD"
        ok &= not flagged
        print(f"  [{status}] {q}  has_pesticide_doses w top5: {len(flagged)}; "
              f"fragmenty z dawką środka (regex): {len(dose_text)}")
    h5 = results["hybrid/stempel"][0]["hit@5"]
    print(f"\nCel hybrid hit@5 ≥ 0.80: {'TAK' if h5 >= 0.8 else 'NIE'} ({h5:.2f})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
