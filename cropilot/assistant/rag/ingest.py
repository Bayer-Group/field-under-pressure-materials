"""CLI: full pipeline. PDFs + Excel -> chunks -> embeddings -> Qdrant + BM25.

    python -m assistant.rag.ingest                # 5 core PDFs + Excel (or: python manage.py rag_ingest)
    python -m assistant.rag.ingest --doc pszenica_doradcy --rebuild
    python -m assistant.rag.ingest --all-crops
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from collections import Counter

from . import config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", action="append", help="doc_id (repeatable); 'ryzyka_zebrane' = the Excel file")
    ap.add_argument("--all-crops", action="store_true", help="also the 10 non-core PDFs")
    ap.add_argument("--rebuild", action="store_true", help="drop & recreate the Qdrant collection")
    ap.add_argument("--skip-index", action="store_true", help="only parse/chunk, no embeddings/Qdrant/BM25")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    t0 = time.time()

    from . import bm25, chunker, docs, excel_parse, pdf_parse, toc

    pdf_ids = [d for d in (a.doc or []) if d != config.EXCEL_DOC_ID] or None
    with_excel = not a.doc or config.EXCEL_DOC_ID in a.doc
    sel = docs.select(pdf_ids, a.all_crops) if (pdf_ids or not a.doc) else []

    # Qdrant first: fail fast with a readable message
    store = None
    if not a.skip_index:
        from .store import QdrantStore, QdrantUnavailable
        try:
            store = QdrantStore()
        except QdrantUnavailable as e:
            print(f"BŁĄD: {e}", file=sys.stderr)
            return 2

    if sel:
        docs.build_docs_json(sel)
        ids = [d.doc_id for d in sel]
        pdf_parse.run(ids)
        toc.run(ids)
        chunker.run(ids)
    if with_excel:
        excel_parse.run()

    all_chunks = chunker.load_chunks()
    touched = {d.doc_id for d in sel} | ({config.EXCEL_DOC_ID} if with_excel else set())
    if a.skip_index:
        print(f"[ingest] chunks.jsonl: {len(all_chunks)} chunks. Done in {time.time() - t0:.1f}s")
        return 0

    from .embed import dim, encode_passages
    # --rebuild re-creates the collection from everything in chunks.jsonl (vectors are cached)
    to_index = all_chunks if a.rebuild else [c for c in all_chunks if c["doc_id"] in touched]
    vecs = encode_passages([c["embed_text"] for c in to_index])
    store.ensure(dim(), rebuild=a.rebuild)
    if not a.rebuild:
        store.delete_docs(sorted(touched))  # drop stale points of re-ingested docs
    t = time.time()
    store.upsert(to_index, vecs)
    print(f"[qdrant] upserted {len(to_index)} points into '{store.collection}' in {time.time() - t:.1f}s")

    t = time.time()
    bm25.build(all_chunks)
    print(f"[bm25] index over {len(all_chunks)} chunks ({', '.join(bm25.STEMMERS)}) in {time.time() - t:.1f}s")

    n_q = store.count()
    by_doc = Counter(c["doc_id"] for c in all_chunks)
    toks = sorted(c["n_tokens"] for c in all_chunks)
    print("\n=== Statystyki indeksu ===")
    for d, n in sorted(by_doc.items()):
        print(f"  {d:22} {n:5} chunków")
    print(f"  RAZEM chunks.jsonl={len(all_chunks)}  punkty w Qdrant={n_q}  "
          f"{'OK' if n_q == len(all_chunks) else 'NIEZGODNOŚĆ!'}")
    print(f"  n_tokens min/med/p95/max = {toks[0]}/{int(statistics.median(toks))}/"
          f"{toks[int(0.95 * (len(toks) - 1))]}/{toks[-1]};  > {config.CHUNK_MAX_TOKENS}: "
          f"{sum(x > config.CHUNK_MAX_TOKENS for x in toks)}")
    fl = Counter(k for c in all_chunks for k, v in c["flags"].items() if v)
    print(f"  flagi: {dict(fl)};  kind: {dict(Counter(c['kind'] for c in all_chunks))}")
    print(f"  czas całkowity: {time.time() - t0:.1f}s")
    return 0 if n_q == len(all_chunks) else 1


if __name__ == "__main__":
    sys.exit(main())
