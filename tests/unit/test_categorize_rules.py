"""Rule-based categorization tests."""

from __future__ import annotations

from app.categorize.rules import Rule, apply_rules


class _Entry:
    def __init__(self, **kw): self.__dict__.update(kw)


def test_first_matching_rule_wins_by_confidence() -> None:
    rules = [
        Rule(id="r1", account_id="acc-rent", confidence=0.9, spec={"description_regex": r"rent"}),
        Rule(id="r2", account_id="acc-utilities", confidence=0.95, spec={"description_regex": r"electric"}),
    ]
    entries = [_Entry(id="e1", description="Monthly rent ACME", amount=2000.0, currency="USD")]
    suggestions, unmatched = apply_rules(entries, rules)
    assert len(suggestions) == 1
    assert suggestions[0].account_id == "acc-rent"
    assert unmatched == []


def test_amount_range_filter() -> None:
    rules = [
        Rule(id="r1", account_id="acc-petty-cash", confidence=0.8, spec={"amount_max": 100}),
        Rule(id="r2", account_id="acc-large", confidence=0.8, spec={"amount_min": 100}),
    ]
    e_small = _Entry(id="s", description="x", amount=50.0, currency="USD")
    e_big = _Entry(id="b", description="x", amount=500.0, currency="USD")
    suggestions, unmatched = apply_rules([e_small, e_big], rules)
    assert {s.entry_id: s.account_id for s in suggestions} == {
        "s": "acc-petty-cash",
        "b": "acc-large",
    }
    assert unmatched == []


def test_unmatched_entries_are_surfaced() -> None:
    rules = [Rule(id="r1", account_id="x", confidence=0.9, spec={"description_regex": r"foo"})]
    e = _Entry(id="e1", description="bar", amount=10.0, currency="USD")
    suggestions, unmatched = apply_rules([e], rules)
    assert suggestions == []
    assert unmatched == [e]
