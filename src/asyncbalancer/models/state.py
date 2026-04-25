from dataclasses import dataclass

from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from asyncbalancer.models.resource import ResourceUnitUsage
from asyncbalancer.models.resource import ResourceUnitCosts

@dataclass 
class ProviderState:
    name: str
    score: float
    circuit_breaker: CircuitBreaker
    resource_units: dict[str, ResourceUnitUsage]

    def is_available(self) -> bool:
        return (self.circuit_breaker.state in [CircuitBreakerState.CLOSED, CircuitBreakerState.HALF_OPEN] 
            or self.circuit_breaker.can_retry())

    def record_success(self):
        self.circuit_breaker.record_success()

    def record_failure(self):
        self.circuit_breaker.record_failure()

    def reserve_capacity(self, costs: ResourceUnitCosts) -> bool:
        updated = False
        for key, cost in costs.costs.items():
            if cost.key not in self.resource_units:
                continue

            self.resource_units[cost.key].reserve(cost.amount)
            updated = True

        return updated

    def release_capacity(self, costs: ResourceUnitCosts) -> bool:
        updated = False
        for key, cost in costs.costs.items():
            if cost.key not in self.resource_units:
                continue

            self.resource_units[cost.key].release(cost.amount)

            updated = True

        return updated

    def record_costs(self, costs: ResourceUnitCosts) -> bool:
        updated = False
        for key, cost in costs.costs.items():
            if cost.key not in self.resource_units:
                continue

            self.resource_units[cost.key].record_cost(cost.amount)

            updated = True

        return updated

    def costs_exceed_capacity(self, costs: ResourceUnitCosts) -> bool:
        for key, cost in costs.costs.items():
            if key not in self.resource_units:
                continue

            resource_unit = self.resource_units[key]

            if resource_unit.reserved + resource_unit.used + cost.amount > resource_unit.capacity:
                return True

        return False