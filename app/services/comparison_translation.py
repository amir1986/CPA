"""Hebrew translation for the USGAAP <> IFRS comparison memo.

The memo's chrome (section headings, labels) is always rendered from the
static `_MEMO_STRINGS` dict in `app/api/routes/comparisons.py` — those
strings are baked in and don't need an LLM. What does need translation is
the LLM-generated prose: per-issue summaries, verifier output, the
difference paragraph, the conversion-impact paragraph, and the run-level
rationale.

We translate via `gpt-oss:120b` over Ollama Cloud. Translation runs
per-field rather than as a single batched-JSON call: the batched-JSON
approach reliably returned the input unchanged for ~half the fields in
production (gpt-oss:120b treated the multi-key JSON as "preserve
structure" and skipped the actual translation step on most values). The
per-field flow uses a direct "translate this English to Hebrew" prompt,
parallelizes across all fields via `asyncio.gather`, and rejects any
response that doesn't actually contain Hebrew characters.

Two callers:

- ``pretranslate_run_to_hebrew`` — fires from the orchestrator the moment
  a run flips to ``done``, and is re-kicked from ``get_run`` whenever a
  done run is fetched with an incomplete cache. Stores the resulting
  Hebrew strings on ``ComparisonRun.translations_he`` so the eventual
  export request can read from cache (instant, no LLM call). Generous
  timeouts (no Render edge in this code path — it's a background task on
  the same worker). Idempotent partial-cache filler: each call only
  re-sends MISSING keys to the LLM, successes merge into the existing
  cache.

- The export route — when ``translations_he`` is empty (user exported
  before pre-translation finished, or pre-translation failed), the
  synchronous helpers below are used as a fallback with a tight wall-clock
  cap so the response doesn't 500 on Render's ~30 s edge idle timeout.
"""

from __future__ import annotations

import asyncio
import logging
import re
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


# Matches any character in the Hebrew Unicode block (U+0590 to U+05FF).
# Used to validate that the LLM actually translated the input — without
# this check, gpt-oss:120b's failure mode (returning the English input
# verbatim or with cosmetic edits) silently lands in the cache and the
# user sees English body prose inside a Hebrew memo.
_HEBREW_RE = re.compile(r"[֐-׿]")


def _contains_hebrew(text: str) -> bool:
    """True when ``text`` has at least one Hebrew character. Used as the
    success signal for a translation — a "Hebrew" response with zero
    Hebrew characters is the LLM failing to translate, not succeeding."""
    return bool(_HEBREW_RE.search(text))


_TRANSLATE_PROMPT = """Translate the following English accounting memo text into Hebrew.

CRITICAL RULES:
1. Your output MUST be in Hebrew. Every English word in narrative prose must become Hebrew.
2. Keep these specific terms in English as-is: standard codes (ASC 606, ASC 326, IFRS 9, IFRS 15, IAS 39), abbreviations (EPS, FVOCI, ECL, CECL, EIR, NPV, GAAP), and proper nouns (FASB, IASB).
3. Translate EVERYTHING else: every other English word, every bracketed phrase, every parenthetical note.
4. Output ONLY the Hebrew translation, with no preamble, no explanations, no quotes around it, no markdown fences.

ENGLISH TEXT:
{text}

HEBREW TRANSLATION:"""


async def _translate_single_field(
    text: str, *, timeout: float = 30.0,
) -> str | None:
    """Translate one English prose field to Hebrew via a direct (non-JSON)
    LLM call. Returns the Hebrew string on success, or None when:

      - the call timed out / raised,
      - the LLM returned an empty string,
      - the LLM returned text with no Hebrew characters (the failure mode
        we hit in production: gpt-oss:120b would return the English input
        with cosmetic edits and the code happily cached it as
        "translated").

    Returning None lets callers distinguish "translation failed, leave
    the English source alone" from "translation succeeded, use this
    Hebrew text" — a distinction the old batched-JSON path collapsed.
    """
    if not text or not text.strip():
        return None
    try:
        from app.llm.client import get_llm
        prompt = _TRANSLATE_PROMPT.format(text=text)
        response = await asyncio.wait_for(
            get_llm().complete(prompt), timeout=timeout,
        )
        out = (response.text or "").strip()
        # Strip a leading markdown fence if the LLM ignored the rule.
        if out.startswith("```"):
            out = out.strip("`").strip()
            for prefix in ("hebrew\n", "hebrew:", "he\n", "he:"):
                if out.lower().startswith(prefix):
                    out = out[len(prefix):].strip()
                    break
        # Strip an "HEBREW TRANSLATION:" preamble the model sometimes
        # echoes back even though the prompt told it not to.
        for label in ("HEBREW TRANSLATION:", "Hebrew translation:", "Hebrew:"):
            if out.startswith(label):
                out = out[len(label):].strip()
        if not out:
            logger.warning("translation returned empty text for input %r", text[:80])
            return None
        if not _contains_hebrew(out):
            # The most common production failure: LLM echoes the input
            # verbatim or rephrases it in English. Logging the truncated
            # raw response makes the failure visible in Render logs so
            # we can iterate on the prompt if it recurs.
            logger.warning(
                "translation produced no Hebrew characters; "
                "input head=%r, response head=%r",
                text[:80], out[:80],
            )
            return None
        return out
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError, GeneratorExit):
        raise
    except BaseException as exc:
        logger.warning(
            "single-field translation failed for input %r: %r",
            text[:80], exc,
        )
        return None


