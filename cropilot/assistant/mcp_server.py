"""
MCP server (stdio) exposing the assistant's tools — the same functions the orchestrator calls
(assistant/tools/registry.py). Run: `python manage.py mcp_server`.

Safety:
* record_observation requires `confirm: true`; without it the call is a dry run returning the draft
  (the model must show it to the user first);
* run_readonly_sql only when ASSISTANT_ENABLE_SQL=1 and a `readonly` database exists;
* nothing but the protocol on stdout: logs go to stderr (stdio_server also diverts fd 1 while serving).
"""
from __future__ import annotations

import json
import logging
import time

import anyio

from .tools.registry import ToolError, available, call, load_all

log = logging.getLogger("assistant.mcp")

SERVER_NAME = "field-under-pressure-assistant"
INSTRUCTIONS = (
    "Narzędzia asystenta agronomicznego Cropilot (pszenica, kukurydza). "
    "Dane pól, ryzyko z silnika decyzyjnego (powody ryzyka tylko z pola explanation), pogoda, "
    "metodyki IOR z cytatami (cytuj chunk_id). Nigdy nie podawaj nazw środków ochrony roślin ani dawek. "
    "„Dziś” = get_season_date. record_observation: najpierw wywołaj bez confirm, pokaż szkic użytkownikowi, "
    "a dopiero po jego zgodzie wywołaj z confirm=true."
)
CONFIRM_NOTE = (" Wywołanie bez confirm=true zwraca tylko podgląd (nic nie zapisuje). Pokaż szkic użytkownikowi "
                "i zapisz z confirm=true dopiero po jego wyraźnym potwierdzeniu.")


def tool_specs() -> list[dict]:
    """Name, description, input schema and hints for every enabled tool (shared with tests)."""
    specs = []
    for t in available():
        schema = json.loads(json.dumps(t.input_schema()))
        desc = t.description
        if t.writes:
            schema.setdefault("properties", {})["confirm"] = {
                "type": "boolean", "default": False,
                "description": "true = zapisz (dopiero po potwierdzeniu przez użytkownika); false = podgląd."}
            desc += CONFIRM_NOTE
        specs.append({"name": t.name, "description": desc, "input_schema": schema,
                      "read_only": not t.writes, "idempotent": True})
    return specs


def run_tool(name: str, arguments: dict | None, manage_connections: bool = True) -> tuple[dict, bool]:
    """Synchronous tool execution (in a worker thread). Returns (result, is_error)."""
    from django.db import close_old_connections

    args = dict(arguments or {})
    if manage_connections:
        close_old_connections()
    try:
        tool = load_all().get(name)
        if tool is not None and tool.writes and not args.pop("confirm", False):
            from .tools.observations import resolve_draft
            from .tools.registry import to_jsonable
            draft = resolve_draft(args.get("field_id"), args.get("date"), args.get("category"),
                                  args.get("threat"), args.get("severity"), args.get("note", ""))
            return {"dry_run": True, "draft": to_jsonable(draft),
                    "message": "Nic nie zapisano. Pokaż ten szkic użytkownikowi i po potwierdzeniu wywołaj "
                               "ponownie z confirm=true."}, False
        args.pop("confirm", None)
        return call(name, **args), False
    except ToolError as e:
        return {"error": str(e)}, True
    finally:
        if manage_connections:
            close_old_connections()


def warm_up() -> None:
    """Load the embedding model, BM25, Qdrant client and DB connection before serving."""
    t0 = time.perf_counter()
    try:
        from django.db import connection
        with connection.cursor() as c:
            c.execute("SELECT 1")
        log.info("database ok")
    except Exception as e:  # noqa: BLE001
        log.warning("database not reachable: %s", e)
    try:
        from .rag import bm25
        from .rag.chunker import ntok
        from .rag.embed import encode_query
        from .rag.search import _store
        encode_query("rozgrzewka")
        ntok("rozgrzewka")  # tokenizer used for the passage token budget
        bm25.load()
        _store()
        log.info("guide search ready")
    except Exception as e:  # noqa: BLE001 - guide tools will return a ToolError
        log.warning("guide search not ready (%s): %s", type(e).__name__, e)
    log.info("warm-up done in %.1fs; tools: %s", time.perf_counter() - t0, [t["name"] for t in tool_specs()])


def build_server():
    import mcp.types as types
    from mcp.server.lowlevel import Server

    async def on_list_tools(ctx, params):
        return types.ListToolsResult(tools=[
            types.Tool(name=s["name"], description=s["description"], input_schema=s["input_schema"],
                       annotations=types.ToolAnnotations(read_only_hint=s["read_only"],
                                                         destructive_hint=False, idempotent_hint=s["idempotent"]))
            for s in tool_specs()])

    async def on_call_tool(ctx, params):
        t0 = time.perf_counter()
        result, is_error = await anyio.to_thread.run_sync(run_tool, params.name, params.arguments)
        log.info("call %s -> %s in %.0f ms", params.name, "error" if is_error else "ok", (time.perf_counter() - t0) * 1000)
        text = json.dumps(result, ensure_ascii=False, default=str)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    structured_content=result if isinstance(result, dict) else None,
                                    is_error=is_error)

    return Server(SERVER_NAME, version="0.1.0", instructions=INSTRUCTIONS,
                  on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def serve() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(warm: bool = True) -> None:
    if warm:
        warm_up()
    anyio.run(serve)
