"""Audit sampling: random, stratified, MUS (Monetary Unit Sampling).

All methods are deterministic given a seed. The caller persists ``seed +
population_query + selected_ids`` so re-runs reproduce the exact IDs.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SamplingItem:
    id: str
    amount: float


@dataclass(frozen=True)
class SampleResult:
    method: str
    seed: int
    selected: tuple[str, ...]


def random_sample(items: Sequence[SamplingItem], *, size: int, seed: int) -> SampleResult:
    if size < 0:
        raise ValueError("size must be ≥ 0")
    rng = random.Random(seed)
    selected = rng.sample(list(items), k=min(size, len(items)))
    return SampleResult(method="random", seed=seed, selected=tuple(s.id for s in selected))


def stratified_sample(
    items: Sequence[SamplingItem],
    *,
    strata_boundaries: Sequence[float],
    per_stratum: int,
    seed: int,
) -> SampleResult:
    """Stratify by ``|amount|`` against ``strata_boundaries`` (ascending), then random within each."""
    if not strata_boundaries or strata_boundaries != sorted(strata_boundaries):
        raise ValueError("strata_boundaries must be a non-empty sorted ascending sequence")
    rng = random.Random(seed)
    buckets: list[list[SamplingItem]] = [[] for _ in range(len(strata_boundaries) + 1)]
    for it in items:
        amt = abs(it.amount)
        placed = False
        for idx, bound in enumerate(strata_boundaries):
            if amt < bound:
                buckets[idx].append(it)
                placed = True
                break
        if not placed:
            buckets[-1].append(it)
    selected: list[str] = []
    for b in buckets:
        if not b:
            continue
        chosen = rng.sample(b, k=min(per_stratum, len(b)))
        selected.extend(s.id for s in chosen)
    return SampleResult(method="stratified", seed=seed, selected=tuple(selected))


def mus_sample(
    items: Sequence[SamplingItem],
    *,
    performance_materiality: float,
    sampling_factor: float = 3.0,
    seed: int,
) -> SampleResult:
    """Monetary Unit Sampling.

    Each currency unit has a probability proportional to ``|amount|``. We
    pick the items that span systematic intervals of length
    ``performance_materiality / sampling_factor``.

    The seeded random start makes reruns identical.
    """
    if performance_materiality <= 0:
        raise ValueError("performance_materiality must be positive")
    interval = performance_materiality / sampling_factor
    rng = random.Random(seed)
    start = rng.uniform(0, interval)
    total = 0.0
    next_hit = start
    selected: list[str] = []
    for it in items:
        total += abs(it.amount)
        while total >= next_hit:
            selected.append(it.id)
            next_hit += interval
    # Dedupe while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for sid in selected:
        if sid not in seen:
            seen.add(sid)
            deduped.append(sid)
    return SampleResult(method="mus", seed=seed, selected=tuple(deduped))


def sample_size_attribute(
    *,
    confidence: float = 0.95,
    expected_deviation: float = 0.05,
    tolerable_deviation: float = 0.10,
) -> int:
    """Attribute sample size from a normal approximation. Returns ``n``.

    n = z^2 * p * (1-p) / (tolerable - expected)^2  (one-tailed).
    """
    if not (0 < confidence < 1):
        raise ValueError("confidence must be in (0, 1)")
    if expected_deviation >= tolerable_deviation:
        raise ValueError("expected_deviation must be < tolerable_deviation")
    # Approximate inverse normal CDF for common confidences.
    z_table = {0.90: 1.282, 0.95: 1.645, 0.975: 1.960, 0.99: 2.326}
    z = z_table.get(round(confidence, 3), 1.96)
    margin = tolerable_deviation - expected_deviation
    n = (z ** 2) * expected_deviation * (1 - expected_deviation) / (margin ** 2)
    return max(1, math.ceil(n))
