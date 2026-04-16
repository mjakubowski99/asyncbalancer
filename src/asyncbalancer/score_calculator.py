from asyncbalancer.models.client import ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCosts


class ProviderScoreCalculator:
    RESOURCE_WEIGHT = 0.8
    LATENCY_WEIGHT = 0.2
    RESOURCE_SCALE = 200.0
    LATENCY_SCALE_MS = 1000.0

    def calculate(self, response: ProviderResponse, actual_costs: ResourceUnitCosts) -> float:
        total_usage = sum(max(0.0, float(cost.amount)) for cost in actual_costs.costs.values())
        latency_ms = max(0.0, float(response.latency))

        # Lower usage should dominate the score.
        resource_score = 1.0 / (1.0 + (total_usage / self.RESOURCE_SCALE))
        # Latency penalizes score, but with lower weight.
        latency_score = 1.0 / (1.0 + (latency_ms / self.LATENCY_SCALE_MS))

        score = 100.0 * (
            (self.RESOURCE_WEIGHT * resource_score)
            + (self.LATENCY_WEIGHT * latency_score)
        )
        return max(0.0, min(100.0, score))