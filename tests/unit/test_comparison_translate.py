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
from app.services import comparison_translation as translation_svc


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

    async def flaky(items, *, per_batch_timeout=18.0):
        # The second batch starts at k8 — make that one explode.
        first_key = next(iter(items))
        if first_key.startswith("k8."):
            raise RuntimeError("second batch's LLM call exploded")
        return {k: f"HE:{v}" for k, v in items.items()}

    # The implementation now lives in app.services.comparison_translation
    # and `_translate_batches_parallel` calls it via the module-local
    # name, so we patch the call site (not the re-export on `routes`).
    monkeypatch.setattr(translation_svc, "_translate_to_hebrew", flaky)

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


async def test_translate_batches_parallel_swallows_base_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BaseException-derived panic from inside translation must not leak
    out as a bare 500 — it has to land in the outer route's catch and
    degrade to English. Reproduces the failure mode where cryptography's
    Rust bindings panic during the LLM client's TLS handshake.
    """

    class FakePanic(BaseException):
        pass

    async def panicking(items, *, per_batch_timeout=18.0):
        raise FakePanic("simulated rust panic during translation")

    monkeypatch.setattr(translation_svc, "_translate_to_hebrew", panicking)

    flat = {"k.current_summary": "en source"}
    # The export route wraps this call in a `try / except BaseException`
    # that degrades to English. Here we just confirm the panic isn't
    # silently turned into a successful Hebrew translation; the panic
    # SHOULD propagate out of _translate_batches_parallel so the route's
    # outer catch sees it (asyncio.gather is configured with
    # return_exceptions=True but that only catches Exception, not
    # BaseException, in current asyncio implementations).
    try:
        out = await routes._translate_batches_parallel(flat, batch_size=8)
    except FakePanic:
        return
    # If gather did swallow the BaseException, the output should at least
    # not corrupt the input dict (English fallback preserved).
    assert out["k.current_summary"] == "en source"


# ─────────────── pre-translation cache helpers ───────────────


class _StubIssue:
    """Stand-in for a `ComparisonIssue` row — only the prose attributes
    the flattener reads. The real model carries citations + ids; we just
    need the fields ``_flatten_for_translation`` walks."""

    def __init__(self, ident: str, **kwargs):
        self.id = ident
        self.current_summary = kwargs.get("current_summary")
        self.gaap_summary = kwargs.get("gaap_summary")
        self.ifrs_summary = kwargs.get("ifrs_summary")
        self.differences = kwargs.get("differences")
        self.conversion_impact = kwargs.get("conversion_impact")
        self.gaap_verification = kwargs.get("gaap_verification")
        self.ifrs_verification = kwargs.get("ifrs_verification")


def test_flatten_for_translation_collects_rationale_and_prose() -> None:
    """Run-level rationale lands under `_run.rationale`; per-issue fields
    are keyed `<issue_id>.<prose_field>`. Empty / whitespace-only values
    are skipped so the LLM doesn't waste tokens on blanks."""
    issues = [
        _StubIssue(
            "abc",
            current_summary="Revenue recognized when control transfers.",
            gaap_summary="",  # skipped — empty
            ifrs_summary="   ",  # skipped — whitespace
            differences="GAAP differs from IFRS on EPS computation.",
        ),
        _StubIssue(
            "def",
            current_summary="Lease accounting follows ASC 842.",
            conversion_impact="Right-of-use asset must be re-measured.",
        ),
    ]
    flat = translation_svc._flatten_for_translation("Detected US GAAP.", issues)

    assert flat["_run.rationale"] == "Detected US GAAP."
    assert flat["abc.current_summary"] == "Revenue recognized when control transfers."
    assert flat["abc.differences"] == "GAAP differs from IFRS on EPS computation."
    assert flat["def.current_summary"] == "Lease accounting follows ASC 842."
    assert flat["def.conversion_impact"] == "Right-of-use asset must be re-measured."
    # Empty fields elided.
    assert "abc.gaap_summary" not in flat
    assert "abc.ifrs_summary" not in flat


def test_flatten_for_translation_skips_blank_rationale() -> None:
    """No `_run.rationale` key when the rationale is None or whitespace —
    avoids round-tripping an empty string through the LLM."""
    assert translation_svc._flatten_for_translation(None, []) == {}
    assert translation_svc._flatten_for_translation("   ", []) == {}


def test_translations_cover_requires_every_key() -> None:
    """A partial cache must NOT count as covered — the export route falls
    back to synchronous translation for missing keys, but only when this
    check correctly identifies the gap."""
    flat = {"a": "x", "b": "y", "c": "z"}

    assert translation_svc.translations_cover({"a": "א", "b": "ב", "c": "ג"}, flat)
    assert not translation_svc.translations_cover({"a": "א", "b": "ב"}, flat)
    assert not translation_svc.translations_cover({}, flat)
    assert not translation_svc.translations_cover(None, flat)


