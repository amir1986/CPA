"""LIVE integration test — hits REAL Ollama Cloud with REAL keys.

This is the real (not FakeLLM) test. It is OPT-IN and skipped unless
``OLLAMA_API_KEYS`` (or ``OLLAMA_API_KEYS_FILE``) is set, so it never runs in
the FakeLLM unit suite / CI without keys. It NEVER hardcodes keys — security
rule: API keys must not live in the repo. Provide them via the environment:

    OLLAMA_API_KEYS="key1
    key2" .venv/bin/python -m pytest tests/integration/test_llm_live.py -v

What it proves: the account is actually entitled to BOTH hardcoded models
(``qwen3-vl:235b-cloud`` default + ``gpt-oss:120b-cloud`` RAG). A 403 here is
the entitlement wall that otherwise surfaces as the misleading "All Ollama
Cloud API keys are exhausted." — so this test turns that into a clear,
actionable failure naming the un-entitled model.
"""

from __future__ import annotations

import os

import pytest

from app.config import OLLAMA_MODEL, OLLAMA_RAG_MODEL, get_settings
from app.llm.client import OllamaCloudLLM

# Skip the whole module unless real keys are present in the environment.
pytestmark = pytest.mark.skipif(
    not (os.environ.get("OLLAMA_API_KEYS") or os.environ.get("OLLAMA_API_KEYS_FILE")),
    reason="live LLM test: set OLLAMA_API_KEYS (or OLLAMA_API_KEYS_FILE) to run",
)


@pytest.fixture(autouse=True)
def _fresh_settings():
    # The keys are read through the lru_cached get_settings(); clear it so the
    # env-provided keys are picked up regardless of prior cached state.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        pytest.param(OLLAMA_MODEL, id="default-qwen3-vl"),
        pytest.param(OLLAMA_RAG_MODEL, id="rag-gpt-oss"),
    ],
)
async def test_model_is_entitled_and_responds(model: str) -> None:
    """Real round-trip: each hardcoded model must return a non-empty answer.

    A fresh client (fresh rotator) per model so a 403 on one can't disable
    the keys for the other. If the account isn't entitled to ``model`` this
    raises (403 -> AllKeysExhausted) instead of returning text — failing the
    test loudly and naming exactly which model is the problem.
    """
    client = OllamaCloudLLM(model=model)
    resp = await client.complete(
        "Reply with exactly the word: ok",
        system="You are a terse assistant. Answer in one word.",
    )
    assert resp.text.strip(), f"empty completion from entitled-but-mute model {model}"