async def _translate_to_hebrew(
    items: dict[str, str], *, per_batch_timeout: float = 18.0,
) -> dict[str, str]:
    """Translate every value in ``items`` to Hebrew via parallel per-field
    LLM calls.

    Returns a dict with the same keys as ``items``. Values that translated
    successfully are Hebrew; values whose LLM call failed or returned
    non-Hebrew text fall back to the English source so the export can
    still ship. Empty / whitespace-only values pass through unchanged so
    the LLM only sees real text.

    The function name is kept for backward compatibility with monkey-
    patched tests; the implementation switched from batched-JSON to
    per-field after the JSON path proved unreliable in production
    (gpt-oss:120b returned the input unchanged for most multi-key
    batches).

    ``per_batch_timeout`` is the per-field timeout — the parameter name
    is preserved so existing call sites don't need updating.
    """
    nonempty = {k: v for k, v in items.items() if v and v.strip()}
    if not nonempty:
        return items
    results = await asyncio.gather(
        *(_translate_single_field(v, timeout=per_batch_timeout) for v in nonempty.values()),
        return_exceptions=True,
    )
    out = dict(items)
    for k, result in zip(nonempty.keys(), results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("translation field raised %r — keeping English", result)
            continue
        if result is None:
            # Failed / non-Hebrew — leave the English source in `out` so
            # the boilerplate localizer at least handles the canned bits.
            continue
        out[k] = result
    return out


async def _translate_batches_parallel(
    flat: dict[str, str],
    batch_size: int = 4,
    *,
    per_batch_timeout: float = 18.0,
) -> dict[str, str]:
    """Translate a flat dict of prose fields in parallel.

    Historical signature kept for backward compatibility with existing
    callers and tests. With the per-field implementation in
    ``_translate_to_hebrew`` there's no longer a "batch" concept — each
    field becomes its own concurrent LLM call internally — so this
    function just delegates and the ``batch_size`` parameter is ignored.

    Translation failures degrade per-field: failed fields keep their
    English values and the rest of the memo still ships in Hebrew.
    """
    if not flat:
        return flat
    return await _translate_to_hebrew(flat, per_batch_timeout=per_batch_timeout)


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

    Idempotent: short-circuits when the existing cache already covers
    every prose key. When the cache is partial (a previous attempt
    translated some batches but not others), only the MISSING keys are
    re-sent to the LLM — successful translations are preserved across
    retries and each call moves us closer to a fully-Hebrew cache.
    Failures on the missing set are logged and the cache is left as-is;
    the next call (kicked from `get_run`) tries again.
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

            # Resume from any prior partial translation. `cache` is the
            # existing Hebrew dict (may cover some keys but not all);
            # `missing` is what we still need to translate. Short-circuit
            # when the cache already covers everything — no LLM call
            # needed at all.
            cache: dict[str, str] = dict(run.translations_he or {})
            missing = {k: v for k, v in flat.items() if k not in cache}
            if not missing:
                return

            # Small batches + a generous per-batch timeout. The bottleneck
            # is gpt-oss:120b's cold-start on a fresh Ollama Cloud API
            # key — at batch_size=4 a single slow batch took the entire
            # 60 s budget; at batch_size=2 the same memo finishes in
            # under 30 s wall-clock because the slow key only ties up
            # one batch, the other batches finish on faster keys and
            # the rotator naturally load-balances. 90 s per-batch
            # absorbs the worst-case cold-key latency without giving up.
            translated = await _translate_batches_parallel(
                missing, batch_size=2, per_batch_timeout=90.0,
            )

            # Merge translations into the existing cache. Only keys whose
            # translation actually changed (i.e. didn't degrade to the
            # English source) are persisted — that way a future call to
            # `pretranslate_run_to_hebrew` will re-attempt the missing
            # keys on a hopefully-warmer key. Also run
            # `localize_boilerplate` on each translated value so any
            # canned English fragment the LLM left intact (the synthesis
            # marker, the verifier no-corpus sentence) gets flipped to
            # Hebrew before we persist. Without this, a partially-
            # translated value lands in the cache, the export path
            # serves it from cache (skipping the sync fallback), and the
            # user sees English fragments inside a Hebrew memo.
            added = 0
            for k, v in translated.items():
                src = missing.get(k)
                if v and isinstance(v, str) and v != src:
                    cache[k] = localize_boilerplate(v, "he") or v
                    added += 1
            if not added:
                logger.warning(
                    "pretranslate: 0 new keys for run %s "
                    "(all %d missing batches degraded to English; "
                    "%d already cached)",
                    run_id, len(missing), len(run.translations_he or {}),
                )
                return

            run.translations_he = cache
            # JSONB columns aren't auto-dirtied on in-place mutations;
            # explicit flag covers the case where SQLAlchemy's change
            # detector misses the reassignment via attribute set.
            flag_modified(run, "translations_he")
            await session.commit()
            logger.info(
                "pretranslate: cached %d new HE translations for run %s "
                "(%d/%d total covered)",
                added, run_id, len(cache), len(flat),
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
