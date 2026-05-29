"""Unit tests for the KeyRotator state machine."""

from __future__ import annotations

import pytest

from app.llm.ollama_rotator import (
    AllKeysExhausted,
    KeyRotator,
    KeyStatus,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def make_rotator(keys: list[str], *, cooldown: float = 60.0, clock: FakeClock | None = None) -> tuple[KeyRotator, FakeClock]:
    clock = clock or FakeClock()
    return KeyRotator(keys, cooldown_seconds=cooldown, clock=clock), clock


def test_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError):
        KeyRotator([])
    with pytest.raises(ValueError):
        KeyRotator(["", "   "])


def test_dedupes_keys_preserving_order() -> None:
    r, _ = make_rotator(["a", "b", "a", "c"])
    snap = r.snapshot()
    assert len(snap.keys) == 3


def test_acquire_returns_first_key_initially() -> None:
    r, _ = make_rotator(["k1", "k2", "k3"])
    s = r.acquire()
    assert s.key == "k1"


def test_rate_limit_advances_circularly() -> None:
    r, _ = make_rotator(["k1", "k2", "k3"], cooldown=60)
    s = r.acquire()
    assert s.key == "k1"
    r.report_rate_limited(s.key)
    # Next acquire moves to k2.
    assert r.acquire().key == "k2"
    r.report_rate_limited("k2")
    # And then to k3.
    assert r.acquire().key == "k3"


def test_wrap_around_after_all_rate_limited_then_cooldown_expires() -> None:
    clock = FakeClock()
    r, _ = make_rotator(["k1", "k2"], cooldown=30, clock=clock)
    r.report_rate_limited(r.acquire().key)  # k1 cool until t+30
    r.report_rate_limited(r.acquire().key)  # k2 cool until t+30
    # Now everyone is cooling.
    with pytest.raises(AllKeysExhausted) as exc_info:
        r.acquire()
    # Smallest cooldown is 30s.
    assert exc_info.value.retry_after == pytest.approx(30.0)

    # Advance time past cooldown — k1 becomes active again.
    clock.tick(30)
    s = r.acquire()
    assert s.key == "k1"
    assert s.status is KeyStatus.ACTIVE


def test_retry_after_header_overrides_default_cooldown() -> None:
    clock = FakeClock()
    r, _ = make_rotator(["k1", "k2"], cooldown=60, clock=clock)
    r.report_rate_limited("k1", retry_after_seconds=5)
    # k1 cool for 5s; default cooldown was 60s but we honored the hint.
    with pytest.raises(AllKeysExhausted):
        # Force only one usable initially, then make sure k2 also cools.
        r.report_rate_limited(r.acquire().key, retry_after_seconds=5)
        r.acquire()
    snap = r.snapshot()
    # Both should be cooling with ~5s remaining.
    cooldowns = [k["cooldown_remaining"] for k in snap.keys if k["status"] == "cooling"]
    assert len(cooldowns) == 2
    assert all(c <= 5.0 for c in cooldowns)


def test_unauthorized_permanently_disables_key() -> None:
    r, _ = make_rotator(["k1", "k2"])
    r.report_unauthorized("k1", reason="bad-token")
    # k1 disabled, only k2 cycles.
    for _ in range(5):
        assert r.acquire().key == "k2"
    snap = r.snapshot()
    assert any(k["status"] == "disabled" and k["last_error"] == "bad-token" for k in snap.keys)


def test_all_disabled_raises_with_no_retry_after() -> None:
    r, _ = make_rotator(["k1", "k2"])
    r.report_unauthorized("k1")
    r.report_unauthorized("k2")
    with pytest.raises(AllKeysExhausted) as exc_info:
        r.acquire()
    assert exc_info.value.retry_after is None


def test_server_error_does_not_advance_cursor() -> None:
    r, _ = make_rotator(["k1", "k2"])
    s = r.acquire()
    assert s.key == "k1"
    r.report_server_error("k1")
    # Same key on next acquire (caller retries).
    assert r.acquire().key == "k1"
    snap = r.snapshot()
    assert snap.keys[0]["consecutive_failures"] == 1
    assert snap.keys[0]["last_error"] == "server_error"


def test_cooldown_key_cools_and_advances_to_next_key() -> None:
    # Regression: a single key returning 5xx forever used to starve the
    # other keys because report_server_error never moved the cursor. Once
    # the client cools the bad key via cooldown_key, acquire must fan out
    # to the next healthy key instead of handing back the same one.
    r, _ = make_rotator(["k1", "k2"], cooldown=30)
    assert r.acquire().key == "k1"
    r.report_server_error("k1")
    r.cooldown_key("k1")
    assert r.acquire().key == "k2"
    snap = r.snapshot()
    assert snap.keys[0]["status"] == "cooling"


def test_cooldown_key_unknown_is_a_no_op() -> None:
    r, _ = make_rotator(["k1"])
    r.cooldown_key("nope")  # must not raise
    assert r.acquire().key == "k1"


def test_success_resets_failure_counter() -> None:
    r, _ = make_rotator(["k1", "k2"])
    r.acquire()
    r.report_server_error("k1")
    r.report_server_error("k1")
    r.report_success("k1")
    snap = r.snapshot()
    assert snap.keys[0]["consecutive_failures"] == 0
    assert snap.keys[0]["last_error"] is None


def test_snapshot_masks_keys() -> None:
    r, _ = make_rotator(["my-super-secret-token-abcd", "anotherone-1234"])
    snap = r.snapshot()
    for k in snap.keys:
        assert "secret" not in str(k["key"]).lower()
        assert "anotherone" not in str(k["key"])


def test_cooldown_expiry_refreshes_status_lazily() -> None:
    clock = FakeClock()
    r, _ = make_rotator(["k1"], cooldown=10, clock=clock)
    r.report_rate_limited("k1")
    # k1 is cooling.
    with pytest.raises(AllKeysExhausted):
        r.acquire()
    clock.tick(11)
    # First acquire after expiry restores the key.
    s = r.acquire()
    assert s.status is KeyStatus.ACTIVE
    assert s.key == "k1"


def test_reporting_unknown_key_is_a_no_op() -> None:
    r, _ = make_rotator(["k1"])
    # Should not raise.
    r.report_success("nope")
    r.report_rate_limited("nope")
    r.report_unauthorized("nope")
    r.report_server_error("nope")


def test_request_counter_increments_per_acquire() -> None:
    r, _ = make_rotator(["k1", "k2"])
    r.acquire()
    r.acquire()
    r.acquire()
    snap = r.snapshot()
    total = sum(int(k["requests"]) for k in snap.keys)
    assert total == 3
