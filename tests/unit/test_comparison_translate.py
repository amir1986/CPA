"""Resilience tests for the Hebrew-memo translation step in the export
route. The bug we're guarding against: an unhandled exception inside
``_translate_to_hebrew`` (or anything it awaits) used to propagate out of
``asyncio.gather(return_exceptions=False)``, then out of the route, and
the user saw an opaque 500 instead of an English-fallback PDF.

We can't drive the FastAPI route directly without the DB and storage
stack, but the failure mode lives in two pure-async helpers that we can
exercise in isolation:

  - ``_translate_to_hebrew``: catches Exception internally and returns
    the original ``items`` dict on failure.
  - ``_translate_batches_parallel``: gathers per-batch translations with
    ``return_exceptions=True`` so one batch's failure doesn't sink the rest.
"""
from __future__ import annotations

import pytest

from app.api.routes import comparisons as routes
from app.llm.client import FakeLLM, reset_llm


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch: pytest.MonkeyPatch):
    """Force the LLM singleton to be a fake so no network calls happen."""
    reset_llm()
    monkeypatch.setenv("CPA_LLM_BACKEND", "fake")
    yield
    reset_llm()


async def test_translate_to_hebrew_returns_english_when_llm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the underlying LLM raises, ``_translate_to_hebrew`` swallows it
    and returns the original English items so the export can still
    proceed."""

    async def boom(_self, _prompt, *, system=None):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(FakeLLM, "complete", boom)

    items = {"a.current_summary": "Revenue is recognized when control transfers."}
    out = await routes._translate_to_hebrew(items)
    assert out == items


async def test_translate_to_hebrew_short_circuits_when_input_empty() -> None:
    assert await routes._translate_to_hebrew({}) == {}
    assert await routes._translate_to_hebrew({"k": ""}) == {"k": ""}
    assert await routes._translate_to_hebrew({"k": "   "}) == {"k": "   "}


async def test_translate_to_hebrew_uses_llm_output_when_json_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: fake LLM returns a valid JSON object with translated
    values, ``_translate_to_hebrew`` merges them onto the input dict."""

    async def fake_complete(_self, _prompt, *, system=None):
        from app.llm.client import LLMResponse

        return LLMResponse(
            text='{"a.current_summary":"ההכרה בהכנסה כאשר השליטה מועברת."}',
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )

    monkeypatch.setattr(FakeLLM, "complete", fake_complete)

    items = {"a.current_summary": "Revenue is recognized when control transfers."}
    out = await routes._translate_to_hebrew(items)
    assert out["a.current_summary"] == "ההכרה בהכנסה כאשר השליטה מועברת."


async def test_translate_batches_parallel_survives_one_bad_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If one batched coroutine raises, the others still complete and the
    failing batch's keys degrade to English — no 500 leaks out.

    The failure is keyed off the batch's content (not call order), so the
    test isn't sensitive to asyncio scheduling within the gather.
    """

    async def flaky(items):
        # The second batch starts at k8 — make that one explode.
        first_key = next(iter(items))
        if first_key.startswith("k8."):
            raise RuntimeError("second batch's LLM call exploded")
        return {k: f"HE:{v}" for k, v in items.items()}

    monkeypatch.setattr(routes, "_translate_to_hebrew", flaky)

    # 3 batches of 8/8/4: keys k0..k7, k8..k15, k16..k19.
    flat = {f"k{i}.current_summary": f"v{i}" for i in range(20)}
    out = await routes._translate_batches_parallel(flat, batch_size=8)

    # Every key is still in the output (defaults to the English value).
    assert set(out) == set(flat)
    # First and third batches translated.
    assert out["k0.current_summary"] == "HE:v0"
    assert out["k16.current_summary"] == "HE:v16"
    # Second batch (keys k8..k15) kept their English values — graceful degrade.
    assert out["k8.current_summary"] == "v8"
    assert out["k15.current_summary"] == "v15"


async def test_translate_batches_parallel_empty_input() -> None:
    assert await routes._translate_batches_parallel({}, batch_size=8) == {}
