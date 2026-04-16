from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from datetime import UTC


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

    def can_retry(self) -> bool:
        now = datetime.now(UTC).timestamp()
        if now - self.last_failure_time < self.retry_after:
            return False

        # Cooldown elapsed: allow one probe request in HALF_OPEN state.
        self.state = CircuitBreakerState.HALF_OPEN
        print(f"[{self.key}] Retry window elapsed. State set to HALF_OPEN.")
        return True

    def record_failure(self):
        now = datetime.now(UTC).timestamp()
        self.failures += 1

        if self.state == CircuitBreakerState.OPEN:
            # Keep it open and extend cooldown on every new failure.
            self.last_failure_time = now
            print(f"[{self.key}] Circuit OPEN. Failure recorded.")
            return

        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
            self.last_failure_time = now
            print(f"[{self.key}] HALF_OPEN failed. State set to OPEN.")
            return

        print(f"[{self.key}] Failure recorded. Total failures: {self.failures}")
        if self.failures >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.last_failure_time = now
            print(f"[{self.key}] Circuit tripped! State set to OPEN.")

    def record_success(self):
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.reset()
            print(f"[{self.key}] HALF_OPEN success. Circuit reset to CLOSED.")
        elif self.state == CircuitBreakerState.CLOSED:
            self.failures = 0
            print(f"[{self.key}] Success recorded. Failures reset to 0.")

    def reset(self):
        self.failures = 0
        self.state = CircuitBreakerState.CLOSED
        self.last_failure_time = 0