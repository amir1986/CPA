"""Engagement-scoped tools the agent can call.

Each tool is a thin wrapper around a deterministic service. The wrappers
return JSON-serializable dicts so the agent's reasoning trace persists
cleanly to ``agent_runs``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyze.anomalies import benford_first_digit
from app.audit.je_tests import (
    benford_hits,
    late_posting_hits,
    round_amount_hits,
    threshold_hits,
    unusual_user_hits,
    weekend_holiday_hits,
)
from app.audit.je_tests.benford import JEAmount
from app.audit.sampling import SamplingItem, random_sample
from app.db.models.books import GLEntry, TrialBalance
from app.rag.query_engine import answer_question


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def build_tools(*, engagement_id: uuid.UUID, session: AsyncSession) -> list[Tool]:
    """Bind tools to an engagement+session pair."""

    async def kb_search(args: dict[str, Any]) -> dict[str, Any]:
        result = await answer_question(
            str(args.get("question", "")),
            jurisdictions=args.get("jurisdictions"),
            corpus_types=args.get("corpus_types"),
            top_k=args.get("top_k"),
        )
        return {
            "refused": result.refused,
            "answer": result.answer,
            "citations": [{"standard": c.standard, "url": c.url, "quote": c.quote} for c in result.citations],
        }

    async def get_trial_balance(args: dict[str, Any]) -> dict[str, Any]:
        rows = (
            await session.scalars(
                select(TrialBalance).where(TrialBalance.engagement_id == engagement_id)
            )
        ).all()
        return {
            "rows": [
                {
                    "period_end": str(r.period_end),
                    "code": r.account_code,
                    "name": r.account_name,
                    "closing": float(r.closing),
                }
                for r in rows
            ]
        }

    async def run_benford(args: dict[str, Any]) -> dict[str, Any]:
        rows = (await session.execute(select(GLEntry.debit, GLEntry.credit).where(GLEntry.engagement_id == engagement_id))).all()
        amounts = [float(d or 0) - float(c or 0) for d, c in rows]
        summary = benford_first_digit(amounts)
        return {
            "n": summary.n,
            "chi_square": summary.chi_square,
            "suspect": summary.suspect,
            "observed_pct": summary.observed_pct,
        }

    async def run_je_test(args: dict[str, Any]) -> dict[str, Any]:
        kind = str(args.get("test_kind", "benford"))
        rows = (await session.scalars(select(GLEntry).where(GLEntry.engagement_id == engagement_id))).all()
        wrapped = [_GLAdapter(r) for r in rows]
        if kind == "benford":
            amts = [JEAmount(id=str(e.id), je_number=e.je_number, je_date=e.je_date, amount=float(e.debit) - float(e.credit)) for e in rows]
            hits = benford_hits(amts)
        elif kind == "weekend_holiday":
            hits = weekend_holiday_hits(wrapped)
        elif kind == "round_amounts":
            hits = round_amount_hits(wrapped, units=int(args.get("units", 1000)))
        elif kind == "unusual_user":
            hits = unusual_user_hits(wrapped, rare_threshold=int(args.get("rare_threshold", 3)))
        elif kind == "late_postings":
            hits = late_posting_hits(wrapped, max_lag_days=int(args.get("max_lag_days", 5)))
        elif kind == "threshold":
            hits = threshold_hits(wrapped, amount_threshold=float(args.get("amount_threshold", 0)))
        else:
            return {"error": f"unknown test_kind: {kind}"}
        return {"test_kind": kind, "hits_count": len(hits), "hits_preview": hits[:10]}

    async def draw_sample(args: dict[str, Any]) -> dict[str, Any]:
        rows = (await session.scalars(select(GLEntry).where(GLEntry.engagement_id == engagement_id))).all()
        items = [SamplingItem(id=str(e.id), amount=float(e.debit) - float(e.credit)) for e in rows]
        result = random_sample(items, size=int(args.get("size", 25)), seed=int(args.get("seed", 42)))
        return {"method": result.method, "seed": result.seed, "selected": list(result.selected)}

    return [
        Tool(
            name="kb_search",
            description="Search the standards corpus and return a cited answer.",
            parameters={"question": "string", "jurisdictions": "list[string]?", "corpus_types": "list[string]?"},
            fn=kb_search,
        ),
        Tool(
            name="get_trial_balance",
            description="Return the engagement's persisted trial balance rows.",
            parameters={},
            fn=get_trial_balance,
        ),
        Tool(
            name="run_benford",
            description="Run Benford 1st-digit on the engagement GL.",
            parameters={},
            fn=run_benford,
        ),
        Tool(
            name="run_je_test",
            description="Run one JE test (benford, weekend_holiday, round_amounts, unusual_user, late_postings, threshold).",
            parameters={"test_kind": "string", "amount_threshold": "number?"},
            fn=run_je_test,
        ),
        Tool(
            name="draw_sample",
            description="Draw a deterministic random sample from the engagement GL.",
            parameters={"size": "int", "seed": "int"},
            fn=draw_sample,
        ),
    ]


class _GLAdapter:
    """Duck-typed adapter so JE-test helpers can read GLEntry rows."""

    def __init__(self, gl: GLEntry) -> None:
        self.id = str(gl.id)
        self.je_number = gl.je_number
        self.je_date = gl.je_date
        self.posting_date = gl.posting_date
        self.preparer = gl.preparer
        self.approver = gl.approver
        self.currency = gl.currency
        self.description = gl.description
        self.amount = float(gl.debit) - float(gl.credit)
