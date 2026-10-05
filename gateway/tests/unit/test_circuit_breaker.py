import pytest
from app.services.circuit_breaker import BreakerState, CircuitBreaker


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make(clock: Clock, **kw) -> CircuitBreaker:
    return CircuitBreaker(
        kw.get("threshold", 3), kw.get("recovery", 10.0), kw.get("probes", 2), clock
    )


def test_opens_after_threshold_failures():
    clock = Clock()
    cb = make(clock)
    for _ in range(2):
        cb.record_failure()
    assert cb.state is BreakerState.CLOSED
    cb.record_failure()
    assert cb.state is BreakerState.OPEN
    assert not cb.allow_request()


def test_success_resets_failure_count():
    cb = make(Clock())
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    assert cb.state is BreakerState.CLOSED


def test_half_open_after_recovery_and_closes_after_successful_probes():
    clock = Clock()
    cb = make(clock)
    for _ in range(3):
        cb.record_failure()
    clock.now = 9.9
    assert cb.state is BreakerState.OPEN
    clock.now = 10.0
    assert cb.state is BreakerState.HALF_OPEN
    assert cb.allow_request() and cb.allow_request()
    assert not cb.allow_request()  # probe budget exhausted
    cb.record_success()
    assert cb.state is BreakerState.HALF_OPEN
    cb.record_success()
    assert cb.state is BreakerState.CLOSED
    assert cb.allow_request()


def test_half_open_failure_reopens_immediately():
    clock = Clock()
    cb = make(clock)
    for _ in range(3):
        cb.record_failure()
    clock.now = 10.0
    assert cb.allow_request()
    cb.record_failure()
    assert cb.state is BreakerState.OPEN
    clock.now = 15.0
    assert cb.state is BreakerState.OPEN  # recovery timer restarted at t=10
    clock.now = 20.0
    assert cb.state is BreakerState.HALF_OPEN


def test_would_allow_does_not_consume_probe_slots():
    clock = Clock()
    cb = make(clock, probes=1)
    for _ in range(3):
        cb.record_failure()
    clock.now = 10.0
    assert cb.would_allow() and cb.would_allow()
    assert cb.allow_request()
    assert not cb.would_allow()


def test_reset_and_snapshot():
    cb = make(Clock())
    for _ in range(3):
        cb.record_failure()
    assert cb.snapshot()["state"] == "open"
    cb.reset()
    assert cb.snapshot() == {"state": "closed", "failures": 0}


def test_invalid_config():
    with pytest.raises(ValueError):
        CircuitBreaker(0)
