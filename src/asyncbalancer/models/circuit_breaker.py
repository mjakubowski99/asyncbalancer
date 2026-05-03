from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from datetime import UTC

_COOLDOWN_EXPONENT_CAP = 10
_MAX_COOLDOWN_SECONDS = 86400
BASE_RETRY_AFTER = 60


class CircuitBreakerState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    key: str
    failure_threshold: int
    retry_after: int = BASE_RETRY_AFTER
    failures: int = 0
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    last_failure_time: int = 0

    def _computed_cooldown_seconds(self) -> int:
        exp = min(_COOLDOWN_EXPONENT_CAP, max(0, self.failures - 1))
        return min(_MAX_COOLDOWN_SECONDS, int(self.retry_after) * (2**exp))

    def effective_retry_seconds(self) -> int:
        """Persisted cooldown window (same as ``retry_after`` after ``record_failure``)."""
        return int(self.retry_after)

    def can_retry(self) -> bool:
        now = datetime.now(UTC).timestamp()

        if now - self.last_failure_time < self.retry_after:
            return False

        # Cooldown elapsed: allow one probe request in HALF_OPEN state.
        self.state = CircuitBreakerState.HALF_OPEN
        return True

    def record_failure(self):
        now = datetime.now(UTC).timestamp()
        self.failures += 1
        self.retry_after = self._computed_cooldown_seconds()

        if self.state == CircuitBreakerState.OPEN:
            self.last_failure_time = now
            return

        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
            self.last_failure_time = now
            return

        if self.failures >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.last_failure_time = now

    def record_success(self):
        if self.state in [CircuitBreakerState.HALF_OPEN, CircuitBreakerState.OPEN]:
            self.reset()
        else:
            self.failures = 0
            self.retry_after = self._computed_cooldown_seconds()

    def reset(self):
        self.failures = 0
        self.state = CircuitBreakerState.CLOSED
        self.last_failure_time = 0
        self.retry_after = BASE_RETRY_AFTER
