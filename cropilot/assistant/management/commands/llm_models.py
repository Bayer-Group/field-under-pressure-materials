"""python manage.py llm_models — list the models each configured LLM provider offers.

Use it to pick GEMINI_MODEL / GROQ_MODEL for .env (model names change, so they are not hard-coded).
"""
from django.core.management.base import BaseCommand

from assistant.orchestrator.llm import provider_configs


class Command(BaseCommand):
    help = "List models of the configured LLM providers (LLM_PROVIDERS in .env)."

    def handle(self, *args, **o):
        from openai import OpenAI
        for c in provider_configs():
            if not c["configured"]:
                self.stdout.write(f"{c['name']}: not configured ({c['name'].upper()}_BASE_URL / _API_KEY missing)")
                continue
            try:
                models = sorted(m.id for m in OpenAI(api_key=c["api_key"], base_url=c["base_url"], max_retries=0,
                                                     timeout=20).models.list())
            except Exception as e:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"{c['name']}: {type(e).__name__}: {e}"))
                continue
            chosen = c["model"] or "(no model set)"
            self.stdout.write(self.style.SUCCESS(f"{c['name']}: {len(models)} models; configured: {chosen}"))
            for m in models:
                self.stdout.write(f"  {'*' if m.split('/')[-1] == chosen.split('/')[-1] else ' '} {m}")
