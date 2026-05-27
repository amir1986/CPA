"""Hebrew translation for the USGAAP <> IFRS comparison memo.

The memo's chrome (section headings, labels) is always rendered from the
static `_MEMO_STRINGS` dict in `app/api/routes/comparisons.py` — those
strings are baked in and don't need an LLM. What does need translation is
the LLM-generated prose: per-issue summaries, verifier output, the
difference paragraph, the conversion-impact paragraph, and the run-level
rationale.

We translate via `gpt-oss:120b` over Ollama Cloud, batched and run in
parallel so a multi-issue memo finishes in a handful of seconds rather
than minute-plus serial. Two callers:

- ``pretranslate_run_to_hebrew`` — fires from the orchestrator the moment
  a run flips to ``done``. Stores the resulting Hebrew strings on
  ``ComparisonRun.translations_he`` so the eventual export request can
  read from cache (instant, no LLM call). Generous timeouts (no Render
  edge in this code path — it's a background task on the same worker).

- The export route — when ``translations_he`` is empty (user exported
  before pre-translation finished, or pre-translation failed), the
  synchronous helpers below are used as a fallback with a tight wall-clock
  cap so the response doesn't 500 on Render's ~30 s edge idle timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.models.comparison_models import (
    ComparisonIssue,
    ComparisonRun,
    ComparisonStatus,
)
from app.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

# Prose fields on a ComparisonIssue that get LLM-translated for HE exports.
# Verbatim quote lists (`*_citations`, `current_user_cites`) are excluded —
# they stay in their source language for citation integrity.
PROSE_KEYS: tuple[str, ...] = (
    "current_summary",
    "gaap_summary",
    "ifrs_summary",
    "differences",
    "conversion_impact",
    "gaap_verification",
    "ifrs_verification",
)


_TRANSLATE_PROMPT = """You are translating an accounting memo from English into Hebrew for a CPA partner. Translate accurately and naturally; preserve technical accounting terms (e.g. ASC 606, IFRS 15, EPS, deferred tax) but use Hebrew for everything else.

Translate the ENTIRE value for every key — including any bracketed markers like "[...]", parenthetical notes, and short fragments. Do NOT leave bracketed text in English: it is descriptive prose, not code. The only English you keep is technical accounting terms and standard names (ASC nnn, IFRS nn, IAS nn, EPS, FVOCI, etc.).

Return STRICT JSON with the SAME keys as the input, each value translated. Do not add or drop keys. Do not include any prose outside the JSON.

