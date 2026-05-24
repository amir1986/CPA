"""Circular API-key rotator for Ollama Cloud.

Pure logic (no I/O). Caller is responsible for actually issuing HTTP requests
and feeding outcomes back via ``report_success`` / ``report_rate_limited`` /
``report_unauthorized`` / ``report_server_error``.

State machine, per key:
- ``active``      — normal; advance circularly on rate-limit.
- ``cooling``     — temporarily skipped until ``cooldown_until``.
- ``disabled``    — permanently skipped this process lifetime (401/403).

If all keys are unavailable, ``acquire`` raises :class:`AllKeysExhausted` and
returns the smallest remaining cooldown so the caller can surface a sensible
``Retry-After``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class KeyStatus(str, Enum):
    ACTIVE = "active"
    COOLING = "cooling"
    DISABLED = "disabled"


@dataclass
class KeyState:
    key: str
    status: KeyStatus = KeyStatus.ACTIVE
    cooldown_until: float = 0.0
    consecutive_failures: int = 0
    last_error: str | None = None
    requests: int = 0

    def masked(self) -> str:
        return _mask(self.key)


@dataclass
class RotatorSnapshot:
    keys: list[dict[str, object]] = field(default_factory=list)
    cursor: int = 0


class AllKeysExhausted(RuntimeError):
    """Raised when no key is currently usable.

    ``retry_after`` is the number of seconds until the soonest cooldown
    expires, or ``None`` if every key is permanently disabled.
    """

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("All Ollama Cloud API keys are exhausted.")
        self.retry_after = retry_after


class KeyRotator:
    """Thread-safe circular rotator with cooldowns and permanent disables."""

    def __init__(
        self,
        keys: list[str],
        *,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not keys:
            raise ValueError("KeyRotator requires at least one key")
        # Preserve declared order but dedupe and drop blanks.
        seen: set[str] = set()
        unique: list[str] = []
        for k in keys:
            stripped = k.strip() if isinstance(k, str) else ""
            if stripped and stripped not in seen:
                seen.add(stripped)
                unique.append(stripped)
        if not unique:
            raise ValueError("KeyRotator requires at least one non-empty key")

        self._states: list[KeyState] = [KeyState(key=k) for k in unique]
        self._cursor: int = 0
        self._cooldown: float = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()

    # ──────────────── acquire / advance ────────────────

    def acquire(self) -> KeyState:
        """Return the next usable key. Raises :class:`AllKeysExhausted` if none."""
        with self._lock:
            self._refresh_cooldowns_locked()
            n = len(self._states)
            for offset in range(n):
                idx = (self._cursor + offset) % n
                state = self._states[idx]
                if state.status is KeyStatus.ACTIVE:
                    self._cursor = idx
                    state.requests += 1
                    return state
            # Nothing active.
            raise AllKeysExhausted(self._soonest_cooldown_locked())

    def _advance_locked(self) -> None:
        self._cursor = (self._cursor + 1) % len(self._states)

    def _refresh_cooldowns_locked(self) -> None:
        now = self._clock()
        for s in self._states:
            if s.status is KeyStatus.COOLING and now >= s.cooldown_until:
                s.status = KeyStatus.ACTIVE
                s.cooldown_until = 0.0

    def _soonest_cooldown_locked(self) -> float | None:
        now = self._clock()
        candidates = [
            s.cooldown_until - now for s in self._states if s.status is KeyStatus.COOLING
        ]
        if not candidates:
            return None  # every key is permanently disabled
        return max(0.0, min(candidates))

    # ──────────────── outcome reports ────────────────

    def report_success(self, key: str) -> None:
        with self._lock:
            state = self._find_locked(key)
            if state is None:
                return
            state.consecutive_failures = 0
            state.last_error = None

    def report_rate_limited(self, key: str, *, retry_after_seconds: float | None = None) -> None:
        """Mark the key as cooling and advance the cursor circularly."""
        with self._lock:
            state = self._find_locked(key)
            if state is None:
                return
            cooldown = retry_after_seconds if retry_after_seconds is not None else self._cooldown
            cooldown = max(0.0, float(cooldown))
            state.status = KeyStatus.COOLING
            state.cooldown_until = self._clock() + cooldown
            state.consecutive_failures += 1
            state.last_error = "rate_limited"
            self._advance_locked()

    def report_unauthorized(self, key: str, *, reason: str = "unauthorized") -> None:
        """Permanently disable this key for the rest of the process lifetime."""
        with self._lock:
            state = self._find_locked(key)
            if state is None:
                return
            state.status = KeyStatus.DISABLED
            state.cooldown_until = 0.0
            state.consecutive_failures += 1
            state.last_error = reason
            self._advance_locked()

    def report_server_error(self, key: str, *, reason: str = "server_error") -> None:
        """Record a 5xx but do not move the cursor — caller will retry same key.

        The rotator does NOT decide retry counts; the HTTP client does. We just
        record the failure so it's visible in the snapshot.
        """
        with self._lock:
            state = self._find_locked(key)
            if state is None:
                return
            state.consecutive_failures += 1
            state.last_error = reason

    # ──────────────── introspection ────────────────

    def snapshot(self) -> RotatorSnapshot:
        with self._lock:
            self._refresh_cooldowns_locked()
            now = self._clock()
            keys: list[dict[str, object]] = []
            for s in self._states:
                keys.append({
                    "key": s.masked(),
                    "status": s.status.value,
                    "cooldown_remaining": max(0.0, s.cooldown_until - now) if s.status is KeyStatus.COOLING else 0.0,
                    "consecutive_failures": s.consecutive_failures,
                    "last_error": s.last_error,
                    "requests": s.requests,
                })
            return RotatorSnapshot(keys=keys, cursor=self._cursor)

    def __len__(self) -> int:
        return len(self._states)

    # ──────────────── helpers ────────────────

    def _find_locked(self, key: str) -> KeyState | None:
        for s in self._states:
            if s.key == key:
                return s
        return None


def _mask(key: str) -> str:
    """Mask all but the last 4 chars of a key for logs/snapshots."""
    if len(key) <= 4:
        return "*" * len(key)
    return f"…{key[-4:]}"
