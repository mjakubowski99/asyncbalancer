from dataclasses import dataclass

@dataclass
class BaseResourceUnit:
    key: str
    capacity: int
    weight: int
    created_at: int
    ttl: int

@dataclass
class ResourceUnitUsage(BaseResourceUnit):
    used: int = 0
    reserved: int = 0

    def can_reserve(self, amount: int) -> bool:
        return self.used + self.reserved + amount <= self.capacity

    def reserve(self, amount: int) -> bool:
        if self.can_reserve(amount):
            self.reserved += amount
            return True
        return False

    def release(self, amount: int) -> bool:
        if self.reserved >= amount:
            self.reserved -= amount
            return True
        return False

    def record_cost(self, amount: int) -> bool:
        self.used += amount
        return True

@dataclass(frozen=True)
class ResourceUnitCost:
    key: str
    amount: float

@dataclass
class ResourceUnitCosts:
    costs: dict[str, ResourceUnitCost]

    def add(self, cost: ResourceUnitCost) -> None:
        self.costs[cost.key] = cost


