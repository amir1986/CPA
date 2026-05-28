"""Unit tests for the USGAAP <> IFRS orchestrator's pure-logic pieces.

The full DB-touching path is exercised by the Playwright e2e
(`web/tests/e2e/usgaap-ifrs.spec.ts`); here we cover the bits that decide
what makes it into a run's persisted issues:

  - JSON parsing tolerates markdown fences and stray prose.
  - File-kind dispatch picks the right extractor from mime/suffix.
  - Source-ref filtering drops issues whose refs don't resolve.
  - Citation dicts round-trip.
  - The difference-fallback never returns an empty string when both sides
    are present.
"""

from __future__ import annotations

import json

import pytest

from app.db.models.files import File, FileKind, ParsedStatus
from app.domain.models import Citation
from app.ingest_docs.extractors.pdf_text import ExtractedSpan
from app.llm.client import FakeLLM
from app.rag.query_engine import QueryAnswer
from app.services.comparison_orchestrator import (
    _build_corpus,
    _citation_dicts,
    _derive_differences,
    _detect_and_identify,
    _kind_from_file,
    _locale_directive,
    _parse_json,
    _run_one_agent,
    _synthesize_treatment,
    _verify_one_side,
)


def _file(name: str, mime: str | None = None) -> File:
    import uuid as _uuid

    return File(
        id=_uuid.uuid4(),
        engagement_id=_uuid.uuid4(),
        kind=FileKind.policy,
        original_name=name,
        s3_uri="s3://bucket/k",
        sha256="x" * 64,
        mime=mime,
        size=1,
        parsed_status=ParsedStatus.queued,
    )


def test_kind_from_file_prefers_mime_then_suffix() -> None:
    assert _kind_from_file(_file("a.pdf", "application/pdf")) == "pdf"
    assert _kind_from_file(_file("a.docx")) == "docx"
    assert _kind_from_file(_file("a.csv", "text/csv")) == "csv"
    assert _kind_from_file(_file("sheet.xlsx")) == "xlsx"
    # Unknown suffix + unknown mime → None so the caller can fail loudly.
    assert _kind_from_file(_file("blob.bin", "application/octet-stream")) is None


def test_parse_json_handles_markdown_fences() -> None:
    raw = "```json\n{\"answer\":\"ok\"}\n```"
    assert _parse_json(raw) == {"answer": "ok"}


def test_parse_json_recovers_from_surrounding_prose() -> None:
    raw = 'Here is the result:\n\n{"detected_framework":"US","confidence":0.8}\n\nThanks!'
    out = _parse_json(raw)
    assert out["detected_framework"] == "US"
    assert out["confidence"] == 0.8


def test_parse_json_returns_empty_on_garbage() -> None:
    assert _parse_json("this is not JSON at all") == {}


def test_build_corpus_skips_empty_spans_and_keeps_anchors() -> None:
    spans = [
        ("file-a::page=1", ExtractedSpan(anchor="page=1", text="Revenue is recognized when control transfers.")),
        ("file-a::page=2", ExtractedSpan(anchor="page=2", text="   ")),
        ("file-b::row=2", ExtractedSpan(anchor="row=2", text="Lease assets are capitalized.")),
    ]
    corpus = _build_corpus(spans)
    # Both non-empty spans appear with their chunk ids; the empty one is dropped.
    assert 'id="file-a::page=1"' in corpus
    assert 'id="file-b::row=2"' in corpus
    assert 'id="file-a::page=2"' not in corpus
    assert "control transfers" in corpus
    assert "Lease assets" in corpus


@pytest.mark.asyncio
async def test_detect_and_identify_drops_fabricated_refs() -> None:
    """If the LLM cites a source ref that isn't in the corpus, drop that issue."""
    fake = FakeLLM()
    fake.set_response(json.dumps({
        "detected_framework": "US",
        "confidence": 0.8,
        "issues": [
            {
                "topic": "Real",
                "current_summary": "...",
                "source_chunk_refs": ["valid-ref-A", "bogus-ref"],
            },
            {
                "topic": "Phantom",
                "current_summary": "...",
                "source_chunk_refs": ["bogus-only"],
            },
            {
                "topic": "Empty refs",
                "current_summary": "...",
                "source_chunk_refs": [],
            },
        ],
    }))

    result = await _detect_and_identify(
        "irrelevant — fake LLM ignores corpus",
        valid_chunk_ids={"valid-ref-A", "another-valid"},
        llm=fake,
    )

    issues = result["issues"]
    assert len(issues) == 1
    assert issues[0]["topic"] == "Real"
    # The bogus ref must have been stripped; only the valid one survives.
    assert issues[0]["source_chunk_refs"] == ["valid-ref-A"]


@pytest.mark.asyncio
async def test_detect_and_identify_adds_hebrew_directive_when_locale_he() -> None:
    """The detect/identify step produces the rationale, topic,
    current_summary and conversion_impact. When locale=he it must tell the
    LLM to write those string values in Hebrew (the framework-detection
    rationale was rendering in English inside a Hebrew UI). We capture the
    prompt the LLM receives and assert the directive presence by locale."""

    class _Capture(FakeLLM):
        def __init__(self) -> None:
            super().__init__()
            self.set_response(json.dumps({"detected_framework": "US", "issues": []}))
            self.seen = ""

        async def complete(self, prompt, *, system=None):
            self.seen = prompt
            return await super().complete(prompt, system=system)

    he = _Capture()
    await _detect_and_identify("corpus", valid_chunk_ids=set(), llm=he, locale="he")
    assert "in Hebrew" in he.seen

    en = _Capture()
    await _detect_and_identify("corpus", valid_chunk_ids=set(), llm=en, locale="en")
    assert "in Hebrew" not in en.seen


