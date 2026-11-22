"""python manage.py rag_search "query" [--crop pszenica] [--k 5] [--mode hybrid]
   python manage.py rag_search --risk pszenica "rdza brunatna"

Same as `python -m assistant.rag.cli`.
"""
from django.core.management.base import BaseCommand, CommandError

from assistant.rag import cli


class Command(BaseCommand):
    help = "Search the guides from the terminal (or look up the risk spreadsheet with --risk)."

    def add_arguments(self, parser):
        parser.add_argument("query", nargs="?")
        parser.add_argument("--crop")
        parser.add_argument("--audience", choices=["doradcy", "producenci"])
        parser.add_argument("--k", type=int, default=6)
        parser.add_argument("--mode", choices=["hybrid", "dense", "bm25"], default="hybrid")
        parser.add_argument("--include-doses", action="store_true")
        parser.add_argument("--risk", metavar="CROP")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--full", action="store_true")

    def handle(self, *args, **o):
        argv = [o["query"]] if o["query"] else []
        for key in ("crop", "audience", "risk"):
            if o[key]:
                argv += [f"--{key}", o[key]]
        argv += ["--k", str(o["k"]), "--mode", o["mode"]]
        argv += [f"--{k.replace('_', '-')}" for k in ("include_doses", "json", "full") if o[k]]
        code = cli.main(argv)
        if code:
            raise CommandError(f"rag search failed (exit code {code})")
