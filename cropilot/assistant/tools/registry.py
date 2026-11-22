"""
One definition of every assistant tool. The orchestrator calls them in the Django process
(`call(...)`); the MCP server exposes the same functions (`assistant/mcp_server.py`).

    from assistant.tools.registry import call
    call("get_field_risks", field_id=3)
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

log = logging.getLogger("assistant.tools")

MAX_RESULT_CHARS = 16_000  # hard cap on a serialized tool result (LLM context budget)


class ToolError(Exception):
    """A tool failed in a way the user/model should be told about (message in Polish)."""


@dataclass
class Tool:
    name: str
    description: str                          # Polish, for the model: when to use, what it returns, example
    input_model: type[BaseModel]
    fn: Callable[..., Any]
    output_model: type[BaseModel] | None = None
    writes: bool = False                      # writing tools: only after the user confirmed
    agent_visible: bool = True                # offered to the LLM in agent mode
    enabled: Callable[[], bool] = lambda: True

    def input_schema(self) -> dict:
        return self.input_model.model_json_schema()


REGISTRY: dict[str, Tool] = {}


def register(name: str, description: str, input_model: type[BaseModel], *, output_model=None,
             writes: bool = False, agent_visible: bool = True, enabled: Callable[[], bool] | None = None):
    """Decorator: register `fn(**validated_input)` as a tool."""
    def deco(fn):
        REGISTRY[name] = Tool(name=name, description=description.strip(), input_model=input_model, fn=fn,
                              output_model=output_model, writes=writes, agent_visible=agent_visible,
                              enabled=enabled or (lambda: True))
        return fn
    return deco


def load_all() -> dict[str, Tool]:
    """Import the tool modules (registration happens on import)."""
    from . import charts, guides, observations, platform, sql  # noqa: F401
    return REGISTRY


def available(names: list[str] | None = None) -> list[Tool]:
    load_all()
    tools = [t for t in REGISTRY.values() if t.enabled()]
    return [t for t in tools if names is None or t.name in names]


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    return obj


def _cap(result: Any) -> Any:
    """Keep results under MAX_RESULT_CHARS: trim the longest lists, then mark as truncated."""
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS or not isinstance(result, dict):
        return result
    result = dict(result)
    for key, val in sorted(result.items(), key=lambda kv: -len(json.dumps(kv[1], ensure_ascii=False, default=str))):
        if isinstance(val, list) and len(val) > 1:
            while len(val) > 1 and len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_RESULT_CHARS:
                val = val[: max(1, len(val) * 2 // 3)]
                result[key] = val
        if len(json.dumps(result, ensure_ascii=False, default=str)) <= MAX_RESULT_CHARS:
            break
    result["truncated"] = True
    return result


def call(name: str, **kwargs) -> Any:
    """Validate input, run the tool, return a JSON-serializable, size-capped result.

    Raises ToolError (Polish message) for unknown tools, invalid input or tool failures."""
    load_all()
    tool = REGISTRY.get(name)
    if tool is None or not tool.enabled():
        raise ToolError(f"Narzędzie „{name}” nie istnieje albo jest wyłączone.")
    try:
        inp = tool.input_model(**kwargs)
    except ValidationError as e:
        raise ToolError(f"Niepoprawne parametry narzędzia „{name}”: {e.errors(include_url=False)}") from None
    t0 = time.perf_counter()
    try:
        result = tool.fn(**inp.model_dump())
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001 - every failure becomes a ToolError for the caller
        log.exception("tool %s failed", name)
        raise ToolError(f"Narzędzie „{name}” nie zadziałało: {type(e).__name__}: {e}") from e
    finally:
        log.info("tool %s took %.0f ms", name, (time.perf_counter() - t0) * 1000)
    return _cap(to_jsonable(result))


def to_openai_tools(names: list[str] | None = None, agent_only: bool = True) -> list[dict]:
    """OpenAI 'tools' schemas (function calling) for the given tool names."""
    return [
        {"type": "function",
         "function": {"name": t.name, "description": t.description, "parameters": t.input_schema()}}
        for t in available(names) if (t.agent_visible or not agent_only)
    ]
