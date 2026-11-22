"""python manage.py rag_ingest  — build the guide search index (PDFs + risk spreadsheet -> Qdrant + BM25).

Same as `python -m assistant.rag.ingest`. Needs `docker compose up -d qdrant`.
"""
from django.core.management.base import BaseCommand, CommandError

from assistant.rag import ingest


class Command(BaseCommand):
    help = "Build the assistant's RAG index over the crop-protection guides (Qdrant + BM25)."

    def add_arguments(self, parser):
        parser.add_argument("--doc", action="append", help="doc_id (repeatable); 'ryzyka_zebrane' = the spreadsheet")
        parser.add_argument("--all-crops", action="store_true", help="also the 10 non-core guides")
        parser.add_argument("--rebuild", action="store_true", help="drop and recreate the Qdrant collection")
        parser.add_argument("--skip-index", action="store_true", help="only parse and chunk")

    def handle(self, *args, **opts):
        argv = [a for d in (opts["doc"] or []) for a in ("--doc", d)]
        argv += [f"--{k.replace('_', '-')}" for k in ("all_crops", "rebuild", "skip_index") if opts[k]]
        code = ingest.main(argv)
        if code:
            raise CommandError(f"rag ingest failed (exit code {code})")
