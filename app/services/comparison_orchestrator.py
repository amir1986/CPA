"""USGAAP <> IFRS orchestrator.

Given a freshly created ``ComparisonRun`` and a set of uploaded files, the
orchestrator:

1. Pulls each file's bytes from S3 and dispatches to the right extractor by
   MIME / suffix.
2. Runs a single structured LLM call ("detect framework + identify issues")
   over the concatenated narrative text.
3. For every identified issue, fans out two parallel ``answer_question``
   calls — one filtered to ``jurisdictions=["US"]``, one to ``["IFRS"]`` —
   to gather standards-side citations for the side-by-side render.
4. Persists each issue, marks the run ``done``.

Failures along the way set ``status='failed'`` and ``error=<reason>`` on
the run rather than crashing the request — the SSE stream surfaces the
final state. Telemetry is intentionally minimal here (no Prometheus
counters) so the orchestrator is easy to unit-test with a FakeLLM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.db.models.comparison_models import (
    ComparisonIssue,
    ComparisonRun,
    ComparisonStatus,
    Framework,
)
from app.db.models.files import File
from app.db.session import get_sessionmaker
from app.ingest_docs.extractors.pdf_text import (
    ExtractedSpan,
    extract_pdf_text,
    is_likely_scanned,
)
from app.llm.client import LLMClient, get_llm
from app.rag.query_engine import answer_question
from app.storage.s3 import get_object_store

logger = logging.getLogger(__name__)


@dataclass
class _ExtractResult:
    spans: list[ExtractedSpan]
    likely_scanned: bool


SUPPORTED_MIMES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/csv": "csv",
    "application/csv": "csv",
}


def _kind_from_file(f: File) -> str | None:
    mime = (f.mime or "").lower()
    if mime in SUPPORTED_MIMES:
        return SUPPORTED_MIMES[mime]
    name = (f.original_name or "").lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    if name.endswith(".xlsx"):
        return "xlsx"
    if name.endswith(".csv"):
        return "csv"
    return None


async def _extract_one(f: File) -> _ExtractResult:
    store = get_object_store()
    key = f.s3_uri.split("/", 3)[-1] if f.s3_uri.startswith("s3://") else f.s3_uri
    body = await store.get(key)
    kind = _kind_from_file(f)
    if kind == "pdf":
        spans = extract_pdf_text(body)
        return _ExtractResult(spans=spans, likely_scanned=is_likely_scanned(spans))
    if kind == "docx":
        from app.ingest_docs.extractors.docx import extract_docx
        return _ExtractResult(spans=extract_docx(body), likely_scanned=False)
    if kind == "xlsx":
        from app.ingest_docs.extractors.excel_narrative import extract_xlsx_narrative
        return _ExtractResult(spans=extract_xlsx_narrative(body), likely_scanned=False)
    if kind == "csv":
        from app.ingest_docs.extractors.csv_ import extract_csv
        return _ExtractResult(spans=extract_csv(body), likely_scanned=False)
    raise ValueError(f"unsupported file kind: {f.original_name} (mime={f.mime})")


def _build_corpus(spans: list[tuple[str, ExtractedSpan]]) -> str:
    """Join all spans into a single chunked text blob the LLM can see, each
    span prefixed with its anchor so it can reference them by ID."""
    pieces: list[str] = []
    for ref, sp in spans:
        if not sp.text.strip():
            continue
        pieces.append(f"<chunk id=\"{ref}\">\n{sp.text}\n</chunk>")
    return "\n\n".join(pieces)


_DETECT_PROMPT = """You are a CPA assistant analyzing a client's uploaded accounting documents to translate them between US GAAP and IFRS.

Below is the full text of the upload, split into chunks identified by id="…":

{corpus}

Return a single JSON object with this exact shape (no markdown, no commentary outside the JSON):

{{
  "detected_framework": "US" | "IFRS",
  "confidence": <float 0..1>,
  "rationale": "<one sentence on why>",
  "issues": [
    {{
      "topic": "<short accounting topic, e.g. 'Revenue recognition' or 'Lease accounting'>",
      "current_summary": "<2-4 sentences summarizing what the document says about this topic>",
      "source_chunk_refs": ["<chunk id from above>", ...],
      "conversion_impact": "<1-2 sentences on what changes when flipping to the other framework>"
    }}
  ]
}}

