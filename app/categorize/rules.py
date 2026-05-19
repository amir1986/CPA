"""Rule-based GL categorization.

Rules are JSON-shaped: ``{"description_regex": "...", "amount_min": float,
"amount_max": float, "currency": "USD"}``. A rule matches when every present
condition matches. First match wins (ordered by ``confidence`` descending);
unmatched lines fall through to the LLM classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class Rule:
    id: str
    account_id: str
    confidence: float
    spec: dict[str, Any]

    def matches(self, *, description: str | None, amount: float, currency: str | None) -> bool:
        if (pat := self.spec.get("description_regex")):
            if description is None or not re.search(pat, description, re.IGNORECASE):
                return False
        if (lo := self.spec.get("amount_min")) is not None and amount < lo:
            return False
        if (hi := self.spec.get("amount_max")) is not None and amount > hi:
            return False
        if (cur := self.spec.get("currency")) is not None and (currency or "").upper() != cur.upper():
            return False
        return True


@dataclass(frozen=True)
class Suggestion:
    entry_id: str
    account_id: str
    confidence: float
    source: str       # "rule" | "llm"
    rule_id: str | None = None
    rationale: str | None = None


def apply_rules(
    entries: Sequence[object],
    rules: Iterable[Rule],
) -> tuple[list[Suggestion], list[object]]:
    """Run rules over entries. Returns ``(suggestions, unmatched_entries)``."""
    sorted_rules = sorted(rules, key=lambda r: r.confidence, reverse=True)
    suggestions: list[Suggestion] = []
    unmatched: list[object] = []
    for e in entries:
        description = getattr(e, "description", None)
        amount = float(getattr(e, "amount", 0.0))
        currency = getattr(e, "currency", None)
        matched: Rule | None = next(
            (r for r in sorted_rules if r.matches(description=description, amount=amount, currency=currency)),
            None,
        )
        if matched is None:
            unmatched.append(e)
            continue
        suggestions.append(
            Suggestion(
                entry_id=getattr(e, "id"),
                account_id=matched.account_id,
                confidence=matched.confidence,
                source="rule",
                rule_id=matched.id,
            )
        )
    return suggestions, unmatched
