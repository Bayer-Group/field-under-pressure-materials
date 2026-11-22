"""
LLM adapter: one OpenAI-compatible client for Gemini, Groq and OpenAI, fallback between providers,
usage logging, and a FakeLLM for tests (tests never call a real API).

Config (.env, "Assistant" section): LLM_PROVIDERS=gemini,groq, {P}_BASE_URL, {P}_API_KEY, {P}_MODEL,
LLM_MAX_TOKENS_OUT, LLM_INPUT_BUDGET.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ValidationError

log = logging.getLogger("assistant.llm")

REPO_DIR = Path(__file__).resolve().parents[2]
USAGE_LOG = Path(os.getenv("ASSISTANT_LOG_DIR", REPO_DIR / "logs")) / "llm_usage.jsonl"
CHARS_PER_TOKEN = 3.0  # conservative estimate for Polish text with LLM tokenizers


def max_tokens_out() -> int:
    return int(os.getenv("LLM_MAX_TOKENS_OUT", "1500"))


def input_budget() -> int:
    return int(os.getenv("LLM_INPUT_BUDGET", "5000"))


def estimate_tokens(text_or_messages) -> int:
    if isinstance(text_or_messages, list):
        text = "\n".join(str(m.get("content") or "") for m in text_or_messages)
        return int(len(text) / CHARS_PER_TOKEN) + 4 * len(text_or_messages)
    return int(len(str(text_or_messages)) / CHARS_PER_TOKEN)


class LLMError(Exception):
    """No answer from any provider (message in Polish, safe to show)."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    usage: dict
    duration_ms: int
    tool_calls: list | None = None
    message: Any = None  # raw assistant message (agent mode)
    truncated: bool = False  # the output limit cut the answer (finish_reason == "length")
    fallback_errors: list = field(default_factory=list)  # providers that failed before this one answered


class LLM(Protocol):
    def complete(self, messages: list[dict], json_mode: bool = False, **opts) -> LLMResult: ...


# ----------------------------------------------------------------------------- usage log
def log_usage(result: LLMResult, kind: str = "", extra: dict | None = None) -> dict:
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "provider": result.provider,
           "model": result.model, "kind": kind, "duration_ms": result.duration_ms, **result.usage, **(extra or {})}
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(USAGE_LOG, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:  # logging must never break an answer
        log.warning("cannot write %s: %s", USAGE_LOG, e)
    return rec


def _usage(resp_usage, messages, text: str) -> dict:
    if resp_usage is not None and getattr(resp_usage, "prompt_tokens", None) is not None:
        return {"prompt_tokens": resp_usage.prompt_tokens, "completion_tokens": resp_usage.completion_tokens or 0,
                "total_tokens": resp_usage.total_tokens or 0, "estimated": False}
    p, c = estimate_tokens(messages), estimate_tokens(text)
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c, "estimated": True}


# ----------------------------------------------------------------------------- JSON helpers
JSON_INSTRUCTION = "\n\nOdpowiedz WYŁĄCZNIE jednym obiektem JSON, bez komentarzy i bez bloku ```."


