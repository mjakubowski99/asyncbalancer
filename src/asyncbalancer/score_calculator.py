from asyncbalancer.models.client import ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCosts


class ProviderScoreCalculator:
    RESOURCE_WEIGHT = 0.8
    LATENCY_WEIGHT = 0.2
    RESOURCE_SCALE = 200.0
    LATENCY_SCALE_MS = 1000.0
    MIN_SCORE = 5.0
    EMA_ALPHA = 0.2
    # Applied when the provider returns ``success=False`` (and optionally again for timeout-like errors).
    TIMEOUT_PENALTY = 0.7
    RECOVERY_BOOST = 1.1
    RECOVERY_THRESHOLD = 5.0

    @staticmethod
    def _error_suggests_timeout(error: str | None) -> bool:
        if not error:
            return False
        lowered = error.lower()
        return any(
            token in lowered
            for token in ("timeout", "timed out", "time out", "deadline", "504", "gateway timeout")
        )

    def calculate(
        self,
        response: ProviderResponse,
        actual_costs: ResourceUnitCosts,
        previous_score: float | None = None,
    ) -> float:
        total_usage = sum(max(0.0, float(cost.amount)) for cost in actual_costs.costs.values())
        latency_ms = max(0.0, float(response.latency))

        # --- base score ---
        resource_score = 1.0 / (1.0 + (total_usage / self.RESOURCE_SCALE))
        latency_score = 1.0 / (1.0 + (latency_ms / self.LATENCY_SCALE_MS))
        raw_score = 100.0 * (
            (self.RESOURCE_WEIGHT * resource_score)
            + (self.LATENCY_WEIGHT * latency_score)
        )

        if not response.success:
            raw_score *= self.TIMEOUT_PENALTY
            if self._error_suggests_timeout(response.error):
                raw_score *= self.TIMEOUT_PENALTY

        if previous_score is None:
            return max(self.MIN_SCORE, min(100.0, raw_score))

        smoothed_score = (
            self.EMA_ALPHA * raw_score
            + (1.0 - self.EMA_ALPHA) * previous_score
        )

        if raw_score - previous_score > self.RECOVERY_THRESHOLD:
            smoothed_score = min(100.0, smoothed_score * self.RECOVERY_BOOST)

        return max(self.MIN_SCORE, min(100.0, smoothed_score))
