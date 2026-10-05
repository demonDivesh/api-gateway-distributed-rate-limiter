"""Per-upstream circuit breaker (closed -> open -> half-open -> closed).

All methods are synchronous and contain no awaits, so they are atomic with respect to
the asyncio event loop and need no locks.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 15.0,
        half_open_max_calls: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or half_open_max_calls < 1:
            raise ValueError("thresholds must be >= 1")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.half_open_max_calls = half_open_max_calls
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_in_flight = 0
        self._half_open_successes = 0

    @property
    def state(self) -> BreakerState:
        if (
            self._state is BreakerState.OPEN
            and self._clock() - self._opened_at >= self.recovery_seconds
        ):
            self._state = BreakerState.HALF_OPEN
            self._half_open_in_flight = 0
            self._half_open_successes = 0
        return self._state

    @property
    def failures(self) -> int:
        return self._failures

    def would_allow(self) -> bool:
        """Non-mutating check used when filtering candidate instances."""
        state = self.state
        if state is BreakerState.CLOSED:
            return True
        if state is BreakerState.HALF_OPEN:
            return self._half_open_in_flight < self.half_open_max_calls
        return False

    def allow_request(self) -> bool:
        """Reserve permission to send a request. Half-open reserves a probe slot."""
        if not self.would_allow():
            return False
        if self._state is BreakerState.HALF_OPEN:
            self._half_open_in_flight += 1
        return True

    def record_success(self) -> None:
        if self.state is BreakerState.HALF_OPEN:
            self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_max_calls:
                self._close()
        elif self._state is BreakerState.CLOSED:
            self._failures = 0

    def record_failure(self) -> None:
        state = self.state
        if state is BreakerState.HALF_OPEN:
            self._trip()
        elif state is BreakerState.CLOSED:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._trip()

    def reset(self) -> None:
        self._close()

    def _trip(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._half_open_in_flight = 0
        self._half_open_successes = 0

    def _close(self) -> None:
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._half_open_in_flight = 0
        self._half_open_successes = 0

    def snapshot(self) -> dict:
        return {"state": self.state.value, "failures": self._failures}
