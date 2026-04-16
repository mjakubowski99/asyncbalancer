
from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker
from asyncbalancer.models.resource import ResourceUnitUsage
from asyncbalancer.models.resource import ResourceUnitCosts
from asyncbalancer.models.resource import ResourceUnitCost
from asyncbalancer.models.circuit_breaker import CircuitBreakerState

from datetime import datetime, UTC

import pytest 

@pytest.fixture
def state() -> ProviderState:
    return ProviderState(
        name="test",
        score=0.0,
        circuit_breaker=CircuitBreaker(
            key="test",
            state=CircuitBreakerState.OPEN,
            failures=0,
            failure_threshold=3,
        ),
        resource_units={
            "tpm": ResourceUnitUsage(
                key="tpm",
                capacity=100,
                weight=1,
                created_at=datetime.now(UTC).timestamp(),
                ttl=3600,
                used=20,
                reserved=10,
            ),
        },
    )

@pytest.fixture
def state_with_many_units() -> ProviderState:
    return ProviderState(
        name="test",
        score=0.0,
        circuit_breaker=CircuitBreaker(
            key="test",
            state=CircuitBreakerState.OPEN,
            failures=0,
            failure_threshold=3,
        ),
        resource_units={
            "tpm": ResourceUnitUsage(
                key="tpm",
                capacity=100,
                weight=1,
                created_at=datetime.now(UTC).timestamp(),
                ttl=3600,
                used=20,
                reserved=10,
            ),
            "tpm2": ResourceUnitUsage(
                key="tpm2",
                capacity=100,
                weight=1,
                created_at=datetime.now(UTC).timestamp(),
                ttl=3600,
                used=40,
                reserved=20,
            ),
        },
    )



@pytest.mark.asyncio
async def test_reserve_capacity_updates_usage(state: ProviderState):
    costs = ResourceUnitCosts(
        costs={
            "tpm": ResourceUnitCost(
                key="tpm",
                amount=20,
            ),
        },
    )

    state.reserve_capacity(costs)

    assert state.resource_units["tpm"].reserved == 10 + 20

@pytest.mark.asyncio
async def test_release_capacity_releases_reserved_capacity(state: ProviderState):
    costs = ResourceUnitCosts(
        costs={
            "tpm": ResourceUnitCost(
                key="tpm",
                amount=10,
            ),
        },
    )

    previous_used = state.resource_units["tpm"].used
    previous_reserved = state.resource_units["tpm"].reserved

    state.release_capacity(costs)

    assert state.resource_units["tpm"].reserved == previous_reserved - 10
    assert state.resource_units["tpm"].used == previous_used

@pytest.mark.asyncio
async def test_record_costs_updates_usage(state: ProviderState):
    costs = ResourceUnitCosts(
        costs={
            "tpm": ResourceUnitCost(
                key="tpm",
                amount=10,
            ),
        },
    )

    previous_used = state.resource_units["tpm"].used
    previous_reserved = state.resource_units["tpm"].reserved

    state.record_costs(costs)

    assert state.resource_units["tpm"].reserved == previous_reserved 
    assert state.resource_units["tpm"].used == previous_used + 10

@pytest.mark.asyncio
async def test_costs_exceeds_capacity_return_true_if_cost_to_high(state: ProviderState):
    costs = ResourceUnitCosts(
        costs={
            "tpm": ResourceUnitCost(
                key="tpm",
                amount=200,
            ),
        },
    )
    assert state.costs_exceed_capacity(costs) is True

@pytest.mark.asyncio
async def test_costs_exceeds_capacity_return_false_if_cost_is_okay(state: ProviderState):
    costs = ResourceUnitCosts(
        costs={
            "tpm": ResourceUnitCost(
                key="tpm",
                amount=50,
            ),
        },
    )
    assert state.costs_exceed_capacity(costs) is False

@pytest.mark.asyncio
async def test_costs_exceeds_capacity_multiple_units_return_false_if_cost_is_okay(state_with_many_units: ProviderState):
    costs = ResourceUnitCosts(
        costs={
            "tpm": ResourceUnitCost(
                key="tpm2",
                amount=5,
            ),
        },
    )
    assert state_with_many_units.costs_exceed_capacity(costs) is False