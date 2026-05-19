"""Bank reconciliation matcher.

Greedy 1:1 matching of bank lines to GL entries by:
- amount equality within ``amount_tolerance``,
- value-date within ``date_window_days``,
- description token-set ratio ≥ ``description_threshold`` (rapidfuzz).

Returns matched pairs + lists of unmatched entries on either side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

from rapidfuzz import fuzz


@dataclass(frozen=True)
class BankLine:
    id: str
    value_date: date | None
    amount: float
    description: str | None


@dataclass(frozen=True)
class GLLine:
    id: str
    je_date: date | None
    amount: float
    description: str | None


@dataclass(frozen=True)
class Match:
    bank_id: str
    gl_id: str
    score: float


@dataclass(frozen=True)
class ReconciliationResult:
    matched: tuple[Match, ...]
    unmatched_bank: tuple[str, ...]
    unmatched_gl: tuple[str, ...]


def reconcile_bank(
    bank_lines: Sequence[BankLine],
    gl_lines: Sequence[GLLine],
    *,
    amount_tolerance: float = 0.01,
    date_window_days: int = 3,
    description_threshold: int = 60,
) -> ReconciliationResult:
    remaining_gl = list(gl_lines)
    matched: list[Match] = []
    unmatched_bank: list[str] = []

    for bl in bank_lines:
        best_idx = -1
        best_score = -1.0
        for idx, gl in enumerate(remaining_gl):
            if abs(bl.amount - gl.amount) > amount_tolerance:
                continue
            if bl.value_date and gl.je_date:
                if abs((bl.value_date - gl.je_date).days) > date_window_days:
                    continue
            desc_score = fuzz.token_set_ratio(bl.description or "", gl.description or "")
            if desc_score < description_threshold:
                continue
            # Composite score: prefer closer dates + higher description match.
            date_score = 100.0
            if bl.value_date and gl.je_date:
                date_score = 100.0 - 10.0 * abs((bl.value_date - gl.je_date).days)
            composite = 0.6 * desc_score + 0.4 * max(0.0, date_score)
            if composite > best_score:
                best_score = composite
                best_idx = idx
        if best_idx >= 0:
            gl = remaining_gl.pop(best_idx)
            matched.append(Match(bank_id=bl.id, gl_id=gl.id, score=best_score))
        else:
            unmatched_bank.append(bl.id)

    unmatched_gl = [gl.id for gl in remaining_gl]
    return ReconciliationResult(
        matched=tuple(matched),
        unmatched_bank=tuple(unmatched_bank),
        unmatched_gl=tuple(unmatched_gl),
    )