def extract_json(text: str) -> dict:
    """First balanced {...} object in text (handles ``` fences and prose around it)."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object in the model output")


def complete_json(llm: LLM, messages: list[dict], model_cls: type[BaseModel], **opts) -> tuple[BaseModel, LLMResult]:
    """json_mode call + extraction + Pydantic validation (raises LLMError on invalid output)."""
    res = llm.complete(messages, json_mode=True, **opts)
    try:
        return model_cls.model_validate(extract_json(res.text)), res
    except (ValueError, ValidationError) as e:
        raise LLMError(f"Model zwrócił niepoprawny JSON: {e}") from None


# ----------------------------------------------------------------------------- real providers
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenAICompatLLM:
    """One OpenAI-compatible endpoint (Gemini's /v1beta/openai/, Groq's /openai/v1, OpenAI's /v1)."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str, timeout: float | None = None):
        from openai import OpenAI
        timeout = timeout or float(os.getenv("LLM_TIMEOUT_S", "25"))  # a farmer waits; the next provider is faster
        self.name, self.model = name, model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self._json_mode_supported = True
        # newer OpenAI models (gpt-5 and later) reject max_tokens and any temperature but the default:
        # learned from the first 400 and kept for this provider
        self._token_param = "max_tokens"
        self._send_temperature = True
        # reasoning models (gpt-oss, Gemini 3.x) spend output tokens on thinking first; keep it short
        self._reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "low") or None

    def complete(self, messages: list[dict], json_mode: bool = False, max_tokens: int | None = None,
                 temperature: float = 0.2, tools: list | None = None, **_) -> LLMResult:
        import openai
        max_tokens = max_tokens or max_tokens_out()
        kwargs: dict = {"model": self.model, "messages": messages, self._token_param: max_tokens}
        if self._send_temperature:
            kwargs["temperature"] = temperature
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        if tools:
            kwargs["tools"] = tools
        msgs = messages
        if json_mode:
            if self._json_mode_supported:
                kwargs["response_format"] = {"type": "json_object"}
            else:
                msgs = _with_json_instruction(messages)
                kwargs["messages"] = msgs
        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except openai.BadRequestError as e:
            # checked first: in JSON mode the fallback below would otherwise blame response_format for these
            err, param = str(e), getattr(e, "param", None)
            if self._token_param == "max_tokens" and (param == "max_tokens" or "max_completion_tokens" in err):
                log.info("%s wants max_completion_tokens instead of max_tokens; switching", self.name)
                self._token_param = "max_completion_tokens"
                return self.complete(messages, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature, tools=tools)
            if "temperature" in kwargs and (param == "temperature" or "temperature" in err.lower()):
                log.info("%s accepts only the default temperature (%s); sending without it", self.name, e)
                self._send_temperature = False
                return self.complete(messages, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature, tools=tools)
            if "reasoning_effort" in kwargs and "reason" in str(e).lower():  # not a reasoning model / not supported
                log.info("%s rejected reasoning_effort (%s); sending without it", self.name, e)
                self._reasoning_effort = None
                return self.complete(messages, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature, tools=tools)
            if json_mode and "response_format" in kwargs:  # provider rejected JSON mode: instruct instead
                log.info("%s rejected response_format (%s); falling back to instruction", self.name, e)
                self._json_mode_supported = False
                return self.complete(messages, json_mode=True, max_tokens=max_tokens, temperature=temperature, tools=tools)
            raise
        msg = resp.choices[0].message
        text = msg.content or ""
        if not text.strip() and not getattr(msg, "tool_calls", None) and max_tokens < 3000 \
                and resp.choices[0].finish_reason == "length":
            # the whole output budget went to reasoning: one retry with a larger budget (still < 6k per call)
            retry = min(3000, max(1400, 2 * max_tokens))
            log.warning("%s returned no text (output limit reached while reasoning); retrying with %s", self.name, retry)
            return self.complete(messages, json_mode=json_mode, max_tokens=retry, temperature=temperature, tools=tools)
        return LLMResult(text=text, provider=self.name, model=self.model, usage=_usage(resp.usage, msgs, text),
                         duration_ms=int((time.perf_counter() - t0) * 1000),
                         tool_calls=getattr(msg, "tool_calls", None), message=msg,
                         truncated=resp.choices[0].finish_reason == "length")


def _with_json_instruction(messages: list[dict]) -> list[dict]:
    out = [dict(m) for m in messages]
    for m in reversed(out):
        if m["role"] == "user":
            m["content"] = (m["content"] or "") + JSON_INSTRUCTION
            break
    return out


def _retry_after(e) -> float:
    try:
        v = e.response.headers.get("retry-after")
        return min(float(v), 20.0) if v else 2.0
    except Exception:  # noqa: BLE001
        return 2.0


MAX_WAIT_BEFORE_NEXT_S = 3.0  # a longer Retry-After goes to the next provider instead of waiting