Rules:
- Identify between 1 and 6 distinct accounting topics actually discussed in the document.
- Every issue MUST cite at least one source_chunk_refs id from the chunks above.
- If the upload does not discuss any specific accounting treatment, return "issues": [].
- Pick "US" when references favor FASB ASC / US codification; pick "IFRS" when they favor IFRS / IAS / IFRIC.
"""


# Cap the detect-and-identify LLM call so a slow Ollama Cloud free-tier
# response doesn't pin runs in "detecting" forever. Two minutes is generous
# vs the typical 10-30 s response, and stays under typical client read
# timeouts on Render.
_DETECT_TIMEOUT_S = 120.0


async def _detect_and_identify(
    text: str,
    *,
    valid_chunk_ids: set[str],
    llm: LLMClient,
) -> dict[str, Any]:
    prompt = _DETECT_PROMPT.format(corpus=text)
    response = await asyncio.wait_for(llm.complete(prompt), timeout=_DETECT_TIMEOUT_S)
    parsed = _parse_json(response.text)
    # Drop fabricated source_chunk_refs.
    issues = parsed.get("issues") or []
    cleaned: list[dict[str, Any]] = []
    for issue in issues:
        refs = [r for r in (issue.get("source_chunk_refs") or []) if r in valid_chunk_ids]
        if not refs:
            logger.info("comparison: dropping issue with no resolvable refs: %s", issue.get("topic"))
            continue
        issue["source_chunk_refs"] = refs
        cleaned.append(issue)
    parsed["issues"] = cleaned
    return parsed


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json\n"):
            text = text[5:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _citation_dicts(citations: list) -> list[dict]:
    return [
        {
            "standard": c.standard,
            "paragraph": c.paragraph,
            "url": c.url,
            "quote": c.quote,
        }
        for c in citations
    ]


# Per-issue retrieval also gets a guard against runaway LLM calls. Both
# fan-outs share this budget; on timeout we return None/None and the
# orchestrator persists the issue with empty standards-side summaries.
_COMPARE_TIMEOUT_S = 120.0


async def _compare_one(topic: str, current_summary: str) -> tuple[Any, Any]:
    """Fan out both jurisdictions in parallel using the existing RAG engine."""
    question = (
        f"Summarize the treatment of {topic}. "
        f"The taxpayer's current policy states: {current_summary[:600]}. "
        f"Quote the controlling standard and identify the recognition / measurement rules."
    )
    return await asyncio.wait_for(
        asyncio.gather(
            answer_question(question, jurisdictions=["US"], corpus_types=["accounting"]),
            answer_question(question, jurisdictions=["IFRS"], corpus_types=["accounting"]),
        ),
        timeout=_COMPARE_TIMEOUT_S,
    )


async def run_orchestrator(run_id: uuid.UUID) -> None:
    """Drive the run from `parsing` → `detecting` → `comparing` → `done`/`failed`.

    Opens its own DB session because it is fired from `asyncio.create_task` —
    the request's session has long been closed by the time this runs.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        run = await session.get(ComparisonRun, run_id)
        if run is None:
            logger.error("comparison run vanished before orchestrator started: %s", run_id)
            return

        # ── 1. Extract every file ──
        run.status = ComparisonStatus.parsing
        await session.commit()

        all_spans: list[tuple[str, ExtractedSpan]] = []
        scanned_pdf_names: list[str] = []
        try:
            for fid_str in run.file_ids:
                fid = uuid.UUID(fid_str)
                f = await session.get(File, fid)
                if f is None:
                    continue
                result = await _extract_one(f)
                if result.likely_scanned:
                    scanned_pdf_names.append(f.original_name)
                    continue
                for sp in result.spans:
                    if sp.text.strip():
                        all_spans.append((f"{f.id}::{sp.anchor}", sp))
        except Exception as exc:
            logger.exception("comparison extraction failed: %s", run_id)
            run.status = ComparisonStatus.failed
            run.error = f"extraction failed: {exc}"
            await session.commit()
            return

        if not all_spans:
            run.status = ComparisonStatus.failed
            if scanned_pdf_names:
                run.error = (
                    "All uploaded PDFs look like scanned images. OCR is not "
                    f"yet supported. Files: {', '.join(scanned_pdf_names)}"
                )
            else:
                run.error = "no extractable text in uploaded files"
            await session.commit()
            return

        # ── 2. Detect framework + identify issues ──
        run.status = ComparisonStatus.detecting
        await session.commit()

        corpus = _build_corpus(all_spans)
        valid_ids = {ref for ref, _ in all_spans}
        try:
            parsed = await _detect_and_identify(corpus, valid_chunk_ids=valid_ids, llm=get_llm())
        except Exception as exc:
            logger.exception("comparison detect/identify failed: %s", run_id)
            run.status = ComparisonStatus.failed
            run.error = f"detect_failed: {exc}"
            await session.commit()
            return

        fw = parsed.get("detected_framework")
        run.detected_framework = Framework(fw) if fw in ("US", "IFRS") else None
        confidence = parsed.get("confidence")
        run.confidence = float(confidence) if isinstance(confidence, (int, float)) else None
        run.rationale = parsed.get("rationale")

        issues_payload = parsed.get("issues") or []
        if not issues_payload:
            run.status = ComparisonStatus.done
            run.error = "no accounting issues identified in the uploaded text"
            await session.commit()
            return

        # ── 3. Per-issue side-by-side ──
        run.status = ComparisonStatus.comparing
        await session.commit()

        # Index spans by ref so we can hydrate `current_user_cites`.
        spans_by_ref = {ref: sp for ref, sp in all_spans}

        for seq, issue in enumerate(issues_payload, start=1):
            topic = str(issue.get("topic") or f"Issue {seq}")[:200]
            current_summary = str(issue.get("current_summary") or "").strip()
            conversion_impact = str(issue.get("conversion_impact") or "").strip() or None
            user_cites_raw = issue.get("source_chunk_refs") or []
            user_cites = [
                {
                    "ref": ref,
                    "quote": spans_by_ref[ref].text[:500],
                    "anchor": spans_by_ref[ref].anchor,
                }
                for ref in user_cites_raw
                if ref in spans_by_ref
            ]

            try:
                gaap_ans, ifrs_ans = await _compare_one(topic, current_summary)
            except Exception as exc:
                logger.warning("comparison fan-out failed for topic %r: %s", topic, exc)
                gaap_ans = ifrs_ans = None

            row = ComparisonIssue(
                run_id=run.id,
                seq=seq,
                topic=topic,
                current_summary=current_summary,
                current_user_cites=user_cites,
                gaap_summary=(gaap_ans.answer if gaap_ans and not gaap_ans.refused else None),
                gaap_citations=_citation_dicts(gaap_ans.citations) if gaap_ans else [],
                ifrs_summary=(ifrs_ans.answer if ifrs_ans and not ifrs_ans.refused else None),
                ifrs_citations=_citation_dicts(ifrs_ans.citations) if ifrs_ans else [],
                differences=_derive_differences(gaap_ans, ifrs_ans),
                conversion_impact=conversion_impact,
            )
            session.add(row)

        run.status = ComparisonStatus.done
        await session.commit()


def _derive_differences(gaap_ans: Any, ifrs_ans: Any) -> str | None:
    """Simple deterministic difference summary so the memo's $differences
    slot is never empty. A future enhancement can replace this with a
    third LLM call once we want LLM-synthesized differences."""
    if gaap_ans and ifrs_ans and not gaap_ans.refused and not ifrs_ans.refused:
        return (
            "Compare the two summaries above. The US GAAP excerpts emphasize the "
            "FASB ASC measurement rules; the IFRS excerpts apply the IASB principles-based "
            "approach. See the side-by-side citations for the controlling paragraphs."
        )
    if gaap_ans and not gaap_ans.refused:
        return "Only US GAAP standards were retrieved; IFRS standards corpus may not be loaded."
    if ifrs_ans and not ifrs_ans.refused:
        return "Only IFRS standards were retrieved; US GAAP corpus may not be loaded."
    return None