INPUT:
{input_json}
"""


async def _translate_to_hebrew(
    items: dict[str, str], *, per_batch_timeout: float = 18.0,
) -> dict[str, str]:
    """Batched LLM translation of memo prose fields. Empty / None values
    short-circuit so the LLM only sees real text. On any failure we
    return the original English so the export still completes."""
    nonempty = {k: v for k, v in items.items() if v and v.strip()}
    if not nonempty:
        return items
    try:
        from app.llm.client import get_llm
        prompt = _TRANSLATE_PROMPT.format(input_json=json.dumps(nonempty, ensure_ascii=False))
        response = await asyncio.wait_for(get_llm().complete(prompt), timeout=per_batch_timeout)
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json\n"):
                text = text[5:]
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        translated = json.loads(text)
        # Merge with the original so empty values stay empty. Skip empty /
        # whitespace-only translations — an LLM returning `""` for a field
        # would otherwise wipe the English source and downstream truthy
        # checks (`prose.get(key) or s["no_…_retrieved"]`) flip the memo to
        # the "no retrieval" placeholder for a field we actually had.
        out = dict(items)
        for k, v in translated.items():
            if isinstance(v, str) and v.strip() and k in out:
                out[k] = v
        return out
    except Exception as exc:
        logger.warning("memo translation failed (returning English): %r", exc)
        return items


async def _translate_batches_parallel(
    flat: dict[str, str],
    batch_size: int = 4,
    *,
    per_batch_timeout: float = 18.0,
) -> dict[str, str]:
    """Split a flat dict of strings into small batches and translate them
    in parallel. Smaller batches finish faster on Ollama Cloud and let
    `KeyRotator` spread load across multiple API keys — a single fat
    batch was timing out at the edge proxy before the model returned.

    Translation failures degrade per-batch: failed batches keep their
    English values and the rest of the memo still ships in Hebrew.

    ``return_exceptions=True`` keeps one batch's failure (rotator
    exhausted, httpx connection broken mid-flight, JSON garbage that
    escapes the inner-most try) from cancelling the rest of the gather.
    """
    if not flat:
        return flat
    items = list(flat.items())
    batches: list[dict[str, str]] = [
        dict(items[i : i + batch_size]) for i in range(0, len(items), batch_size)
    ]
    results = await asyncio.gather(
        *[_translate_to_hebrew(b, per_batch_timeout=per_batch_timeout) for b in batches],
        return_exceptions=True,
    )
    out: dict[str, str] = dict(flat)
    for batch, batch_out in zip(batches, results, strict=True):
        if isinstance(batch_out, BaseException):
            logger.warning("translation batch failed (keeping English): %r", batch_out)
            continue
        for k, v in batch_out.items():
            out[k] = v
    return out


def _flatten_for_translation(
    rationale: str | None, issues: list[ComparisonIssue]
) -> dict[str, str]:
    """Collect every non-empty prose field into a single flat dict, keyed
    so the export route can look the translation back up.

    `_run.rationale` is special-cased; per-issue fields are keyed as
    ``<issue_id>.<prose_field>``.
    """
    flat: dict[str, str] = {}
    if rationale and rationale.strip():
        flat["_run.rationale"] = rationale
    for i in issues:
        for k in PROSE_KEYS:
            v = getattr(i, k, None)
            if v and v.strip():
                flat[f"{i.id}.{k}"] = v
    return flat


# Strong refs so the GC can't reap in-flight pre-translation tasks while
# they're still doing work — mirrors `_BACKGROUND_TASKS` in the routes
# module (see CLAUDE.md §3 on the create_task GC footgun).
_PRETRANSLATION_TASKS: set[asyncio.Task[None]] = set()


def kick_pretranslation(run_id: uuid.UUID) -> None:
    """Schedule `pretranslate_run_to_hebrew(run_id)` in the background and
    keep a strong reference until it finishes. Safe to call multiple times
    — the inner function checks the cache and short-circuits if Hebrew is
    already cached for the run."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside an event loop (e.g. from a sync context in a
        # test). Translation cache stays empty; the export route's
        # synchronous fallback will run instead.
        logger.debug("kick_pretranslation called without a running loop; skipping")
        return
    task = loop.create_task(pretranslate_run_to_hebrew(run_id))
    _PRETRANSLATION_TASKS.add(task)
    task.add_done_callback(_PRETRANSLATION_TASKS.discard)


