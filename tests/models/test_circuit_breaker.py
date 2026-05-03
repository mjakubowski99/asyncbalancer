from datetime import datetime, UTC

from asyncbalancer.models.circuit_breaker import (
    BASE_RETRY_AFTER,
    CircuitBreaker,
    CircuitBreakerState,
)


def test_record_failure_always_increments_counter_in_open_state() -> None:
    breaker = CircuitBreaker(
        key="gemini",
        failure_threshold=3,
        retry_after=60,
        failures=2,
        state=CircuitBreakerState.OPEN,
        last_failure_time=1,
    )

    breaker.record_failure()

    assert breaker.failures == 3
    assert breaker.state == CircuitBreakerState.OPEN
    assert breaker.last_failure_time > 1
    assert breaker.retry_after == 60 * (2**2)


def test_record_failure_trips_circuit_when_threshold_reached() -> None:
    breaker = CircuitBreaker(
        key="gemini",
        failure_threshold=3,
        failures=2,
        state=CircuitBreakerState.CLOSED,
    )

    breaker.record_failure()

    assert breaker.failures == 3
    assert breaker.state == CircuitBreakerState.OPEN
    assert breaker.last_failure_time > 0
    assert breaker.retry_after == 60 * (2**2)


def test_half_open_failure_switches_back_to_open() -> None:
    breaker = CircuitBreaker(
        key="gemini",
        failure_threshold=3,
        failures=5,
        state=CircuitBreakerState.HALF_OPEN,
    )

    breaker.record_failure()

    assert breaker.failures == 6
    assert breaker.state == CircuitBreakerState.OPEN
    assert breaker.last_failure_time > 0
    assert breaker.retry_after == 60 * (2**5)


def test_effective_retry_seconds_matches_persisted_retry_after() -> None:
    """After failures, ``retry_after`` is the cooldown window; ``effective_retry_seconds()`` mirrors it."""
    b1 = CircuitBreaker(key="a", failure_threshold=99, retry_after=60, failures=1)
    b2 = CircuitBreaker(key="b", failure_threshold=99, retry_after=120, failures=2)
    b3 = CircuitBreaker(key="c", failure_threshold=99, retry_after=240, failures=3)

    assert b1.effective_retry_seconds() == b1.retry_after == 60
    assert b2.effective_retry_seconds() == b2.retry_after == 120
    assert b3.effective_retry_seconds() == b3.retry_after == 240


def test_record_failure_updates_retry_after_to_computed_cooldown() -> None:
    breaker = CircuitBreaker(key="gemini", failure_threshold=10, retry_after=30)

    breaker.record_failure()
    assert breaker.failures == 1
    assert breaker.retry_after == 30 * (2**0)

    breaker.record_failure()
    assert breaker.failures == 2
    assert breaker.retry_after == 30 * (2**1)
    assert breaker.effective_retry_seconds() == breaker.retry_after


def test_can_retry_returns_false_before_retry_window() -> None:
    now = datetime.now(UTC).timestamp()
    breaker = CircuitBreaker(
        key="gemini",
        failure_threshold=3,
        retry_after=120,
        failures=3,
        state=CircuitBreakerState.OPEN,
        last_failure_time=int(now) - 5,
    )

    assert breaker.effective_retry_seconds() == breaker.retry_after == 120

    assert breaker.can_retry() is False
    assert breaker.state == CircuitBreakerState.OPEN


def test_can_retry_switches_to_half_open_after_retry_window() -> None:
    now = datetime.now(UTC).timestamp()
    breaker = CircuitBreaker(
        key="gemini",
        failure_threshold=3,
        retry_after=1,
        failures=3,
        state=CircuitBreakerState.OPEN,
        last_failure_time=int(now) - 100,
    )

    assert breaker.effective_retry_seconds() == breaker.retry_after == 1

    assert breaker.can_retry() is True
    assert breaker.state == CircuitBreakerState.HALF_OPEN


def test_record_success_closes_breaker_after_half_open_success() -> None:
    breaker = CircuitBreaker(
        key="gemini",
        failure_threshold=3,
        failures=4,
        state=CircuitBreakerState.HALF_OPEN,
        last_failure_time=123,
    )

    breaker.record_success()

    assert breaker.state == CircuitBreakerState.CLOSED
    assert breaker.failures == 0
    assert breaker.last_failure_time == 0
    assert breaker.retry_after == BASE_RETRY_AFTER
    assert breaker.effective_retry_seconds() == breaker.retry_after
