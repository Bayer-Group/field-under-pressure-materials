"""python manage.py mcp_server [--no-warmup]

MCP server over stdio with the assistant's tools (assistant/mcp_server.py). Logs go to stderr;
stdout carries only the MCP protocol.
"""
import logging
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the assistant's MCP server (stdio)."

    def add_arguments(self, parser):
        parser.add_argument("--no-warmup", action="store_true", help="skip loading the model/BM25/Qdrant first")

    def handle(self, *args, **o):
        logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
        for noisy in ("httpx", "sentence_transformers", "transformers", "huggingface_hub"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        from assistant.mcp_server import main
        main(warm=not o["no_warmup"])