async def pretranslate_run_to_hebrew(run_id: uuid.UUID) -> None:
    """Translate every prose field of a completed run to Hebrew and persist
    the result on ``ComparisonRun.translations_he``.

    Runs as a background task off the request path, so there's no wall-
    clock cap protecting against Render's ~30 s edge timeout. The per-
    batch LLM timeout is the only bound — slow but eventually-successful
    translations are exactly the case we want to capture here.

    Idempotent: short-circuits if the cache is already populated. Failures
    are logged and the cache is left empty; the export route's synchronous
    fallback will then translate on-demand under its tight wall-clock cap.
    """
    try:
        factory = get_sessionmaker()
        async with factory() as session:
            run = await session.get(ComparisonRun, run_id)
            if run is None:
                logger.warning("pretranslate: run %s vanished before task ran", run_id)
                return
            if run.status != ComparisonStatus.done:
                # Don't pre-translate a failed or in-flight run.
                return
            if run.translations_he:
                # Already cached (likely a retry).
                return

            issues = list(
                (
                    await session.scalars(
                        select(ComparisonIssue)
                        .where(ComparisonIssue.run_id == run_id)
                        .order_by(ComparisonIssue.seq)
                    )
                ).all()
            )
            flat = _flatten_for_translation(run.rationale, issues)
            if not flat:
                return

            # Wider per-batch timeout than the request-path fallback —
            # 60 s comfortably covers gpt-oss:120b's worst-case latency
            # on a cold Ollama Cloud key without risking an edge timeout
            # (there's no client connection open here).
            translated = await _translate_batches_parallel(
                flat, batch_size=4, per_batch_timeout=60.0,
            )

            # Only persist keys whose translation actually changed —
            # identity-mapped values mean the batch failed and degraded
            # to English; we want the export route to try again on the
            # request path rather than serve a half-Hebrew memo from
            # cache forever.
            #
            # Also run `localize_boilerplate` on each translated value
            # so any canned English fragment the LLM left intact (the
            # synthesis marker, the verifier no-corpus sentence) gets
            # flipped to Hebrew before we persist. Without this, a
            # partially-translated value lands in the cache, the export
            # path serves it from cache (skipping the sync fallback),
            # and the user sees English fragments inside a Hebrew memo.
            real: dict[str, str] = {}
            for k, v in translated.items():
                src = flat.get(k)
                if v and isinstance(v, str) and v != src:
                    real[k] = localize_boilerplate(v, "he") or v
            if not real:
                logger.warning(
                    "pretranslate: no fields translated for run %s "
                    "(all batches degraded to English)",
                    run_id,
                )
                return

            run.translations_he = real
            # JSONB columns aren't auto-dirtied on in-place mutations;
            # explicit flag covers the case where SQLAlchemy's change
            # detector misses the reassignment via attribute set.
            flag_modified(run, "translations_he")
            await session.commit()
            logger.info(
                "pretranslate: cached %d/%d HE translations for run %s",
                len(real), len(flat), run_id,
            )
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit):
        raise
    except BaseException as exc:
        logger.warning("pretranslate failed for run %s: %r", run_id, exc)


def translations_cover(
    cache: Mapping[str, str] | None, flat: Mapping[str, str]
) -> bool:
    """True when the cached translations cover every key in `flat`. Used
    by the export route to decide whether the cache is good enough to
    skip the synchronous fallback entirely."""
    if not cache:
        return False
    return all(k in cache for k in flat)


# ─────────────── Boilerplate localization ───────────────
#
# The orchestrator emits a small set of canned English phrases that get
# stored directly on the issue rows as part of the prose fields:
#
#   - synthesis marker:        gaap_summary, ifrs_summary
#   - verifier no-corpus:      gaap_verification, ifrs_verification
#   - verifier empty quotes:   gaap_verification, ifrs_verification
#   - verifier crash:          gaap_verification, ifrs_verification
#   - derived differences:     differences
#
# LLM translation tends to either preserve bracketed markers in their
# source language (treating them as code-like literals) or to drop the
# whole field on a parse error / timeout. Either way, the user ends up
# with English fragments inside what's supposed to be a fully-Hebrew
# memo — which is exactly the bug the screenshot ticket reported.
#
# These maps localize the canned phrases deterministically — no LLM call,
# no failure mode. Applied AFTER LLM translation so any successful
# translation wins; canned phrases the LLM left untranslated still get
# flipped to Hebrew. Idempotent (no English substrings inside the Hebrew
# translations, so a second pass is a no-op).

