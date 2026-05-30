"""Regression guard: the two Ollama models are HARDCODED (not env-driven).

The AI surface uses two models, both pinned as constants in `app/config.py`:
- ``OLLAMA_MODEL = "qwen3-vl:235b-cloud"`` — comparison, file processing,
  Hebrew translation, agent (served by `get_llm()`).
- ``OLLAMA_RAG_MODEL = "gpt-oss:120b-cloud"`` — RAG retrieval-answering only
  (served by `get_rag_llm()`).

They are exposed as read-only `Settings` properties, so a stray `OLLAMA_MODEL`
env var can NOT override them (that override once caused a prod outage — see
CLAUDE.md §9). These tests lock the values, the per-feature client pinning,
and the env-independence. Entitlement (a real 200 vs 403 from Ollama Cloud)
is covered by the opt-in live test in ``tests/integration/test_llm_live.py``.
"""

from __future__ import annotations

from app.config import OLLAMA_MODEL, OLLAMA_RAG_MODEL, Settings, get_settings
from app.llm.client import OllamaCloudLLM, _chat_payload
from app.llm.ollama_rotator import KeyRotator

EXPECTED_DEFAULT = "qwen3-vl:235b-cloud"
EXPECTED_RAG = "gpt-oss:120b-cloud"


def test_hardcoded_constants() -> None:
    assert OLLAMA_MODEL == EXPECTED_DEFAULT
    assert OLLAMA_RAG_MODEL == EXPECTED_RAG


def test_settings_properties_return_constants() -> None:
    settings = get_settings()
    assert settings.ollama_model == OLLAMA_MODEL
    assert settings.ollama_rag_model == OLLAMA_RAG_MODEL


def test_models_are_not_env_overridable(monkeypatch) -> None:
    # Even with the env vars set, the properties return the hardcoded
    # constants — proving the models are not read from the environment.
    monkeypatch.setenv("OLLAMA_MODEL", "evil:override")
    monkeypatch.setenv("OLLAMA_RAG_MODEL", "evil:override")
    settings = Settings()
    assert settings.ollama_model == OLLAMA_MODEL
    assert settings.ollama_rag_model == OLLAMA_RAG_MODEL


def test_default_client_uses_default_model() -> None:
    # Explicit rotator so no real API keys are required.
    client = OllamaCloudLLM(rotator=KeyRotator(["test-key"]))
    assert client._model == OLLAMA_MODEL
    assert _chat_payload(client._model, "hi", system=None, stream=False)["model"] == OLLAMA_MODEL


def test_rag_client_uses_rag_model() -> None:
    # The per-feature `model=` override is how get_rag_llm() pins the RAG tag.
    client = OllamaCloudLLM(rotator=KeyRotator(["test-key"]), model=OLLAMA_RAG_MODEL)
    assert client._model == OLLAMA_RAG_MODEL
    assert _chat_payload(client._model, "hi", system=None, stream=False)["model"] == OLLAMA_RAG_MODEL
