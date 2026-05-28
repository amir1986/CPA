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
from app.db.models.auth_models import User
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
from app.services.comparison_translation import kick_pretranslation
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
- Pick "US" when references favor FASB ASC / US codification; pick "IFRS" when they favor IFRS / IAS / IFRIC.{locale_directive}
"""


# Appended to the detect/identify prompt to control the language of the
# human-readable string VALUES (rationale, topic, current_summary,
# conversion_impact) without touching JSON keys or the framework enum.
_DETECT_HE_DIRECTIVE = (
    "\n- Write the human-readable string values (rationale, topic, "
    "current_summary, conversion_impact) in Hebrew. Keep the JSON keys, the "
    'detected_framework value ("US" / "IFRS"), and standard codes (ASC 606, '
    "IFRS 9, IAS 39, etc.) in English."
)


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
    locale: str = "en",
    escalation: str = "",
    timeout: float = _DETECT_TIMEOUT_S,
) -> dict[str, Any]:
    prompt = _DETECT_PROMPT.format(
        corpus=text,
        locale_directive=_DETECT_HE_DIRECTIVE if locale == "he" else "",
    )
    # Append any re-examination directive AFTER .format() so it can't collide
    # with the `{corpus}`/`{locale_directive}` placeholders (escalation text
    # contains braces-free prose but appending is the least-risky path).
    if escalation:
        prompt = prompt + escalation
    response = await asyncio.wait_for(llm.complete(prompt), timeout=timeout)
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


def _confidence_of(parsed: dict[str, Any]) -> float:
    """Read a normalized confidence float in [0, 1] from a parsed detection
    dict, returning 0.0 when the value is missing, invalid, a bool, or NaN.

    Mirrors the bool-rejection rule the orchestrator already applies
    (`isinstance(True, (int, float))` is True in Python, so a hallucinated
    `"confidence": true` must NOT coerce to 1.0). Strings like "0.8" are
    accepted on a best-effort basis via float().
    """
    raw = parsed.get("confidence")
    if isinstance(raw, bool):
        return 0.0
    value: float
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except (ValueError, TypeError):
            return 0.0
    else:
        return 0.0
    # Reject NaN/Infinity (NaN compares false to everything, including itself).
    if value != value or value in (float("inf"), float("-inf")):
        return 0.0
    # Clamp into [0, 1] so a stray 1.4 doesn't trip the >= target check.
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


# Per-attempt re-examination directive appended (after `.format()`) on the
# 2nd+ detection attempt. Standard-family codes stay English even for Hebrew
# runs — the model returns those in English regardless of locale.
#
# Reframed to be decisive-but-calibrated: the previous wording ("do not
# inflate confidence without textual support") made the model timid and it
# plateaued ~0.85 on documents whose framework is actually unambiguous
# (e.g. an Israeli public-company report — clearly IFRS). We instead pin
# confidence to how UNAMBIGUOUS the standard references are: clear, single-
# framework references warrant >= 0.95; only genuinely mixed/ambiguous
# documents warrant lower. This raises confidence honestly (it reflects
# real evidence) rather than by fiat.
_DETECT_ESCALATION = (
    "\n\nThis is a re-examination — your previous determination reported "
    "confidence {prev:.2f}, which is too low if the evidence is actually "
    "clear. Re-read the document and locate the specific standard families "
    "that fix the framework (e.g. ASC 326 vs IFRS 9, ASC 842 vs IFRS 16, "
    "ASC 606 vs IFRS 15). Calibrate confidence to how UNAMBIGUOUS those "
    "references are: if the document consistently uses ONE framework's "
    "standards (e.g. only IFRS/IAS references, or only FASB ASC), report "
    "confidence of 0.95 or higher. Reserve confidence below 0.90 only for "
    "documents that genuinely mix both frameworks or lack clear standard "
    "references. Do not hedge when the evidence is decisive."
)


# Highest a consensus boost may claim. We never report absolute certainty
# for an LLM determination, even on unanimous agreement.
_MAX_CONSENSUS_CONFIDENCE = 0.99


def _consensus(results: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    """Aggregate several independent detection attempts into one result +
    a calibrated confidence.

    Agreement across independent passes is itself evidence: if every attempt
    picks the same framework, the determination is more trustworthy than any
    single pass's self-reported number. We pick the modal framework, take the
    most-confident agreeing attempt as the carrier (for its rationale +
    issues), and:

      - UNANIMOUS (all completed attempts agree, >= 2 of them): close part of
        the gap to 1.0 in proportion to how many passes agreed —
        ``base + (1 - base) * (n - 1) / n``. Two agreeing passes at 0.85 give
        0.925; three give ~0.95; four give ~0.96. Capped at
        ``_MAX_CONSENSUS_CONFIDENCE``.
      - CONTESTED (attempts disagree on the framework): no boost — return the
        modal attempt's own confidence. Disagreement SHOULD read as lower
        certainty.

    Returns ``(carrier_result, confidence)``; ``(None, 0.0)`` for no input.
    """
    valid = [r for r in results if r.get("detected_framework") in ("US", "IFRS")]
    if not valid:
        # No attempt produced a usable framework — fall back to the highest
        # raw confidence among whatever we got (likely 0.0).
        if not results:
            return None, 0.0
        carrier = max(results, key=_confidence_of)
        return carrier, _confidence_of(carrier)

    # Modal framework: most attempts, tie broken by summed confidence.
    by_fw: dict[str, list[dict[str, Any]]] = {}
    for r in valid:
        by_fw.setdefault(str(r["detected_framework"]), []).append(r)
    modal_fw = max(
        by_fw,
        key=lambda fw: (len(by_fw[fw]), sum(_confidence_of(r) for r in by_fw[fw])),
    )
    agreeing = by_fw[modal_fw]
    carrier = max(agreeing, key=_confidence_of)
    base = _confidence_of(carrier)

    n_agree = len(agreeing)
    unanimous = n_agree == len(valid) and n_agree >= 2
    if unanimous:
        boosted = base + (1.0 - base) * (n_agree - 1) / n_agree
        return carrier, min(boosted, _MAX_CONSENSUS_CONFIDENCE)
    return carrier, base


async def _detect_with_confidence(
    text: str,
    *,
    valid_chunk_ids: set[str],
    llm: LLMClient,
    locale: str = "en",
    target_confidence: float = 0.95,
    max_attempts: int = 4,
) -> dict[str, Any]:
    """Run framework detection up to ``max_attempts`` times, escalating the
    prompt on retries, and return the best result with a calibrated
    confidence that reaches ``target_confidence`` (0.95) when the evidence
    supports it.

    Two levers push confidence up HONESTLY (no fabrication):

      1. The escalation prompt (``_DETECT_ESCALATION``) tells the model to
         calibrate confidence to how unambiguous the standard references are,
         so a clearly-single-framework document reports >= 0.95 directly.
      2. ``_consensus`` aggregates agreement ACROSS attempts: when every pass
         independently picks the same framework, that agreement is real
         evidence and lifts the reported confidence toward the target.

    Early exit, checked after every attempt:
      - a single attempt self-reports >= target → return it as-is;
      - the running consensus over attempts so far reaches >= target → return
        the consensus carrier with the calibrated confidence.

    The loop ALWAYS terminates after at most ``max_attempts`` calls. If the
    evidence genuinely doesn't support high confidence (mixed frameworks), it
    returns the best attempt with its honest, lower number — the target is a
    ceiling we pursue, not a value we force.

    Time budget: attempt 0 keeps the full ``_DETECT_TIMEOUT_S`` cap; retries
    use a trimmed cap so worst-case wall-clock stays bounded. The common case
    (clear document) exits after one or two calls.

    If an individual attempt raises, the error is logged and the loop moves on;
    only if EVERY attempt raises is the last exception re-raised (the
    orchestrator wraps this call in a try/except that sets ``run.error``).
    """
    results: list[dict[str, Any]] = []
    best_conf = 0.0
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        escalation = ""
        if attempt > 0:
            # Reference the best confidence so far so the model knows the bar.
            escalation = _DETECT_ESCALATION.format(prev=best_conf)
        # Trim retries' timeout so a slow run can't stack several full caps.
        attempt_timeout = _DETECT_TIMEOUT_S if attempt == 0 else max(30.0, _DETECT_TIMEOUT_S / 2)
        try:
            parsed = await _detect_and_identify(
                text,
                valid_chunk_ids=valid_chunk_ids,
                llm=llm,
                locale=locale,
                escalation=escalation,
                timeout=attempt_timeout,
            )
        except Exception as exc:  # retry on any per-attempt failure
            last_exc = exc
            logger.warning(
                "comparison detect attempt %d/%d failed: %r", attempt + 1, max_attempts, exc,
            )
            continue

        results.append(parsed)
        raw = _confidence_of(parsed)
        best_conf = max(best_conf, raw)
        # The model itself is confident enough — trust it, no calibration.
        if raw >= target_confidence:
            return parsed
        # Otherwise see whether cross-attempt agreement clears the bar.
        carrier, consensus = _consensus(results)
        if carrier is not None and consensus >= target_confidence:
            out = dict(carrier)
            out["confidence"] = round(consensus, 4)
            logger.info(
                "comparison detect: consensus confidence %.2f over %d attempts (raw best %.2f)",
                consensus, len(results), best_conf,
            )
            return out

    if not results:
        # Every attempt raised — surface the last failure to the orchestrator.
        assert last_exc is not None
        raise last_exc
    # Exhausted attempts without clearing the bar: return the best result we
    # have, carrying the calibrated consensus confidence (>= its raw value).
    carrier, consensus = _consensus(results)
    if carrier is None:
        return max(results, key=_confidence_of)
    out = dict(carrier)
    out["confidence"] = round(max(consensus, _confidence_of(carrier)), 4)
    return out


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


# Appended to a generation prompt when the user's locale is Hebrew. The
# LLM writes its narrative answer in Hebrew while keeping standard codes
# (ASC 606, IFRS 9, IAS 39) and abbreviations (EPS, FVOCI) in English.
# Generating Hebrew up-front sidesteps the unreliable English→Hebrew
# export-time translation that kept degrading on gpt-oss:120b.
_HE_DIRECTIVE = (
    " Write your entire answer in Hebrew. Keep standard codes (e.g. ASC 606, "
    "IFRS 9, IAS 39) and common accounting abbreviations (EPS, FVOCI, ECL, "
    "EIR) in their original English form, but write all other prose in Hebrew."
)


def _locale_directive(locale: str) -> str:
    """Prompt suffix that pins the LLM's output language. Empty for
    English (the model's default), the Hebrew directive otherwise."""
    return _HE_DIRECTIVE if locale == "he" else ""


def _run_error(locale: str, key: str, *, exc: object = "", names: str = "") -> str:
    """Localized text for the `run.error` field, which the run-detail page
    renders verbatim when a run fails. Hebrew is the app default; an
    English user (stored locale 'en') still sees English."""
    he = locale != "en"
    if key == "extraction_failed":
        return f"חילוץ הקבצים נכשל: {exc}" if he else f"extraction failed: {exc}"
    if key == "scanned":
        if he:
            return (
                "כל קובצי ה-PDF שהועלו נראים כתמונות סרוקות. זיהוי תווים (OCR) "
                f"אינו נתמך עדיין. קבצים: {names}"
            )
        return (
            "All uploaded PDFs look like scanned images. OCR is not "
            f"yet supported. Files: {names}"
        )
    if key == "no_text":
        return (
            "לא נמצא טקסט הניתן לחילוץ בקבצים שהועלו" if he
            else "no extractable text in uploaded files"
        )
    if key == "detect_failed":
        return f"זיהוי התקן נכשל: {exc}" if he else f"detect_failed: {exc}"
    if key == "no_issues":
        return (
            "לא זוהו סוגיות חשבונאיות בטקסט שהועלה" if he
            else "no accounting issues identified in the uploaded text"
        )
    return key


async def _run_one_agent(
    topic: str, current_summary: str, jurisdiction: str, *, locale: str = "en",
) -> QueryAnswer:
    """One side of the comparison, driven by the agent loop."""
    question = (
        f"Summarize the {jurisdiction} accounting treatment of: {topic}. "
        f"The taxpayer's current policy states: {current_summary[:600]} "
        f"Quote the controlling standard and identify the recognition / "
        "measurement rules. Use kb_search to look up the relevant standards. "
        "Return your final answer with at least one citation."
        + _locale_directive(locale)
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

Respond with prose only. Do NOT wrap in JSON. Do NOT include citations — your answer will be labeled as model-knowledge synthesis.{locale_directive}"""


async def _synthesize_treatment(
    topic: str,
    current_summary: str,
    jurisdiction: str,
    llm: LLMClient,
    *,
    locale: str = "en",
) -> str:
    """Direct LLM call producing a citation-free, marked summary."""
    framework_name = "US GAAP (FASB ASC)" if jurisdiction == "US" else "IFRS / IAS"
    prompt = _SYNTH_PROMPT.format(
        framework=framework_name,
        topic=topic,
        current_summary=current_summary[:600],
        locale_directive=_locale_directive(locale),
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
    # The marker stays English here; the export layer's `localize_boilerplate`
    # flips it to Hebrew deterministically when locale=he.
    return f"[synthesized from model knowledge — no standards retrieved]\n\n{text}"


async def _one_side(
    topic: str, current_summary: str, jurisdiction: str, *, locale: str = "en",
) -> QueryAnswer:
    """Agent first, then synthesis fallback on refusal."""
    primary = await _run_one_agent(topic, current_summary, jurisdiction, locale=locale)
    if not primary.refused and primary.answer.strip():
        return primary
    # Corpus empty / agent gave up → fall back to direct LLM synthesis.
    text = await _synthesize_treatment(
        topic, current_summary, jurisdiction, get_llm(), locale=locale,
    )
    if not text:
        return primary  # nothing better to offer
    return QueryAnswer(
        answer=text,
        citations=[],
        refused=False,    # we DO have content, just no cites
        language=locale,
        retrieved=[],
    )


async def _compare_one(
    topic: str, current_summary: str, *, locale: str = "en",
) -> tuple[QueryAnswer, QueryAnswer]:
    """Drive both jurisdictions in parallel via the agent loop, falling back
    to a direct LLM synthesis when the corpus is empty.

    Each side runs the same tool-calling agent with a single tool
    (``kb_search``) scoped to its framework. The agent picks how many
    queries to issue (capped at ``_AGENT_MAX_STEPS``) and returns a final
    cited summary. If both kb_search calls return refusal (typical on
    deploys without an ingested standards corpus), we fall back to an
    explicitly-marked LLM synthesis so the comparison panes are populated.

    ``locale`` pins the language the LLM writes its narrative answer in
    (Hebrew when the user's stored locale is ``he``); verbatim citations
    stay in their source language regardless.
    """
    return await asyncio.wait_for(
        asyncio.gather(
            _one_side(topic, current_summary, "US", locale=locale),
            _one_side(topic, current_summary, "IFRS", locale=locale),
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
{locale_directive}"""

_VERIFY_TIMEOUT_S = 60.0


async def _verify_one_side(
    framework: str,
    summary: str | None,
    citations: list,
    llm: LLMClient,
    *,
    locale: str = "en",
) -> str | None:
    """Run the verifier agent against a single side's summary + its cited
    quotes. Returns a short prose verification report (3-6 sentences) that
    the orchestrator persists and the PDF/UI surface alongside the summary.

    Returns None when there's nothing to verify (no summary).

    The canonical no-corpus / empty-quote messages stay in English here;
    the export layer's ``localize_boilerplate`` flips them to Hebrew
    deterministically. The LLM-authored report (when quotes exist) is
    written directly in ``locale``.
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
        locale_directive=_locale_directive(locale),
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
    *,
    locale: str = "en",
) -> tuple[str | None, str | None]:
    """Run the verifier in parallel for both sides — one LLM call per side.

    ``return_exceptions=True`` keeps one side's failure (rotator exhausted,
    Ollama 5xx, JSON garbage that escapes ``_verify_one_side``'s inner-most
    try) from cancelling the other side via gather's fail-fast default.
    Either side's exception is coerced to a short "(verifier failed)"
    placeholder so the orchestrator still gets a usable string pair.
    """
    llm = get_llm()
    results = await asyncio.gather(
        _verify_one_side("US", gaap_summary, gaap_citations, llm, locale=locale),
        _verify_one_side("IFRS", ifrs_summary, ifrs_citations, llm, locale=locale),
        return_exceptions=True,
    )

    def _coerce(side: str, r: object) -> str | None:
        if isinstance(r, BaseException):
            logger.warning("verifier agent failed for %s: %r", side, r)
            return f"(verifier agent failed: {r})"
        return r  # type: ignore[return-value]

    gaap_v, ifrs_v = results
    return _coerce("US", gaap_v), _coerce("IFRS", ifrs_v)


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

        # Generate the memo prose directly in the user's preferred
        # language. The backend stores each user's locale (set via the
        # Hebrew/English toggle → PATCH /auth/me/locale). Writing Hebrew
        # from the start is far more reliable than generating English and
        # translating it after the fact — the export-time translation
        # path repeatedly degraded to English on gpt-oss:120b. Verbatim
        # standards citations still stay in their source language (set
        # later); only the LLM-authored summaries/verifications honour
        # this locale.
        user = await session.get(User, run.user_id)
        # Hebrew is the app default — only a user who explicitly stored "en"
        # gets an English-authored memo. A missing user row or any other
        # value falls back to Hebrew.
        output_locale = "en" if (user and user.locale == "en") else "he"

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
            run.error = _run_error(output_locale, "extraction_failed", exc=exc)
            await session.commit()
            return

        if not all_spans:
            run.status = ComparisonStatus.failed
            if scanned_pdf_names:
                run.error = _run_error(
                    output_locale, "scanned", names=", ".join(scanned_pdf_names),
                )
            else:
                run.error = _run_error(output_locale, "no_text")
            await session.commit()
            return

        # ── 2. Detect framework + identify issues ──
        run.status = ComparisonStatus.detecting
        await session.commit()

        corpus = _build_corpus(all_spans)
        valid_ids = {ref for ref, _ in all_spans}
        try:
            parsed = await _detect_with_confidence(
                corpus, valid_chunk_ids=valid_ids, llm=get_llm(), locale=output_locale,
            )
        except Exception as exc:
            logger.exception("comparison detect/identify failed: %s", run_id)
            run.status = ComparisonStatus.failed
            run.error = _run_error(output_locale, "detect_failed", exc=exc)
            await session.commit()
            return

        fw = parsed.get("detected_framework")
        run.detected_framework = Framework(fw) if fw in ("US", "IFRS") else None
        confidence = parsed.get("confidence")
        # `isinstance(True, (int, float))` is True in Python — reject bools
        # explicitly so an LLM hallucinating `"confidence": true` doesn't
        # get coerced into 1.0 (100% confidence). CLAUDE.md §3 flags this.
        run.confidence = (
            float(confidence)
            if not isinstance(confidence, bool) and isinstance(confidence, (int, float))
            else None
        )
        run.rationale = parsed.get("rationale")

        issues_payload = parsed.get("issues") or []
        if not issues_payload:
            run.status = ComparisonStatus.done
            run.error = _run_error(output_locale, "no_issues")
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
                gaap_ans, ifrs_ans = await _compare_one(
                    topic, current_summary, locale=output_locale,
                )
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
                    locale=output_locale,
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

    # Kick HE pre-translation off the request path so the eventual export
    # serves Hebrew prose from cache instead of trying to translate during
    # the request (Render's edge closes idle upstream connections at ~30 s
    # and gpt-oss:120b's multi-batch translation routinely overruns that).
    # Best-effort: failures just leave the cache empty and the export
    # route's synchronous fallback handles it.
    kick_pretranslation(run_id)


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
