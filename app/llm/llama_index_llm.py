"""LlamaIndex CustomLLM adapter that delegates to our OllamaCloudLLM.

LlamaIndex's ``ReActAgent`` and ``FunctionAgent`` expect an LLM that
implements its ``LLM`` interface. We sit a thin adapter on top of our
existing ``OllamaCloudLLM`` / ``FakeLLM`` so the rotator, retries, and
metrics keep working unchanged.

We use ``CustomLLM`` (not ``FunctionCallingLLM``) so any text-producing
backend — including the deterministic FakeLLM in tests — is compatible.
``ReActAgent`` then drives tool-calling via prompt-based reasoning.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from llama_index.core.bridge.pydantic import Field
from llama_index.core.llms import (
    CompletionResponse,
    CompletionResponseAsyncGen,
    CompletionResponseGen,
    CustomLLM,
    LLMMetadata,
)
from llama_index.core.llms.callbacks import llm_completion_callback

from app.llm.client import LLMClient, get_llm


class OllamaCloudLlamaIndexLLM(CustomLLM):
    """Wraps the CPA LLMClient so LlamaIndex agents can use it."""

    context_window: int = Field(default=8192)
    num_output: int = Field(default=1024)
    model_name: str = Field(default="cpa-ollama")

    # Internal — the real client (FakeLLM in tests, OllamaCloudLLM in prod).
    _client: LLMClient | None = None

    class Config:  # pragma: no cover — pydantic config
        arbitrary_types_allowed = True

    def __init__(self, client: LLMClient | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = client or get_llm()

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=self.context_window,
            num_output=self.num_output,
            model_name=self.model_name,
            is_chat_model=False,
            is_function_calling_model=False,
        )

    # ──────────────── sync (required by CustomLLM) ────────────────

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        async def _run() -> str:
            assert self._client is not None
            resp = await self._client.complete(prompt)
            return resp.text

        # ReActAgent calls aiter; this sync path is rarely hit but supported.
        return CompletionResponse(text=asyncio.run(_run()))

    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        async def _agen() -> AsyncGenerator[str, None]:
            assert self._client is not None
            async for piece in self._client.stream(prompt):
                yield piece

        async def _collect() -> list[str]:
            return [p async for p in _agen()]

        pieces = asyncio.run(_collect())
        text = ""
        for p in pieces:
            text += p
            yield CompletionResponse(text=text, delta=p)

    # ──────────────── async ────────────────

    @llm_completion_callback()
    async def acomplete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        assert self._client is not None
        resp = await self._client.complete(prompt)
        return CompletionResponse(text=resp.text)

    @llm_completion_callback()
    async def astream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseAsyncGen:
        async def _gen() -> AsyncGenerator[CompletionResponse, None]:
            assert self._client is not None
            text = ""
            async for piece in self._client.stream(prompt):
                text += piece
                yield CompletionResponse(text=text, delta=piece)

        return _gen()
