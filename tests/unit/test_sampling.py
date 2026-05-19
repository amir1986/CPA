"""Sampling determinism + reproducibility tests."""

from __future__ import annotations

import pytest

from app.audit.sampling import (
    SamplingItem,
    mus_sample,
    random_sample,
    sample_size_attribute,
    stratified_sample,
)


def _items(n: int) -> list[SamplingItem]:
    return [SamplingItem(id=f"id-{i}", amount=float(i + 1) * 100.0) for i in range(n)]


def test_random_sample_reproducible_with_same_seed() -> None:
    items = _items(50)
    a = random_sample(items, size=10, seed=7)
    b = random_sample(items, size=10, seed=7)
    assert a.selected == b.selected
    assert len(a.selected) == 10


def test_different_seeds_yield_different_samples() -> None:
    items = _items(50)
    a = random_sample(items, size=10, seed=1)
    b = random_sample(items, size=10, seed=2)
    assert a.selected != b.selected


def test_random_sample_clamps_to_population_size() -> None:
    items = _items(3)
    r = random_sample(items, size=100, seed=0)
    assert len(r.selected) == 3


def test_stratified_sample_reproducible() -> None:
    items = _items(100)
    a = stratified_sample(items, strata_boundaries=[500, 1000, 5000], per_stratum=3, seed=11)
    b = stratified_sample(items, strata_boundaries=[500, 1000, 5000], per_stratum=3, seed=11)
    assert a.selected == b.selected


def test_stratified_requires_ascending_boundaries() -> None:
    with pytest.raises(ValueError):
        stratified_sample([], strata_boundaries=[1000, 500], per_stratum=1, seed=0)


def test_mus_picks_more_at_high_amounts() -> None:
    items = _items(100)
    r = mus_sample(items, performance_materiality=1000, sampling_factor=3, seed=42)
    # MUS biases toward larger amounts — last items should appear more often than first.
    last_quartile = sum(1 for sid in r.selected if int(sid.split("-")[1]) >= 75)
    first_quartile = sum(1 for sid in r.selected if int(sid.split("-")[1]) < 25)
    assert last_quartile >= first_quartile


def test_mus_reproducible() -> None:
    items = _items(50)
    a = mus_sample(items, performance_materiality=1000, sampling_factor=3, seed=3)
    b = mus_sample(items, performance_materiality=1000, sampling_factor=3, seed=3)
    assert a.selected == b.selected


def test_sample_size_attribute_increases_with_tighter_margin() -> None:
    big_margin = sample_size_attribute(confidence=0.95, expected_deviation=0.05, tolerable_deviation=0.20)
    small_margin = sample_size_attribute(confidence=0.95, expected_deviation=0.05, tolerable_deviation=0.10)
    assert small_margin > big_margin