def test_citation_dicts_roundtrip() -> None:
    cite = Citation(standard="ASC 606", paragraph="25-1", url="https://x/y", quote="control transfers")
    out = _citation_dicts([cite])
    assert out == [{
        "standard": "ASC 606",
        "paragraph": "25-1",
        "url": "https://x/y",
        "quote": "control transfers",
    }]


def test_derive_differences_never_empty_when_both_sides_present() -> None:
    gaap = QueryAnswer(answer="US ans", citations=[], refused=False, language="en", retrieved=[])
    ifrs = QueryAnswer(answer="IFRS ans", citations=[], refused=False, language="en", retrieved=[])
    out = _derive_differences(gaap, ifrs)
    assert out and "side-by-side" in out


def test_derive_differences_explains_missing_side() -> None:
    gaap = QueryAnswer(answer="US ans", citations=[], refused=False, language="en", retrieved=[])
    out = _derive_differences(gaap, None)
    assert out and "IFRS standards corpus" in out


def test_derive_differences_none_when_both_refused() -> None:
    refused_gaap = QueryAnswer(answer="", citations=[], refused=True, language="en", retrieved=[])
    refused_ifrs = QueryAnswer(answer="", citations=[], refused=True, language="en", retrieved=[])
    assert _derive_differences(refused_gaap, refused_ifrs) is None


# ─────────────── locale-aware generation ───────────────


def test_locale_directive_only_for_hebrew() -> None:
    """English (and any non-he locale) generates with the model's default
    language — no directive. Hebrew gets the explicit "write in Hebrew"
    instruction that keeps standard codes in English."""
    assert _locale_directive("en") == ""
    assert _locale_directive("fr") == ""
    he = _locale_directive("he")
    assert "Hebrew" in he
    # Standard codes must stay English even in the Hebrew directive.
    assert "ASC 606" in he and "IFRS 9" in he


@pytest.mark.asyncio
async def test_synthesize_treatment_appends_hebrew_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When locale=he, the synthesis prompt must instruct the model to
    write Hebrew. We capture the prompt the LLM actually receives and
    assert the directive is present (he) / absent (en)."""
    seen: dict[str, str] = {}

    class _Capture:
        async def complete(self, prompt, *, system=None):
            from app.llm.client import LLMResponse
            seen["prompt"] = prompt
            return LLMResponse(text="טקסט בעברית על הכרה בהכנסה.", usage={})

    out_he = await _synthesize_treatment(
        "Revenue recognition", "policy excerpt", "US", _Capture(), locale="he",
    )
    assert "Write your entire answer in Hebrew" in seen["prompt"]
    # The marker prefix is English (boilerplate localizer flips it later),
    # but the body the model returned is Hebrew.
    assert out_he.startswith("[synthesized from model knowledge")
    assert "טקסט בעברית" in out_he

    await _synthesize_treatment(
        "Revenue recognition", "policy excerpt", "US", _Capture(), locale="en",
    )
    assert "Write your entire answer in Hebrew" not in seen["prompt"]


@pytest.mark.asyncio
async def test_run_one_agent_threads_locale_into_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent question must carry the Hebrew directive when locale=he
    so the agent-authored summary comes back in Hebrew."""
    captured: dict[str, str] = {}

    async def fake_run_agent(question, *, tools, llm, max_steps):
        from app.agent.agent import AgentResult
        captured["question"] = question
        return AgentResult(final_answer="", citations=[])

    monkeypatch.setattr(
        "app.services.comparison_orchestrator.run_agent", fake_run_agent,
    )
    # _run_one_agent calls get_llm() to pass the client into run_agent;
    # stub it so the test doesn't need real OLLAMA_API_KEYS.
    monkeypatch.setattr(
        "app.services.comparison_orchestrator.get_llm", lambda: FakeLLM(),
    )
    await _run_one_agent("Leases", "policy", "IFRS", locale="he")
    assert "Write your entire answer in Hebrew" in captured["question"]

    await _run_one_agent("Leases", "policy", "US", locale="en")
    assert "Write your entire answer in Hebrew" not in captured["question"]


@pytest.mark.asyncio
async def test_verify_one_side_threads_locale_into_prompt() -> None:
    """The verifier's LLM-authored report must be requested in Hebrew when
    locale=he (only matters when citations exist — the no-corpus message
    is canned English that the export localizer handles)."""
    seen: dict[str, str] = {}

    class _Capture:
        async def complete(self, prompt, *, system=None):
            from app.llm.client import LLMResponse
            seen["prompt"] = prompt
            return LLMResponse(text="דוח אימות בעברית.", usage={})

    cites = [{"standard": "IFRS 9", "quote": "An entity shall recognise..."}]
    out = await _verify_one_side("IFRS", "summary text", cites, _Capture(), locale="he")
    assert "Write your entire answer in Hebrew" in seen["prompt"]
    assert out == "דוח אימות בעברית."