# ─────────────── boilerplate localization ───────────────


def test_localize_boilerplate_passthrough_for_english_locale() -> None:
    """English exports must not be touched — `localize_boilerplate`
    short-circuits when locale != 'he'."""
    text = "[synthesized from model knowledge — no standards retrieved]\n\nbody"
    assert translation_svc.localize_boilerplate(text, "en") == text


def test_localize_boilerplate_translates_synthesis_marker() -> None:
    """The synthesis-fallback prefix is the most visible English fragment
    when LLM translation degrades — must always Hebrew-ize."""
    text = (
        "[synthesized from model knowledge — no standards retrieved]\n\n"
        "Under US GAAP, interest income is recognized using the EIR."
    )
    out = translation_svc.localize_boilerplate(text, "he") or ""
    assert "[סונתז מידע מהמודל — לא אותרו תקנים]" in out
    # The body after the marker stays as-is (LLM territory).
    assert "Under US GAAP" in out


def test_localize_boilerplate_translates_verifier_no_corpus() -> None:
    """The verifier's canned 'no quotes were retrieved' sentence — emitted
    per framework — must localize cleanly. Both US GAAP and IFRS variants
    are covered."""
    us = (
        "No US GAAP (FASB ASC) standards quotes were retrieved for this side "
        "— verification not possible. Treat the summary as based on the "
        "model's general knowledge only."
    )
    ifrs = (
        "No IFRS / IAS standards quotes were retrieved for this side "
        "— verification not possible. Treat the summary as based on the "
        "model's general knowledge only."
    )
    out_us = translation_svc.localize_boilerplate(us, "he") or ""
    out_ifrs = translation_svc.localize_boilerplate(ifrs, "he") or ""
    assert "לא אותרו ציטוטי תקני US GAAP" in out_us
    assert "לא אותרו ציטוטי תקני IFRS" in out_ifrs
    # No English carry-over in either result.
    assert "No US GAAP" not in out_us
    assert "No IFRS" not in out_ifrs


def test_localize_boilerplate_translates_derived_differences() -> None:
    """The `_derive_differences` canned text (both 'compare-above' and
    the single-side variants) must Hebrew-ize."""
    a = (
        "Compare the two summaries above. The US GAAP excerpts emphasize the "
        "FASB ASC measurement rules; the IFRS excerpts apply the IASB "
        "principles-based approach. See the side-by-side citations for the "
        "controlling paragraphs."
    )
    b = "Only US GAAP standards were retrieved; IFRS standards corpus may not be loaded."
    c = "Only IFRS standards were retrieved; US GAAP corpus may not be loaded."
    out_a = translation_svc.localize_boilerplate(a, "he") or ""
    out_b = translation_svc.localize_boilerplate(b, "he") or ""
    out_c = translation_svc.localize_boilerplate(c, "he") or ""
    assert "השוו בין שני הסיכומים" in out_a
    assert "אותרו רק תקני US GAAP" in out_b
    assert "אותרו רק תקני IFRS" in out_c
    assert "Compare the two" not in out_a
    assert "Only US GAAP" not in out_b
    assert "Only IFRS" not in out_c


def test_localize_boilerplate_translates_verifier_failed_prefix() -> None:
    """The dynamic '(verifier agent failed: <exc>)' prefix keeps the
    runtime exception repr — only the framing flips to Hebrew."""
    text = "(verifier agent failed: TimeoutError('60s'))"
    out = translation_svc.localize_boilerplate(text, "he") or ""
    assert out.startswith("(סוכן האימות נכשל:")
    assert "TimeoutError" in out


def test_localize_boilerplate_idempotent_on_already_hebrew_text() -> None:
    """A second pass over Hebrew output must be a no-op — Hebrew strings
    contain no English substring keys."""
    text = (
        "[synthesized from model knowledge — no standards retrieved]\n\n"
        "Under US GAAP, interest income is recognized."
    )
    once = translation_svc.localize_boilerplate(text, "he") or ""
    twice = translation_svc.localize_boilerplate(once, "he") or ""
    assert once == twice


def test_localize_boilerplate_none_and_empty_passthrough() -> None:
    assert translation_svc.localize_boilerplate(None, "he") is None
    assert translation_svc.localize_boilerplate("", "he") == ""


def test_kick_pretranslation_no_running_loop_is_a_noop() -> None:
    """Called from a sync context (e.g. a test, or an early-startup hook),
    `kick_pretranslation` must not crash — it just logs and returns."""
    import uuid
    # If this raised, pytest would fail; the assertion is the lack of
    # exception. We can't easily assert "no task scheduled" without
    # reaching into the private set, but the no-loop branch is the one
    # we care about — verify it's hit by ensuring the task set is unchanged.
    before = len(translation_svc._PRETRANSLATION_TASKS)
    translation_svc.kick_pretranslation(uuid.uuid4())
    assert len(translation_svc._PRETRANSLATION_TASKS) == before
