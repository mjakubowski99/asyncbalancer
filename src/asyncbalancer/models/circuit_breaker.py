from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from datetime import UTC

_COOLDOWN_EXPONENT_CAP = 10
_MAX_COOLDOWN_SECONDS = 86400


class CircuitBreakerState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    key: str
    failure_threshold: int
    retry_after: int = 60
    failures: int = 0
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    last_failure_time: int = 0

    def effective_retry_seconds(self) -> int:
        """Cooldown after a failure: ``retry_after`` × 2ⁿ where n grows with ``failures`` (capped)."""
        exp = min(_COOLDOWN_EXPONENT_CAP, max(0, self.failures - 1))
        return min(_MAX_COOLDOWN_SECONDS, int(self.retry_after) * (2**exp))

    def can_retry(self) -> bool:
        now = datetime.now(UTC).timestamp()

        if now - self.last_failure_time < self.effective_retry_seconds():
            return False

        # Cooldown elapsed: allow one probe request in HALF_OPEN state.
        self.state = CircuitBreakerState.HALF_OPEN
        return True

    def record_failure(self):
        now = datetime.now(UTC).timestamp()
        self.failures += 1

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

    def reset(self):
        self.failures = 0
        self.state = CircuitBreakerState.CLOSED
        self.last_failure_time = 0
