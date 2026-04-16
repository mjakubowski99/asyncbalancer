

from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker
from asyncbalancer.models.resource import ResourceUnitUsage
from asyncbalancer.models.circuit_breaker import CircuitBreakerState
from dataclasses import asdict

from asyncbalancer.repository.provider_state_redis_repository import ProviderStateRedisRepository, custom_asdict_factory
from datetime import datetime, UTC

import pytest 

@pytest.fixture
async def redis_repo() -> ProviderStateRedisRepository:
    repo = ProviderStateRedisRepository(host="localhost", port=6379, db=0)
    yield repo
    await repo._client.flushdb()

@pytest.fixture
def state() -> ProviderState:
    return ProviderState(
        name="test",
        score=20.0,
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

@pytest.fixture
def worse_score_state() -> ProviderState:
    return ProviderState(
        name="test2",
        score=10.0,
        circuit_breaker=CircuitBreaker(
            key="test2",
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

async def test_save_state_saves_state_to_redis(state: ProviderState, redis_repo: ProviderStateRedisRepository):
    await redis_repo.save_state(state)

    result = await redis_repo.get_state(state.name)

    assert asdict(result, dict_factory=custom_asdict_factory) == asdict(state, dict_factory=custom_asdict_factory)

async def test_get_state_when_ttl_is_expired(state: ProviderState, redis_repo: ProviderStateRedisRepository):
    state.resource_units["tpm"].created_at = datetime.now(UTC).timestamp() - 3700

    await redis_repo.save_state(state)

    result = await redis_repo.get_state(state.name)

    assert result.resource_units["tpm"].used == 0
    assert result.resource_units["tpm"].reserved == 0
    assert abs(result.resource_units["tpm"].created_at - datetime.now(UTC).timestamp()) <= 5

async def test_lock_locks_the_key(redis_repo: ProviderStateRedisRepository):
    assert await redis_repo.lock("test2")
    assert not (await redis_repo.lock("test2"))

async def test_unlock_unlocks_the_key(redis_repo: ProviderStateRedisRepository):
    assert await redis_repo.lock("test2")
    assert await redis_repo.unlock("test2")
    assert not (await redis_repo.unlock("test2"))


async def test_save_saves_state_score(state: ProviderState, worse_score_state: ProviderState, redis_repo: ProviderStateRedisRepository):
    await redis_repo.save_state(state)
    await redis_repo.save_state(worse_score_state)

    result = await redis_repo.get_with_lowest_score(limit=2)

    assert result == [state.name, worse_score_state.name]