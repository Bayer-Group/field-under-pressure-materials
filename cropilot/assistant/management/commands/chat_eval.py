"""python manage.py chat_eval [--live] [--yes] [--only id1,id2]

Runs assistant/eval/chat_scenarios.yaml end to end (router, tools, flows, state, citations, guard).
Default: FakeLLM (no API). --live: the real LLM from .env; prints the estimated usage and asks first.
Needs the demo farm (manage.py scenario switch demo_2024; best on a copy of the database: it saves reports) and, for guide citations, Qdrant + the RAG index.
"""
import logging
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

SCENARIOS = Path(__file__).resolve().parents[2] / "eval" / "chat_scenarios.yaml"
EST_TOKENS_PER_CALL = 3500


class Command(BaseCommand):
    help = "Evaluate the chat assistant on scenarios (FakeLLM by default)."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--yes", action="store_true", help="do not ask before live calls")
        parser.add_argument("--only", help="comma-separated scenario ids")

    def handle(self, *args, **o):
        logging.basicConfig(level=logging.ERROR)
        from core.models import Field

        from assistant.answer import answer
        from assistant.models import Conversation, Message
        from assistant.orchestrator.fake import demo_llm
        from assistant.orchestrator.llm import get_llm

        scenarios = yaml.safe_load(SCENARIOS.read_text())
        if o["only"]:
            keep = set(o["only"].split(","))
            scenarios = [s for s in scenarios if s["id"] in keep]
        if not Field.objects.exists():
            raise CommandError("Brak pól w bazie. Uruchom: python manage.py scenario switch demo_2024")
        if o["live"]:
            n_calls = sum(1 for s in scenarios if s.get("expect") != "no_llm")
            self.stdout.write(f"Live: ~{n_calls} wywołań LLM, ~{n_calls * EST_TOKENS_PER_CALL:,} tokenów (szacunek).")
            if not o["yes"] and input("Kontynuować? [t/N] ").strip().lower() not in ("t", "tak", "y", "yes"):
                return
            llm = get_llm()
        else:
            llm = demo_llm()

        rows, total_in, total_out, total_calls, max_call = [], 0, 0, 0, 0
        for s in scenarios:
            field = Field.objects.filter(name=s["field"]).first() if s.get("field") else None
            if s.get("field") and field is None:
                raise CommandError(f"Scenariusz {s['id']}: nie ma pola „{s['field']}”. Uruchom: python manage.py scenario switch demo_2024")
            conv = Conversation.objects.create(title=f"[eval] {s['id']}")
            msgs = [s["message"]] + list(s.get("then", []))
            replies, routes = [], []
            for m in msgs:
                Message.objects.create(conversation=conv, role="user", text=m, field=field)
                r = answer(conv, m, field, llm=llm)
                Message.objects.create(conversation=conv, role="assistant", text=r.text, citations=r.citations,
                                       meta=r.meta | {"updated_field_ids": r.updated_field_ids})
                conv.refresh_from_db()
                replies.append(r)
                routes.append(r.meta.get("route"))
            first, last = replies[0], replies[-1]
            calls = [c for r in replies for c in r.meta.get("llm_calls", [])]
            tin = sum(c["prompt_tokens"] for c in calls)
            tout = sum(c["completion_tokens"] for c in calls)
            total_in, total_out, total_calls = total_in + tin, total_out + tout, total_calls + len(calls)
            max_call = max([max_call] + [c["prompt_tokens"] + c["completion_tokens"] for c in calls])
            guide_cits = [c for c in first.citations if c.get("type") == "guide"]
            checks = {
                "route": routes[0] == s["route"],
                "cites": len(guide_cits) >= s.get("min_citations", 0),
                "no_bad": not any(b.lower() in r.text.lower() for b in s.get("must_not_contain", []) for r in replies),
            }
            exp = s.get("expect")
            if exp == "chart":
                checks["expect"] = first.chart is not None
            elif exp == "observation_draft":
                checks["expect"] = bool(first.pending_action)
            elif exp == "observation_saved":
                checks["expect"] = any("Zapisałem obserwację" in r.text for r in replies) and \
                    (len(replies) < 3 or "już zapisana" in replies[-1].text)
            elif exp == "no_llm":
                checks["expect"] = not calls
            if o["live"] and s.get("must_contain_any"):
                checks["contains"] = any(p.lower() in last.text.lower() for p in s["must_contain_any"])
            ok = all(checks.values())
            rows.append((s["id"], routes[0], s["route"], len(guide_cits), len(calls), tin, tout, ok,
                         ", ".join(k for k, v in checks.items() if not v), first.text))

        w = self.stdout.write
        w(f"\n{'scenariusz':26} {'trasa':20} {'cyt':>3} {'LLM':>3} {'tok in/out':>12}  wynik")
        for sid, route, exp_route, ncit, ncalls, tin, tout, ok, failed, _ in rows:
            mark = self.style.SUCCESS("OK") if ok else self.style.ERROR(f"FAIL: {failed}")
            route_txt = route if route == exp_route else f"{route}≠{exp_route}"
            w(f"{sid:26} {route_txt:20} {ncit:>3} {ncalls:>3} {tin:>6}/{tout:<5}  {mark}")
        passed = sum(r[7] for r in rows)
        typical = [r for r in rows if r[1] not in ("poza_zakresem", "potwierdzenie")]
        w(f"\n{passed}/{len(rows)} scenariuszy OK · wywołań LLM: {total_calls} · tokeny in/out: {total_in}/{total_out} "
          f"· maks. na wywołanie: {max_call} · wywołań na typowe pytanie: "
          f"{max((r[4] for r in typical), default=0)} (maks.)")
        if not o["live"]:
            w("(FakeLLM: treść odpowiedzi nie jest oceniana — must_contain_any sprawdzane tylko z --live)")
