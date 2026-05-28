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

import asyncio

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


async def test_translate_to_hebrew_uses_llm_output_when_response_is_hebrew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: fake LLM returns a Hebrew translation,
    ``_translate_to_hebrew`` writes it into the result dict."""

    async def fake_complete(_self, _prompt, *, system=None):
        from app.llm.client import LLMResponse

        return LLMResponse(
            text="ההכרה בהכנסה כאשר השליטה מועברת.",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )

    monkeypatch.setattr(FakeLLM, "complete", fake_complete)

    items = {"a.current_summary": "Revenue is recognized when control transfers."}
    out = await routes._translate_to_hebrew(items)
    assert out["a.current_summary"] == "ההכרה בהכנסה כאשר השליטה מועברת."


async def test_translate_to_hebrew_rejects_english_response_as_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production bug we're guarding against: gpt-oss:120b sometimes
    returns the input English largely unchanged when asked to translate.
    The old batched-JSON path silently cached those as "translated"; the
    new per-field path detects the absence of Hebrew characters and
    keeps the English source (so the boilerplate localizer downstream
    still gets a chance, and a later retry can try again).
    """

    async def fake_complete(_self, prompt, *, system=None):
        from app.llm.client import LLMResponse
        # Mimic the production failure: model echoes the input prose
        # back unchanged instead of translating.
        return LLMResponse(
            text="Revenue is recognized when control transfers.",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )

    monkeypatch.setattr(FakeLLM, "complete", fake_complete)

    items = {"a.current_summary": "Revenue is recognized when control transfers."}
    out = await routes._translate_to_hebrew(items)
    # Failed translation degrades to English source — the dict still has
    # the key (so cache-cover logic still works) but the value is the
    # original, NOT the non-Hebrew "translation".
    assert out["a.current_summary"] == "Revenue is recognized when control transfers."


async def test_translate_to_hebrew_strips_preamble_when_llm_ignores_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt tells the LLM "Output ONLY the Hebrew translation, no
    preamble" but models occasionally echo "HEBREW TRANSLATION:" / a
    markdown fence anyway. The parser strips them so the Hebrew lands
    cleanly in the cache."""

    async def fake_complete(_self, _prompt, *, system=None):
        from app.llm.client import LLMResponse
        return LLMResponse(
            text="```hebrew\nההכרה בהכנסה כאשר השליטה מועברת.\n```",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )

    monkeypatch.setattr(FakeLLM, "complete", fake_complete)
    items = {"a.current_summary": "Revenue is recognized when control transfers."}
    out = await routes._translate_to_hebrew(items)
    assert out["a.current_summary"] == "ההכרה בהכנסה כאשר השליטה מועברת."


async def test_translate_to_hebrew_per_field_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One field failing must not poison the others. Per-field LLM calls
    are independent: if `gaap_summary` returns English (failed) and
    `ifrs_summary` returns Hebrew (success), the result dict has
    English for the first and Hebrew for the second.
    """

    call_count = {"n": 0}

    async def fake_complete(_self, prompt, *, system=None):
        from app.llm.client import LLMResponse
        call_count["n"] += 1
        # Branch on text unique to one field's INPUT, not on words like
        # "IFRS" that appear in the prompt template itself.
        if "control transfers" in prompt:
            # Field 2 succeeds.
            return LLMResponse(text="תחת IFRS, הכנסות ריבית מוכרות בשיטת EIR.", usage={})
        # Field 1 fails (LLM echoes English back).
        return LLMResponse(text="Under US GAAP, interest income.", usage={})

    monkeypatch.setattr(FakeLLM, "complete", fake_complete)

    items = {
        "a.gaap_summary": "Under US GAAP, interest income.",
        "a.ifrs_summary": "Revenue recognized when control transfers.",
    }
    out = await routes._translate_to_hebrew(items)
    # First field failed → English source preserved.
    assert out["a.gaap_summary"] == "Under US GAAP, interest income."
    # Second field succeeded → Hebrew.
    assert out["a.ifrs_summary"] == "תחת IFRS, הכנסות ריבית מוכרות בשיטת EIR."


