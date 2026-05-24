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

from app.agent.agent import run_agent
from app.agent.tools import Tool
from app.db.models.comparison_models import (
    ComparisonIssue,
    ComparisonRun,
    ComparisonStatus,
    Framework,
)
from app.db.models.files import File
from app.db.session import get_sessionmaker
from app.domain.models import Citation
from app.ingest_docs.extractors.pdf_text import (
    ExtractedSpan,
    extract_pdf_text,
    is_likely_scanned,
)
from app.llm.client import LLMClient, get_llm
from app.rag.query_engine import QueryAnswer, answer_question
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


# Ollama Cloud free-tier rejects single prompts above roughly 32K tokens
# with a 400 — large XLSX financial statements (hundreds of flattened
# rows) blow past that easily. Cap each span and the total corpus so the
# detect-and-identify prompt always fits the context window.
_MAX_SPAN_CHARS = 800
_MAX_CORPUS_CHARS = 24_000


def _build_corpus(spans: list[tuple[str, ExtractedSpan]]) -> str:
    """Join all spans into a single chunked text blob the LLM can see, each
    span prefixed with its anchor so it can reference them by ID.

    Truncates per-span and globally to keep the prompt under the model's
    context budget. When the global cap kicks in, picks an evenly-spaced
    sample of the spans instead of dropping the tail — for a long FS the
    tail rows are often the most informative (totals, notes).
    """
    non_empty = [(ref, sp) for ref, sp in spans if sp.text.strip()]
    if not non_empty:
        return ""

    # Per-span cap so one mega-row can't eat the entire budget.
    capped = [
        (ref, sp.text[:_MAX_SPAN_CHARS] + ("…[truncated]" if len(sp.text) > _MAX_SPAN_CHARS else ""))
        for ref, sp in non_empty
    ]

    # Estimate the full corpus; if it fits, return it directly.
    full = "\n\n".join(f"<chunk id=\"{ref}\">\n{text}\n</chunk>" for ref, text in capped)
    if len(full) <= _MAX_CORPUS_CHARS:
        return full

    # Otherwise, evenly-space-sample spans down to the budget.
    n = len(capped)
    # Roughly how many spans the budget can hold. Each chunk wrapper adds
    # ~25 chars of overhead.
    avg = max(1, sum(len(t) + 25 for _, t in capped) // n)
    target_count = max(1, _MAX_CORPUS_CHARS // avg)
    if target_count >= n:
        return full[:_MAX_CORPUS_CHARS] + "\n\n[corpus truncated — original document is larger]"
    step = n / target_count
    sampled_idxs = sorted({int(i * step) for i in range(target_count)} | {0, n - 1})
    sampled = [capped[i] for i in sampled_idxs if i < n]
    out = "\n\n".join(f"<chunk id=\"{ref}\">\n{text}\n</chunk>" for ref, text in sampled)
    out += f"\n\n[corpus sampled — {len(sampled)} of {n} chunks shown]"
    return out


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
_COMPARE_TIMEOUT_S = 180.0
_AGENT_MAX_STEPS = 4


def _kb_search_tool(jurisdiction: str) -> Tool:
    """A jurisdiction-scoped wrapper around ``answer_question`` so the agent
    loop can call it like any other tool. The agent is free to refine its
    query (e.g. follow up with a narrower question) which is the whole point
    of routing per-issue retrieval through the agent rather than a single
    one-shot RAG call.
    """

    async def fn(args: dict[str, Any]) -> dict[str, Any]:
        result = await answer_question(
            str(args.get("question", "")),
            jurisdictions=[jurisdiction],
            corpus_types=["accounting"],
        )
        return {
            "refused": result.refused,
            "answer": result.answer,
            "citations": _citation_dicts(result.citations),
        }

    return Tool(
        name="kb_search",
        description=(
            f"Search the {jurisdiction} accounting standards corpus and "
            "return a cited summary. Use this to look up the controlling "
            "standard for the topic. You may call it multiple times with "
            "refined questions."
        ),
        parameters={"question": "string"},
        fn=fn,
    )


def _hydrate_query_answer(
    agent_result: Any,
) -> QueryAnswer:
    """Map the agent's final answer + citations back into the QueryAnswer
    shape the orchestrator's downstream code already understands."""
    cites: list[Citation] = []
    for c in agent_result.citations or []:
        if not isinstance(c, dict):
            continue
        cites.append(
            Citation(
                standard=c.get("standard"),
                paragraph=c.get("paragraph"),
                url=c.get("url", ""),
                quote=c.get("quote", ""),
            )
        )
    refused = not (agent_result.final_answer and cites)
    return QueryAnswer(
        answer=agent_result.final_answer or "",
        citations=cites,
        refused=refused,
        language="en",
        retrieved=[],
    )


async def _run_one_agent(topic: str, current_summary: str, jurisdiction: str) -> QueryAnswer:
    """One side of the comparison, driven by the agent loop."""
    question = (
        f"Summarize the {jurisdiction} accounting treatment of: {topic}. "
        f"The taxpayer's current policy states: {current_summary[:600]} "
        f"Quote the controlling standard and identify the recognition / "
        "measurement rules. Use kb_search to look up the relevant standards. "
        "Return your final answer with at least one citation."
    )
    result = await run_agent(
        question,
        tools=[_kb_search_tool(jurisdiction)],
        llm=get_llm(),
        max_steps=_AGENT_MAX_STEPS,
    )
    return _hydrate_query_answer(result)


# Plain-prose summarization when the standards corpus is empty (e.g. the
# free-tier deploy hasn't ingested any sources yet). The agent's normal
# kb_search path always refuses without a corpus, leaving the comparison
# panes empty — the user sees detection + issue identification but no
# US vs IFRS treatment. This fallback uses the model's general knowledge
# to produce a short, marked summary so the side-by-side card is useful.
_SYNTH_PROMPT = """You are a CPA. Summarize how {framework} treats the following accounting topic in 3-5 sentences. Be specific about the controlling standard family (e.g. ASC 606 for US revenue, IFRS 15 for IFRS revenue), the recognition / measurement criteria, and any disclosure highlights.

Topic: {topic}

Context (taxpayer's current policy excerpt):
{current_summary}

Respond with prose only. Do NOT wrap in JSON. Do NOT include citations — your answer will be labeled as model-knowledge synthesis."""


async def _synthesize_treatment(
    topic: str,
    current_summary: str,
    jurisdiction: str,
    llm: LLMClient,
) -> str:
    """Direct LLM call producing a citation-free, marked summary."""
    framework_name = "US GAAP (FASB ASC)" if jurisdiction == "US" else "IFRS / IAS"
    prompt = _SYNTH_PROMPT.format(
        framework=framework_name,
        topic=topic,
        current_summary=current_summary[:600],
    )
    try:
        response = await asyncio.wait_for(llm.complete(prompt), timeout=60.0)
    except Exception as exc:
        logger.warning("synthesis fallback failed for %s/%s: %s", topic, jurisdiction, exc)
        return ""
    text = (response.text or "").strip()
    if not text:
        return ""
    # Mark the synthesis so the frontend can render a "no citations" badge.
    return f"[synthesized from model knowledge — no standards retrieved]\n\n{text}"


async def _one_side(topic: str, current_summary: str, jurisdiction: str) -> QueryAnswer:
    """Agent first, then synthesis fallback on refusal."""
    primary = await _run_one_agent(topic, current_summary, jurisdiction)
    if not primary.refused and primary.answer.strip():
        return primary
    # Corpus empty / agent gave up → fall back to direct LLM synthesis.
    text = await _synthesize_treatment(topic, current_summary, jurisdiction, get_llm())
    if not text:
        return primary  # nothing better to offer
    return QueryAnswer(
        answer=text,
        citations=[],
        refused=False,    # we DO have content, just no cites
        language="en",
        retrieved=[],
    )


async def _compare_one(topic: str, current_summary: str) -> tuple[QueryAnswer, QueryAnswer]:
    """Drive both jurisdictions in parallel via the agent loop, falling back
    to a direct LLM synthesis when the corpus is empty.

    Each side runs the same tool-calling agent with a single tool
    (``kb_search``) scoped to its framework. The agent picks how many
    queries to issue (capped at ``_AGENT_MAX_STEPS``) and returns a final
    cited summary. If both kb_search calls return refusal (typical on
    deploys without an ingested standards corpus), we fall back to an
    explicitly-marked LLM synthesis so the comparison panes are populated.
    """
    return await asyncio.wait_for(
        asyncio.gather(
            _one_side(topic, current_summary, "US"),
            _one_side(topic, current_summary, "IFRS"),
        ),
        timeout=_COMPARE_TIMEOUT_S,
    )


# ── Verifier agent ───────────────────────────────────────────────────────
#
# After each side's summary lands, a separate LLM call inspects it against
# the EXACT verbatim quotes returned by kb_search and produces a short
# narrative judging whether each claim is grounded in a quote, partially
# grounded, or unsupported. This is the layer that catches hallucinated
# claims the cited paragraphs don't actually support — critical when the
# memo will end up in front of a partner.

_VERIFY_PROMPT = """You are a CPA verifier. Read the SUMMARY and the verbatim QUOTES that were retrieved from the {framework} standards corpus. For each substantive claim in the summary, decide whether it is:

  (a) FULLY SUPPORTED by one of the verbatim quotes (state which one),
  (b) PARTIALLY SUPPORTED (the quote is related but doesn't fully establish the claim),
  (c) NOT SUPPORTED (no quote backs the claim — possible hallucination).

Then write a SHORT verification report (3-6 sentences) in plain prose. Start with an overall verdict ('Fully grounded', 'Partially grounded', 'Largely unsupported'), then enumerate any unsupported claims by topic. Do NOT repeat the entire summary. Do NOT add new citations.

If the QUOTES list is empty, respond with exactly: 'No standards quotes were retrieved for this side — verification not possible. Treat the summary as based on the model''s general knowledge only.'

SUMMARY:
{summary}

QUOTES (each line is one verbatim retrieved standards excerpt):
{quotes}
"""

_VERIFY_TIMEOUT_S = 60.0


async def _verify_one_side(
    framework: str,
    summary: str | None,
    citations: list,
    llm: LLMClient,
) -> str | None:
    """Run the verifier agent against a single side's summary + its cited
    quotes. Returns a short prose verification report (3-6 sentences) that
    the orchestrator persists and the PDF/UI surface alongside the summary.

    Returns None when there's nothing to verify (no summary).
    """
    if not summary or not summary.strip():
        return None
    framework_name = "US GAAP (FASB ASC)" if framework == "US" else "IFRS / IAS"
    if not citations:
        # No quotes were retrieved — short-circuit with the canonical no-corpus
        # message rather than burn an LLM call.
        return (
            f"No {framework_name} standards quotes were retrieved for this side "
            "— verification not possible. Treat the summary as based on the "
            "model's general knowledge only."
        )
    quote_lines: list[str] = []
    for c in citations:
        std = c.get("standard") if isinstance(c, dict) else getattr(c, "standard", None)
        quote = c.get("quote") if isinstance(c, dict) else getattr(c, "quote", "")
        if not quote:
            continue
        std_label = std or "(no standard)"
        quote_lines.append(f"- [{std_label}] {quote}")
    if not quote_lines:
        return (
            f"Citations were returned for {framework_name} but every quote was "
            "empty — verification not possible against empty source text."
        )
    prompt = _VERIFY_PROMPT.format(
        framework=framework_name,
        summary=summary,
        quotes="\n".join(quote_lines),
    )
    try:
        response = await asyncio.wait_for(llm.complete(prompt), timeout=_VERIFY_TIMEOUT_S)
    except Exception as exc:
        logger.warning("verifier agent failed for %s: %r", framework, exc)
        return f"(verifier agent failed: {exc})"
    text = (response.text or "").strip()
    return text or None


async def _verify_both_sides(
    topic: str,
    gaap_summary: str | None,
    gaap_citations: list,
    ifrs_summary: str | None,
    ifrs_citations: list,
) -> tuple[str | None, str | None]:
    """Run the verifier in parallel for both sides — one LLM call per side."""
    llm = get_llm()
    return await asyncio.gather(
        _verify_one_side("US", gaap_summary, gaap_citations, llm),
        _verify_one_side("IFRS", ifrs_summary, ifrs_citations, llm),
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

            gaap_summary = gaap_ans.answer if gaap_ans and not gaap_ans.refused else None
            ifrs_summary = ifrs_ans.answer if ifrs_ans and not ifrs_ans.refused else None
            gaap_cites = _citation_dicts(gaap_ans.citations) if gaap_ans else []
            ifrs_cites = _citation_dicts(ifrs_ans.citations) if ifrs_ans else []

            # Verifier agent — judges whether each side's summary is grounded
            # in the verbatim quotes the retrieval returned. Runs both sides
            # in parallel; failures degrade to a "(verifier failed)" string
            # rather than break the orchestrator.
            try:
                gaap_verif, ifrs_verif = await _verify_both_sides(
                    topic, gaap_summary, gaap_cites, ifrs_summary, ifrs_cites,
                )
            except Exception as exc:
                logger.warning("verifier agent crashed for topic %r: %s", topic, exc)
                gaap_verif = ifrs_verif = None

            row = ComparisonIssue(
                run_id=run.id,
                seq=seq,
                topic=topic,
                current_summary=current_summary,
                current_user_cites=user_cites,
                gaap_summary=gaap_summary,
                gaap_citations=gaap_cites,
                ifrs_summary=ifrs_summary,
                ifrs_citations=ifrs_cites,
                differences=_derive_differences(gaap_ans, ifrs_ans),
                conversion_impact=conversion_impact,
                gaap_verification=gaap_verif,
                ifrs_verification=ifrs_verif,
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