_HE_BOILERPLATE_MAP: dict[str, str] = {
    # Synthesis marker — literal prefix on gaap_summary / ifrs_summary
    # when the agent refuses and the synthesis-fallback path runs.
    "[synthesized from model knowledge — no standards retrieved]":
        "[סונתז מידע מהמודל — לא אותרו תקנים]",

    # Verifier no-corpus canned (per framework).
    "No US GAAP (FASB ASC) standards quotes were retrieved for this side "
    "— verification not possible. Treat the summary as based on the "
    "model's general knowledge only.":
        "לא אותרו ציטוטי תקני US GAAP (FASB ASC) עבור צד זה — לא ניתן לבצע "
        "אימות. יש להתייחס לסיכום כאל מבוסס על ידע כללי של המודל בלבד.",

    "No IFRS / IAS standards quotes were retrieved for this side "
    "— verification not possible. Treat the summary as based on the "
    "model's general knowledge only.":
        "לא אותרו ציטוטי תקני IFRS / IAS עבור צד זה — לא ניתן לבצע אימות. "
        "יש להתייחס לסיכום כאל מבוסס על ידע כללי של המודל בלבד.",

    # Verifier empty-quotes canned.
    "Citations were returned for US GAAP (FASB ASC) but every quote was "
    "empty — verification not possible against empty source text.":
        "התקבלו ציטוטים עבור US GAAP (FASB ASC) אך כל ציטוט היה ריק — "
        "לא ניתן לבצע אימות מול טקסט מקור ריק.",

    "Citations were returned for IFRS / IAS but every quote was "
    "empty — verification not possible against empty source text.":
        "התקבלו ציטוטים עבור IFRS / IAS אך כל ציטוט היה ריק — "
        "לא ניתן לבצע אימות מול טקסט מקור ריק.",

    # Derived differences canned (three shapes from _derive_differences).
    "Compare the two summaries above. The US GAAP excerpts emphasize the "
    "FASB ASC measurement rules; the IFRS excerpts apply the IASB "
    "principles-based approach. See the side-by-side citations for the "
    "controlling paragraphs.":
        "השוו בין שני הסיכומים שלמעלה. הקטעים של US GAAP מדגישים את כללי "
        "המדידה של FASB ASC; הקטעים של IFRS מיישמים את הגישה מבוססת-"
        "העקרונות של IASB. ראו את הציטוטים צד-לצד עבור הפסקאות הקובעות.",

    "Only US GAAP standards were retrieved; IFRS standards corpus may "
    "not be loaded.":
        "אותרו רק תקני US GAAP; ייתכן שמאגר תקני IFRS לא נטען.",

    "Only IFRS standards were retrieved; US GAAP corpus may not be loaded.":
        "אותרו רק תקני IFRS; ייתכן שמאגר US GAAP לא נטען.",
}


# Sorted by length descending so a longer pattern (e.g. the full
# verifier-no-corpus sentence) is matched before any short substring
# that might appear inside it. Exact-match `str.replace` is fine here —
# none of the keys overlap once sorted longest-first.
_HE_BOILERPLATE_PAIRS: list[tuple[str, str]] = sorted(
    _HE_BOILERPLATE_MAP.items(), key=lambda kv: -len(kv[0])
)


def localize_boilerplate(text: str | None, locale: str) -> str | None:
    """Replace orchestrator-emitted English boilerplate fragments with
    Hebrew equivalents. Returns the input unchanged for non-Hebrew
    locales or when no fragment matches.

    Designed to run *after* the LLM translation step so successful
    translations are preserved. The boilerplate fragments are exact
    English strings — if the LLM already translated them, the substring
    no longer matches and this call is a no-op.

    Also handles the dynamic ``(verifier agent failed: <exc>)`` prefix
    so that error report keeps a Hebrew framing even when the embedded
    exception string is opaque.
    """
    if not text or locale != "he":
        return text
    out = text
    for en, he in _HE_BOILERPLATE_PAIRS:
        if en in out:
            out = out.replace(en, he)
    # Dynamic verifier-failure prefix — has a runtime exception repr
    # appended that we can't predict, so we just swap the leading framing.
    if "(verifier agent failed:" in out:
        out = out.replace("(verifier agent failed:", "(סוכן האימות נכשל:")
    return out