async def test_translate_batches_parallel_delegates_to_translate_to_hebrew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_translate_batches_parallel`` is now a thin pass-through to
    ``_translate_to_hebrew`` — the per-field implementation handles
    parallelism + failure isolation internally, so there's no outer
    batching layer to test. This test pins the delegation contract so a
    future refactor that breaks it (and silently stops translating) is
    caught.
    """

    async def fake_translate(items, *, per_batch_timeout=18.0):
        # Marker prefix proves the patched implementation ran.
        return {k: f"HE:{v}" for k, v in items.items()}

    monkeypatch.setattr(translation_svc, "_translate_to_hebrew", fake_translate)

    flat = {f"k{i}.current_summary": f"v{i}" for i in range(8)}
    out = await routes._translate_batches_parallel(flat, batch_size=4)
    assert set(out) == set(flat)
    # Every value passed through the patched implementation — confirms
    # _translate_batches_parallel didn't bypass the function under test.
    assert all(v.startswith("HE:") for v in out.values())


async def test_translate_batches_parallel_empty_input() -> None:
    assert await routes._translate_batches_parallel({}, batch_size=8) == {}


async def test_translate_to_hebrew_swallows_base_exception_per_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BaseException-derived panic from inside a single LLM call must
    NOT leak out as a bare 500. Per-field translation catches
    BaseException at the field level so one panicking field keeps its
    English source and the rest of the dict still translates.
    Reproduces the failure mode where cryptography's Rust bindings panic
    during the LLM client's TLS handshake.
    """

    class FakePanic(BaseException):
        pass

    async def panicking(_self, _prompt, *, system=None):
        raise FakePanic("simulated rust panic during translation")

    monkeypatch.setattr(FakeLLM, "complete", panicking)

    flat = {"k.current_summary": "en source"}
    # No exception leaks; English source preserved on per-field failure.
    out = await routes._translate_to_hebrew(flat)
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


def test_flatten_for_translation_skips_already_hebrew_fields() -> None:
    """When the orchestrator generated a run in Hebrew (user's stored
    locale was 'he'), the prose is already in the target language. Those
    fields must NOT be flattened for translation — re-sending Hebrew to
    the LLM "to translate to Hebrew" wastes calls and risks corruption.
    The export route renders skipped fields verbatim via its getattr
    fallback.
    """
    issues = [
        _StubIssue(
            "heb",
            current_summary="ההכרה בהכנסה מתבצעת כאשר השליטה מועברת.",  # Hebrew
            gaap_summary="Under US GAAP, revenue is recognized on transfer.",  # English
        ),
    ]
    flat = translation_svc._flatten_for_translation(
        "זוהה תקן US GAAP.", issues,  # Hebrew rationale
    )
    # Hebrew rationale + Hebrew current_summary skipped; only the English
    # gaap_summary remains for translation.
    assert "_run.rationale" not in flat
    assert "heb.current_summary" not in flat
    assert flat["heb.gaap_summary"] == "Under US GAAP, revenue is recognized on transfer."


def test_flatten_for_translation_hebrew_run_yields_empty() -> None:
    """A run fully generated in Hebrew flattens to an empty dict — the
    export route then short-circuits the whole translation path and
    renders the stored Hebrew prose directly (no LLM call)."""
    issues = [
        _StubIssue(
            "heb",
            current_summary="טקסט עברי אחד.",
            gaap_summary="טקסט עברי שתיים.",
            ifrs_summary="טקסט עברי שלוש.",
            differences="טקסט עברי ארבע.",
        ),
    ]
    assert translation_svc._flatten_for_translation("נימוק בעברית.", issues) == {}


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


