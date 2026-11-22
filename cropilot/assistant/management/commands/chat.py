"""Talk to the assistant from the terminal.

    python manage.py chat --session [--live] [--field "Pole Północne"]     # interactive conversation
    python manage.py chat "pytanie" [--field ID|nazwa] [--conversation ID] [--live] [--show-prompt] [--chart-out f.json]

Default: FakeLLM (no API calls); --live uses the LLM configured in .env. Messages are saved like the
chat endpoint does. In --session mode the whole conversation is also written to
logs/chat_sessions/<conversation id>.md (gitignored) so it can be reviewed or shared.

Session commands: /pole <nazwa|id|brak>, /pola, /nowa, /prompt, /szczegoly, /koniec
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

SESSIONS_DIR = Path(__file__).resolve().parents[3] / "logs" / "chat_sessions"


def chart_title(chart: dict) -> str:
    """The chart's title as one line (Vega-Lite allows a list of lines)."""
    text = chart.get("title", {}).get("text")
    return " — ".join(text) if isinstance(text, list) else str(text)
HELP = ("Komendy: /pole <nazwa|id|brak> — zaznacz pole jak na mapie · /pola — lista pól · /nowa — nowa rozmowa · "
        "/prompt — pokaż ostatni prompt · /szczegoly — trasa, tokeny, cytaty (wł./wył.) · /koniec")


