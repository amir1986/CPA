"""Async Ollama Cloud client + a deterministic fake for tests.

The production client honors the ``KeyRotator`` state machine: on 429 it
advances to the next key, on 5xx it retries the same key with jittered
backoff, on 401/403 it permanently disables the key, on streaming mid-stream
it does NOT transparently fail over.

For unit/integration tests we use ``FakeLLM`` which returns a fixed JSON
payload — that's what powers the ``/query`` and ``/agent`` end-to-end tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

import httpx

from app.config import get_settings
from app.llm.ollama_rotator import AllKeysExhausted, KeyRotator

logger = logging.getLogger(__name__)


def _llm_metric(outcome: str, *, cooldown: bool = False) -> None:
    """Increment Prometheus counters. Defensive — telemetry is optional in tests."""
    try:
        from app.telemetry import LLM_KEY_COOLDOWNS, LLM_REQUESTS

        LLM_REQUESTS.labels(outcome=outcome).inc()
        if cooldown:
            LLM_KEY_COOLDOWNS.inc()
    except Exception:
        pass


@dataclass
class LLMResponse:
    text: str
    usage: dict[str, int]


class LLMClient(Protocol):
    async def complete(self, prompt: str, *, system: str | None = ...) -> LLMResponse: ...

    async def stream(self, prompt: str, *, system: str | None = ...) -> AsyncIterator[str]: ...


# ──────────────── Fake (tests) ────────────────


class FakeLLM:
    """Returns the canned response set via :func:`set_fake_response`."""

    def __init__(self) -> None:
        self._response: str = json.dumps({"answer": "", "citations": []})
        self.calls: list[str] = []

    def set_response(self, text: str) -> None:
        self._response = text

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        self.calls.append(prompt)
        return LLMResponse(text=self._response, usage={"prompt_tokens": 0, "completion_tokens": 0})

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        self.calls.append(prompt)
        # Yield in chunks so the SSE pipeline is exercised.
        for piece in self._chunk(self._response, 16):
            yield piece
            await asyncio.sleep(0)

    @staticmethod
    def _chunk(s: str, n: int) -> list[str]:
        return [s[i : i + n] for i in range(0, len(s), n)] or [s]


# ──────────────── Real client ────────────────


class OllamaCloudLLM:
    def __init__(self, rotator: KeyRotator | None = None) -> None:
        settings = get_settings()
        keys = settings.resolved_api_keys()
        if rotator is None:
            if not keys:
                raise RuntimeError("OLLAMA_API_KEYS is empty — cannot create OllamaCloudLLM")
            rotator = KeyRotator(keys, cooldown_seconds=settings.ollama_rate_limit_cooldown_seconds)
        self._rotator = rotator
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model
        self._timeout = settings.ollama_request_timeout_seconds
        self._max_retries = settings.ollama_max_retries_per_key

    @property
    def rotator(self) -> KeyRotator:
        return self._rotator

    async def _request(self, *, payload: dict, stream: bool) -> httpx.Response:
        """One non-streaming HTTP call with retry/rotation logic."""
        attempts_total = 0
        max_attempts = len(self._rotator) * (self._max_retries + 1)
        while attempts_total < max_attempts:
            state = self._rotator.acquire()  # may raise AllKeysExhausted
            attempts_total += 1
            headers = {
                "Authorization": f"Bearer {state.key}",
                "Content-Type": "application/json",
            }
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/api/chat",
                        json=payload,
                        headers=headers,
                    )
                if resp.status_code == 429:
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    self._rotator.report_rate_limited(state.key, retry_after_seconds=retry_after)
                    _llm_metric("rate_limited", cooldown=True)
                    continue
                if resp.status_code in (401, 403):
                    self._rotator.report_unauthorized(state.key, reason=f"http_{resp.status_code}")
                    _llm_metric("unauthorized")
                    continue
                if resp.status_code >= 500:
                    self._rotator.report_server_error(state.key, reason=f"http_{resp.status_code}")
                    _llm_metric("server_error")
                    await asyncio.sleep(0.5 + random.random())
                    continue
                resp.raise_for_status()
                self._rotator.report_success(state.key)
                _llm_metric("success")
                return resp
            except httpx.RequestError as exc:
                self._rotator.report_server_error(state.key, reason=type(exc).__name__)
                _llm_metric("server_error")
                await asyncio.sleep(0.5 + random.random())
                continue
        _llm_metric("exhausted")
        raise AllKeysExhausted(None)

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        payload = _chat_payload(self._model, prompt, system=system, stream=False)
        resp = await self._request(payload=payload, stream=False)
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }
        return LLMResponse(text=text, usage=usage)

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        # Per the plan, streaming does NOT fail over mid-stream.
        payload = _chat_payload(self._model, prompt, system=system, stream=True)
        state = self._rotator.acquire()
        headers = {"Authorization": f"Bearer {state.key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", f"{self._base_url}/api/chat", json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    if resp.status_code == 429:
                        self._rotator.report_rate_limited(state.key)
                    elif resp.status_code in (401, 403):
                        self._rotator.report_unauthorized(state.key)
                    else:
                        self._rotator.report_server_error(state.key)
                    resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = evt.get("message", {}).get("content")
                    if delta:
                        yield delta
        self._rotator.report_success(state.key)


def _chat_payload(model: str, prompt: str, *, system: str | None, stream: bool) -> dict:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return {"model": model, "messages": messages, "stream": stream}


def _parse_retry_after(header: str | None) -> float | None:
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None


# ──────────────── factory ────────────────


_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    global _singleton
    if _singleton is None:
        backend = os.environ.get("CPA_LLM_BACKEND", "ollama").lower()
        if backend == "fake":
            _singleton = FakeLLM()
        else:
            _singleton = OllamaCloudLLM()
    return _singleton


def reset_llm() -> None:
    global _singleton
    _singleton = None