# ─────────────── end-to-end: simulated production data ───────────────
#
# These tests reproduce the exact failure mode the user reported in the
# screenshot ticket: Hebrew section headers, Hebrew boilerplate (the fix
# from 055b304 worked), but English body prose because the LLM was
# returning JSON with unchanged English values. The flow under test is
# the same one the export route runs after pre-translation has (or
# hasn't) populated the cache.


def _make_issue(
    ident: str,
    *,
    gaap_summary: str | None = None,
    ifrs_summary: str | None = None,
    gaap_verification: str | None = None,
) -> _StubIssue:
    return _StubIssue(
        ident,
        gaap_summary=gaap_summary,
        ifrs_summary=ifrs_summary,
        gaap_verification=gaap_verification,
    )


async def test_e2e_flat_dict_translates_when_llm_returns_hebrew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: simulate the real LLM returning Hebrew, run through
    flatten + translate, verify every key has Hebrew in the output."""

    async def fake_complete(_self, prompt, *, system=None):
        from app.llm.client import LLMResponse
        # Echo a believable Hebrew translation. The prompt always passes
        # the English text in the `text=` slot; we just return Hebrew.
        if "interest income" in prompt:
            return LLMResponse(text="הכנסות ריבית מוכרות בשיטת EIR.", usage={})
        if "credit-risk losses" in prompt:
            return LLMResponse(text="הפסדי סיכון אשראי נמדדים לפי IFRS 9.", usage={})
        if "verifier" in prompt.lower() or "no us gaap" in prompt.lower():
            return LLMResponse(text="לא אותרו ציטוטים.", usage={})
        return LLMResponse(text="טקסט בעברית.", usage={})

    monkeypatch.setattr(FakeLLM, "complete", fake_complete)

    issues = [
        _make_issue(
            "issue-1",
            gaap_summary=(
                "[synthesized from model knowledge — no standards retrieved]\n\n"
                "Under US GAAP, interest income is recognized using EIR."
            ),
            ifrs_summary=(
                "Under IFRS, credit-risk losses are measured under IFRS 9."
            ),
            gaap_verification=(
                "No US GAAP (FASB ASC) standards quotes were retrieved for "
                "this side — verification not possible."
            ),
        ),
    ]
    flat = translation_svc._flatten_for_translation(None, issues)
    translated = await translation_svc._translate_batches_parallel(flat)

    # Every key has Hebrew content — no field silently degraded to English.
    for key, value in translated.items():
        assert translation_svc._contains_hebrew(value), (
            f"key {key} lacks Hebrew chars: {value!r}"
        )


async def test_e2e_english_llm_response_does_not_poison_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production failure being fixed: gpt-oss:120b returns the English
    input largely unchanged. The old batched-JSON path cached those
    values as "translated" and the export served English forever.

    With per-field validation, a non-Hebrew response is rejected and the
    English source is preserved — so the next retry (kicked from
    `get_run` or from the export route) gets another shot at producing
    real Hebrew.
    """

    async def english_back(_self, prompt, *, system=None):
        from app.llm.client import LLMResponse
        # Extract the English text from the prompt and echo it back —
        # simulates the LLM saying "I see the structure, I'll preserve it".
        marker = "ENGLISH TEXT:\n"
        idx = prompt.find(marker)
        text = prompt[idx + len(marker):].split("\n\nHEBREW")[0].strip()
        return LLMResponse(text=text, usage={})

    monkeypatch.setattr(FakeLLM, "complete", english_back)

    flat = {
        "issue-1.gaap_summary": "Under US GAAP, interest income is EIR-based.",
        "issue-1.ifrs_summary": "Under IFRS, IFRS 9 governs credit-risk losses.",
    }
    out = await translation_svc._translate_batches_parallel(flat)

    # Both values were rejected (no Hebrew chars in response) so the dict
    # still has the English source — NOT the LLM's "translation" of it.
    # The `pretranslate_run_to_hebrew` cache-writer's `v != src` check
    # then keeps the cache empty, leaving room for a real retry.
    assert out["issue-1.gaap_summary"] == flat["issue-1.gaap_summary"]
    assert out["issue-1.ifrs_summary"] == flat["issue-1.ifrs_summary"]