class Command(BaseCommand):
    help = "Chat with the assistant (FakeLLM by default, --live for the real model; --session = interactive)."

    def add_arguments(self, parser):
        parser.add_argument("message", nargs="?")
        parser.add_argument("--session", action="store_true", help="interactive multi-turn conversation")
        parser.add_argument("--field", help="selected field: id or name")
        parser.add_argument("--conversation", type=int, help="continue this conversation id")
        parser.add_argument("--live", action="store_true", help="use the real LLM from .env")
        parser.add_argument("--show-prompt", action="store_true")
        parser.add_argument("--chart-out", help="write the chart spec (Vega-Lite) to this file")

    # ------------------------------------------------------------------ helpers
    def _field(self, value):
        from core.models import Field
        if not value or value.lower() in ("brak", "none", "-"):
            return None
        f = (Field.objects.filter(pk=int(value)).first() if value.isdigit()
             else Field.objects.filter(name__iexact=value).first())
        if f is None:
            raise CommandError(f"Nie ma pola „{value}”. Pola: {list(Field.objects.values_list('id', 'name'))}")
        return f

    def _turn(self, conv, text, field, llm):
        from assistant.answer import answer
        from assistant.models import Message
        Message.objects.create(conversation=conv, role=Message.Role.USER, text=text, field=field)
        reply = answer(conv, text, field, llm=llm)
        Message.objects.create(conversation=conv, role=Message.Role.ASSISTANT, text=reply.text,
                               citations=reply.citations, focus_field_id=reply.focus_field_id,
                               meta=reply.meta | {"updated_field_ids": reply.updated_field_ids})
        conv.refresh_from_db()
        return reply

    def _details(self, reply, conv):
        w, meta = self.stdout.write, reply.meta
        w(self.style.MIGRATE_HEADING(f"=== trasa: {meta.get('route')} ({meta.get('route_reason')}) · rozmowa {conv.pk}"))
        for c in meta.get("llm_calls", []):
            w(f"LLM: {c['provider']}/{c['model']} in={c['prompt_tokens']} out={c['completion_tokens']} "
              f"{'(szac.)' if c.get('estimated') else ''} {c['duration_ms']} ms [{c['kind']}]")
        if "prompt_info" in meta:
            pi = meta["prompt_info"]
            w(f"prompt ≈ {pi['estimated_input_tokens']} tok.; źródła: {pi['sources']}; pominięte: {pi['dropped_sources']}")
        if meta.get("removed_citations"):
            w(self.style.WARNING(f"usunięte nieznane cytaty: {meta['removed_citations']}"))

    def _citations(self, reply):
        lines = []
        for c in reply.citations:
            if c.get("type") == "guide" and c.get("sheet"):
                lines.append(f"[{c.get('ref')}] {c['document']}, arkusz „{c['sheet']}”, wiersz {c['row']}")
            elif c.get("type") == "guide":
                lines.append(f"[{c.get('ref')}] {c['document']}, s. {c.get('printed_page') or c.get('page')} (PDF {c.get('page')})"
                             f" — {c.get('section', '')}")
            else:
                lines.append(f"ryzyko: pole {c['field_id']}, {c['threat_code']}, {c['date']}")
        return lines

    # ------------------------------------------------------------------ main
    def handle(self, *args, **o):
        logging.basicConfig(level=logging.WARNING)
        logging.getLogger("assistant").setLevel(logging.WARNING if o["session"] else logging.INFO)
        from assistant.models import Conversation
        from assistant.orchestrator.fake import demo_llm
        from assistant.orchestrator.llm import get_llm

        field = self._field(o["field"])
        llm = get_llm() if o["live"] else demo_llm()
        if o["conversation"]:
            conv = Conversation.objects.filter(pk=o["conversation"]).first()
            if conv is None:
                raise CommandError(f"Nie ma rozmowy {o['conversation']}")
        else:
            conv = None
        if o["session"]:
            return self.session(conv, field, llm, live=o["live"])
        if not o["message"]:
            raise CommandError('Podaj pytanie albo użyj --session.')
        conv = conv or Conversation.objects.create(title=Conversation.title_from(o["message"]))
        reply = self._turn(conv, o["message"], field, llm)
        w = self.stdout.write
        if o["show_prompt"] and getattr(reply, "_prompt", None):
            for m in reply._prompt:
                w(self.style.MIGRATE_HEADING(f"--- {m['role']} ---"))
                w(m["content"])
        self._details(reply, conv)
        w(self.style.SUCCESS("\n" + reply.text + "\n"))
        for line in self._citations(reply):
            w("  " + line)
        if reply.focus_field_id or reply.updated_field_ids:
            w(f"  focus_field_id={reply.focus_field_id} updated_field_ids={reply.updated_field_ids}")
        if reply.chart is not None:
            w(f"  wykres: {chart_title(reply.chart)} ({len(reply.chart.get('data', {}).get('values', []))} punktów)")
            if o["chart_out"]:
                with open(o["chart_out"], "w") as f:
                    json.dump(reply.chart, f, ensure_ascii=False, indent=1)
                w(f"  zapisano: {o['chart_out']}")
        if reply.pending_action:
            w(f"  oczekuje: {reply.pending_action['type']} → odpowiedz: manage.py chat \"tak\" --conversation {conv.pk}")

    def session(self, conv, field, llm, live: bool):
        from core.models import Field

        from assistant.models import Conversation
        from assistant.tools.registry import call

        w = self.stdout.write
        today = call("get_season_date")["today"]
        details, last = False, None
        transcript: list[str] = []

        def log_path(c):
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            return SESSIONS_DIR / f"{c.pk}.md"

        def save():
            if conv is not None:
                head = (f"# Rozmowa {conv.pk} · {'LIVE ' + llm.name if live else 'FakeLLM'} · data sezonu {today}\n"
                        f"Zapisano {datetime.now():%Y-%m-%d %H:%M}\n\n")
                log_path(conv).write_text(head + "\n".join(transcript), encoding="utf-8")

        w(self.style.MIGRATE_HEADING(
            f"Czat z asystentem · {'LIVE: ' + llm.name if live else 'FakeLLM (bez API — dodaj --live)'} · "
            f"dziś w sezonie: {today}"))
        w(HELP)
        w(f"Zaznaczone pole: {field.name if field else 'brak'}\n")
        while True:
            try:
                text = input(f"Ty{' [' + field.name + ']' if field else ''}> ").strip()
            except (EOFError, KeyboardInterrupt):
                w("")
                break
            if not text:
                continue
            if text.startswith("/"):
                cmd, _, arg = text.partition(" ")
                if cmd in ("/koniec", "/exit", "/quit"):
                    break
                if cmd == "/pole":
                    try:
                        field = self._field(arg.strip())
                        w(f"Zaznaczone pole: {field.name if field else 'brak'}")
                        transcript.append(f"*[zaznaczono pole: {field.name if field else 'brak'}]*\n")
                    except CommandError as e:
                        w(self.style.ERROR(str(e)))
                elif cmd == "/pola":
                    for f in Field.objects.select_related("crop").order_by("name"):
                        w(f"  {f.id:<4} {f.name:22} {f.crop.name}  {f.area_ha} ha")
                elif cmd == "/nowa":
                    save()
                    conv, transcript = None, []
                    w("Nowa rozmowa.")
                elif cmd == "/prompt":
                    for m in (getattr(last, "_prompt", None) or []):
                        w(self.style.MIGRATE_HEADING(f"--- {m['role']} ---"))
                        w(m["content"])
                elif cmd == "/szczegoly":
                    details = not details
                    w(f"Szczegóły: {'włączone' if details else 'wyłączone'}")
                else:
                    w(HELP)
                continue
            if conv is None:
                conv = Conversation.objects.create(title=Conversation.title_from(text))
            last = self._turn(conv, text, field, llm)
            if details:
                self._details(last, conv)
            w(self.style.SUCCESS("\nAsystent> " + last.text + "\n"))
            cits = self._citations(last)
            for line in cits:
                w("   " + line)
            if last.chart is not None:
                w(f"   [wykres: {chart_title(last.chart)} — zapisany w Message.meta]")
            if last.focus_field_id and (field is None or last.focus_field_id != field.id):
                f = Field.objects.filter(pk=last.focus_field_id).first()
                w(f"   [mapa: przybliż pole {f.name if f else last.focus_field_id}]")
            w("")
            meta = last.meta
            calls = meta.get("llm_calls", [])
            transcript.append(f"**Rolnik{' [' + field.name + ']' if field else ''}:** {text}\n")
            transcript.append(f"**Asystent** _(trasa: {meta.get('route')}; wywołania LLM: {len(calls)}; "
                              f"tokeny in/out: {sum(c['prompt_tokens'] for c in calls)}/"
                              f"{sum(c['completion_tokens'] for c in calls)})_:\n\n{last.text}\n")
            if cits:
                transcript.append("\n".join(f"- {c}" for c in cits) + "\n")
            save()
        save()
        if conv is not None:
            w(f"Zapis rozmowy: {log_path(conv)}")
