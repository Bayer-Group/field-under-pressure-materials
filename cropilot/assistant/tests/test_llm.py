"""LLM adapter tests — no network: providers are stubs raising real openai exceptions."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
import openai
from django.test import SimpleTestCase
from pydantic import BaseModel

from assistant.orchestrator import llm as L


def _status_error(cls, code: int, headers=None):
    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    resp = httpx.Response(code, request=req, headers=headers or {}, json={"error": {"message": "x"}})
    return cls(message=f"HTTP {code}", response=resp, body=None)


class StubProvider:
    def __init__(self, name, outcomes):
        self.name, self.model, self.outcomes, self.calls = name, f"{name}-m", list(outcomes), 0

    def complete(self, messages, json_mode=False, **opts):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return L.LLMResult(text=o, provider=self.name, model=self.model, usage={}, duration_ms=1)


class FallbackTests(SimpleTestCase):
    def test_retry_once_then_next_provider(self):
        a = StubProvider("gemini", [_status_error(openai.RateLimitError, 429, {"retry-after": "1"}),
                                    _status_error(openai.RateLimitError, 429)])
        b = StubProvider("groq", ["ok z groq"])
        waits = []
        r = L.FallbackLLM([a, b], sleep=waits.append).complete([{"role": "user", "content": "x"}])
        self.assertEqual((r.text, r.provider, a.calls, b.calls), ("ok z groq", "groq", 2, 1))
        self.assertEqual(waits, [1.0])

    def test_non_retryable_goes_straight_to_next(self):
        a = StubProvider("gemini", [_status_error(openai.AuthenticationError, 401)])
        b = StubProvider("groq", ["ok"])
        r = L.FallbackLLM([a, b], sleep=lambda s: None).complete([{"role": "user", "content": "x"}])
        self.assertEqual((r.provider, a.calls), ("groq", 1))

    def test_all_fail_raises_polish_error(self):
        a = StubProvider("gemini", [_status_error(openai.InternalServerError, 503)] * 2)
        with self.assertRaises(L.LLMError) as cm:
            L.FallbackLLM([a], sleep=lambda s: None).complete([{"role": "user", "content": "x"}])
        self.assertIn("niedostępny", str(cm.exception))

    def test_no_providers(self):
        with self.assertRaises(L.LLMError):
            L.FallbackLLM([])

    def test_get_llm_without_keys_raises(self):
        # pinned, so a developer's .env (e.g. LLM_PROVIDERS=openai,groq with a key) cannot configure one
        with mock.patch.dict("os.environ", {"LLM_PROVIDERS": "gemini,groq,openai", "GEMINI_API_KEY": "",
                                            "GROQ_API_KEY": "", "OPENAI_API_KEY": ""}):
            with self.assertRaises(L.LLMError):
                L.get_llm()


class JsonTests(SimpleTestCase):
    class Out(BaseModel):
        category: str
        missing: list[str] = []

    def test_extract_json_from_fences_and_prose(self):
        self.assertEqual(L.extract_json('Oto: ```json\n{"a": {"b": "}"}}\n``` koniec'), {"a": {"b": "}"}})
        with self.assertRaises(ValueError):
            L.extract_json("brak json")

    def test_complete_json_validates(self):
        out, res = L.complete_json(L.FakeLLM('{"category": "choroba"}'), [{"role": "user", "content": "x"}], self.Out)
        self.assertEqual(out.category, "choroba")
        with self.assertRaises(L.LLMError):
            L.complete_json(L.FakeLLM('{"nope": 1}'), [{"role": "user", "content": "x"}], self.Out)


class UsageTests(SimpleTestCase):
    def test_fake_usage_is_estimated_and_logged(self):
        fake = L.FakeLLM(["pierwsza", "druga"])
        r1 = fake.complete([{"role": "user", "content": "a" * 300}])
        r2 = fake.complete([{"role": "user", "content": "b"}])
        self.assertEqual((r1.text, r2.text), ("pierwsza", "druga"))
        self.assertTrue(r1.usage["estimated"])
        self.assertEqual(r1.usage["prompt_tokens"], 300 // 3 + 4)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(L, "USAGE_LOG", Path(d) / "u.jsonl"):
            L.log_usage(r1, kind="pytanie_ogolne")
            rec = json.loads((Path(d) / "u.jsonl").read_text().strip())
        self.assertEqual((rec["kind"], rec["provider"], rec["estimated"]), ("pytanie_ogolne", "fake", True))


# OpenAI's 400s for newer models (gpt-5 and later), as the API returns them
MAX_TOKENS_ERR = ("Unsupported parameter: 'max_tokens' is not supported with this model. "
                  "Use 'max_completion_tokens' instead.", "max_tokens")
TEMPERATURE_ERR = ("Unsupported value: 'temperature' does not support 0.2 with this model. "
                   "Only the default (1) value is supported.", "temperature")


def _bad_request(message: str, param: str | None):
    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    resp = httpx.Response(400, request=req, json={"error": {"message": message, "param": param}})
    return openai.BadRequestError(message=f"Error code: 400 - {message}", response=resp,
                                  body={"message": message, "param": param})


def _ok(text: str):
    msg = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)


class OpenAICompatParamTests(SimpleTestCase):
    """Request parameters a provider rejects are learned once and dropped or renamed."""

    def _llm(self, outcomes):
        llm = L.OpenAICompatLLM("openai", "https://example.test/v1", "test-key", "m")
        llm.client = mock.Mock()
        llm.client.chat.completions.create.side_effect = outcomes
        return llm

    def _sent(self, llm):
        return [c.kwargs for c in llm.client.chat.completions.create.call_args_list]

    def test_older_models_get_max_tokens_and_temperature(self):
        llm = self._llm([_ok("ok")])
        llm.complete([{"role": "user", "content": "x"}], max_tokens=100)
        sent = self._sent(llm)[0]
        self.assertEqual((sent["max_tokens"], sent["temperature"]), (100, 0.2))
        self.assertNotIn("max_completion_tokens", sent)

    def test_switches_to_max_completion_tokens_and_remembers(self):
        llm = self._llm([_bad_request(*MAX_TOKENS_ERR), _ok("pierwsza"), _ok("druga")])
        r1 = llm.complete([{"role": "user", "content": "x"}], max_tokens=100)
        r2 = llm.complete([{"role": "user", "content": "y"}], max_tokens=100)
        self.assertEqual((r1.text, r2.text), ("pierwsza", "druga"))
        first, retry, later = self._sent(llm)
        self.assertEqual(first["max_tokens"], 100)
        for sent in (retry, later):  # one failed request per provider, not per question
            self.assertEqual(sent["max_completion_tokens"], 100)
            self.assertNotIn("max_tokens", sent)

    def test_drops_temperature_and_keeps_json_mode(self):
        llm = self._llm([_bad_request(*MAX_TOKENS_ERR), _bad_request(*TEMPERATURE_ERR), _ok('{"ok": true}')])
        r = llm.complete([{"role": "user", "content": "x"}], json_mode=True, max_tokens=100)
        self.assertEqual(r.text, '{"ok": true}')
        final = self._sent(llm)[-1]
        self.assertNotIn("temperature", final)
        self.assertEqual(final["max_completion_tokens"], 100)
        self.assertEqual(final["response_format"], {"type": "json_object"})  # JSON mode not blamed
        self.assertTrue(llm._json_mode_supported)

    def test_other_bad_requests_still_raise(self):
        llm = self._llm([_bad_request("The model `m` does not exist.", "model")])
        with self.assertRaises(openai.BadRequestError):
            llm.complete([{"role": "user", "content": "x"}])
        self.assertEqual(len(self._sent(llm)), 1)