async def test_e2e_mixed_llm_response_only_caches_hebrew_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Realistic intermediate state: the LLM translates some fields but
    echoes others in English. After translation, only the Hebrew fields
    should have changed in `out`; the others stay English so a future
    retry can fill them in.
    """

    async def maybe_translate(_self, prompt, *, system=None):
        from app.llm.client import LLMResponse
        # Branch on text unique to the IFRS field's INPUT — "credit-risk
        # losses" appears in the IFRS field's body but not the GAAP one,
        # and it's not in the prompt template's IFRS-9 reference list.
        if "credit-risk losses" in prompt:
            return LLMResponse(text="טקסט עברי על הפסדי סיכון אשראי.", usage={})
        marker = "ENGLISH TEXT:\n"
        idx = prompt.find(marker)
        text = prompt[idx + len(marker):].split("\n\nHEBREW")[0].strip()
        return LLMResponse(text=text, usage={})

    monkeypatch.setattr(FakeLLM, "complete", maybe_translate)

    flat = {
        "issue-1.gaap_summary": "Under US GAAP, interest income is EIR-based.",
        "issue-1.ifrs_summary": "IFRS 9 governs credit-risk losses for banks.",
    }
    out = await translation_svc._translate_batches_parallel(flat)

    # GAAP failed (English echo) — English preserved.
    assert out["issue-1.gaap_summary"] == flat["issue-1.gaap_summary"]
    # IFRS translated to Hebrew.
    assert out["issue-1.ifrs_summary"] == "טקסט עברי על הפסדי סיכון אשראי."


def test_contains_hebrew_detects_hebrew_chars() -> None:
    """The Hebrew character predicate is the gate that decides whether a
    "translation" is real. Tested directly so a future regex tweak that
    accidentally fails to match Hebrew (or matches English) shows up."""
    assert translation_svc._contains_hebrew("שלום")
    assert translation_svc._contains_hebrew("Under IFRS, תחת IFRS")  # mixed
    assert not translation_svc._contains_hebrew("Under IFRS, interest income.")
    assert not translation_svc._contains_hebrew("")
    assert not translation_svc._contains_hebrew("12345 ASC 326 EIR")


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


async def test_kick_pretranslation_dedupes_inflight_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`get_run` re-kicks pre-translation on every poll of a done run with
    an incomplete cache. Without the in-flight guard, a page polling every
    couple of seconds would fan out ~20 fresh LLM calls per poll — a
    self-inflicted request storm that exhausts Ollama keys (429s) and
    pressures the worker. The guard collapses repeated kicks for the same
    run into a single in-flight task."""
    import uuid as _uuid

    started: list[_uuid.UUID] = []
    release = asyncio.Event()

    async def fake_pretranslate(run_id: _uuid.UUID) -> None:
        started.append(run_id)
        await release.wait()

    monkeypatch.setattr(translation_svc, "pretranslate_run_to_hebrew", fake_pretranslate)

    rid = _uuid.uuid4()
    translation_svc.kick_pretranslation(rid)
    translation_svc.kick_pretranslation(rid)  # de-duped — same run in flight
    translation_svc.kick_pretranslation(rid)  # de-duped
    await asyncio.sleep(0)  # let the single task start

    assert started.count(rid) == 1, "only one task should run for a single run"
    assert rid in translation_svc._PRETRANSLATION_INFLIGHT

    # Release and drain so the done-callback clears the in-flight marker.
    release.set()
    pending = list(translation_svc._PRETRANSLATION_TASKS)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0)
    assert rid not in translation_svc._PRETRANSLATION_INFLIGHT
