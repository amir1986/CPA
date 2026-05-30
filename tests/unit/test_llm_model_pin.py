"""Regression guard: the Ollama model is pinned to ``qwen3.5:397b-cloud``.

Every AI call — RAG (`query_engine`), the comparison orchestrator, the
agent loop and Hebrew translation — flows through the single
`OllamaCloudLLM` client, which reads `settings.ollama_model`. We pin that
default in code (and mirror it in every deploy config) so the model can't
silently change. NOTE: a pinned tag must be one the account is *entitled*
to — an un-entitled tag (e.g. `qwen3.5:cloud`) returns 403 and disables
every key (see CLAUDE.md §9). `gpt-oss:120b` is the known-good fallback.
If someone changes the default, this test fails loudly and points them at
the deploy configs that must change in lockstep.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.client import OllamaCloudLLM, _chat_payload
from app.llm.ollama_rotator import KeyRotator

PINNED_MODEL = "qwen3.5:397b-cloud"


def test_settings_default_model_is_pinned() -> None:
    # Assert the *hardcoded field default*, independent of any OLLAMA_MODEL
    # env var that might be set in the shell running the suite.
    assert Settings.model_fields["ollama_model"].default == PINNED_MODEL


def test_chat_payload_carries_the_model() -> None:
    payload = _chat_payload(PINNED_MODEL, "hi", system=None, stream=False)
    assert payload["model"] == PINNED_MODEL


def test_client_sends_the_configured_model() -> None:
    # Build with an explicit rotator so no real API keys are required, and
    # confirm the client forwards exactly what settings resolved — i.e. the
    # model the orchestrator/RAG/agent will actually put on the wire.
    client = OllamaCloudLLM(rotator=KeyRotator(["test-key"]))
    resolved = get_settings().ollama_model
    payload = _chat_payload(client._model, "hi", system=None, stream=False)
    assert client._model == resolved
    assert payload["model"] == resolved