class FallbackLLM:
    """Try providers in order: retryable error -> one retry after waiting -> next provider."""

    def __init__(self, providers: list[OpenAICompatLLM], sleep: Callable[[float], None] = time.sleep):
        if not providers:
            raise LLMError("Brak skonfigurowanego dostawcy LLM (ustaw klucze w .env: GEMINI_API_KEY / GROQ_API_KEY).")
        self.providers, self.sleep = providers, sleep

    @property
    def name(self) -> str:
        return ",".join(p.name for p in self.providers)

    def complete(self, messages: list[dict], json_mode: bool = False, **opts) -> LLMResult:
        import openai
        errors = []
        for i, p in enumerate(self.providers):
            has_next = i + 1 < len(self.providers)
            for attempt in (1, 2):
                try:
                    res = p.complete(messages, json_mode=json_mode, **opts)
                    res.fallback_errors = list(errors)  # what failed before this answer (kept in the message's meta)
                    return res
                except (openai.APITimeoutError, openai.APIConnectionError) as e:
                    errors.append(f"{p.name}: {type(e).__name__}")
                    wait = 2.0
                except openai.APIStatusError as e:
                    errors.append(f"{p.name}: HTTP {e.status_code}")
                    if e.status_code not in RETRYABLE_STATUS:
                        break  # e.g. 401/400: next provider, no retry
                    wait = _retry_after(e)
                if attempt == 1:
                    if has_next and wait > MAX_WAIT_BEFORE_NEXT_S:  # rate-limited for a while: the next provider now
                        log.warning("LLM %s failed (%s, retry in %.0fs); trying the next provider", p.name, errors[-1], wait)
                        break
                    log.warning("LLM %s failed (%s); retrying in %.1fs", p.name, errors[-1], wait)
                    self.sleep(wait)
            log.warning("LLM %s gave up, trying next provider", p.name)
        raise LLMError("Model językowy jest chwilowo niedostępny (" + "; ".join(errors) + ").")


# ----------------------------------------------------------------------------- fake (tests)
@dataclass
class FakeLLM:
    """Scripted answers. `responses`: list of strings (consumed in order, last one repeats) or a
    callable(messages, json_mode) -> str. Records every call in `calls`."""

    responses: Any = "To jest odpowiedź testowa."
    name: str = "fake"
    model: str = "fake-1"
    calls: list = field(default_factory=list)

    def complete(self, messages: list[dict], json_mode: bool = False, **opts) -> LLMResult:
        self.calls.append({"messages": messages, "json_mode": json_mode, **opts})
        if callable(self.responses):
            text = self.responses(messages, json_mode)
        elif isinstance(self.responses, list):
            text = self.responses[min(len(self.calls), len(self.responses)) - 1]
        else:
            text = self.responses
        return LLMResult(text=text, provider=self.name, model=self.model, usage=_usage(None, messages, text),
                         duration_ms=0)


# ----------------------------------------------------------------------------- factory
DEFAULT_BASE_URL = {"gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "groq": "https://api.groq.com/openai/v1",
                    "openai": "https://api.openai.com/v1"}
DEFAULT_MODEL = {"groq": "openai/gpt-oss-120b"}  # Gemini/OpenAI model names change: pick one with `manage.py llm_models`


def provider_configs() -> list[dict]:
    from assistant.rag import config  # noqa: F401 - loads the repo .env
    out = []
    for name in [p.strip().lower() for p in (os.getenv("LLM_PROVIDERS") or "gemini,groq").split(",") if p.strip()]:
        up = name.upper()
        cfg = {"name": name, "base_url": os.getenv(f"{up}_BASE_URL") or DEFAULT_BASE_URL.get(name, ""),
               "api_key": os.getenv(f"{up}_API_KEY", ""), "model": os.getenv(f"{up}_MODEL") or DEFAULT_MODEL.get(name, "")}
        cfg["configured"] = bool(cfg["base_url"] and cfg["api_key"])
        out.append(cfg)
    return out


def get_llm(sleep: Callable[[float], None] = time.sleep) -> FallbackLLM:
    """Real LLM from .env (providers with a key and a model). Raises LLMError if none."""
    providers, problems = [], []
    for c in provider_configs():
        up = c["name"].upper()
        if c["configured"] and c["model"]:
            providers.append(OpenAICompatLLM(c["name"], c["base_url"], c["api_key"], c["model"]))
        elif c["configured"]:
            problems.append(f"{up}: jest klucz, brak {up}_MODEL (wybierz: python manage.py llm_models)")
            log.warning("LLM provider %s has a key but no %s_MODEL; skipped", c["name"], up)
        else:
            problems.append(f"{up}: brak {up}_API_KEY" + ("" if c["base_url"] else f" i {up}_BASE_URL"))
    if not providers:
        raise LLMError("Brak skonfigurowanego dostawcy LLM. " + "; ".join(problems) + ".")
    return FallbackLLM(providers, sleep=sleep)


def strip_think(text: str) -> str:
    """Remove <think>…</think> blocks some open models emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
