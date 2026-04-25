from asyncbalancer.provider_factory import ProviderFactory
from asyncbalancer.models.client import ProviderRequest
from tests.fakes.in_memory_provider import SuccessfulInMemoryProvider, UnsuccessfulInMemoryProvider
from asyncbalancer.repository.provider_state_redis_repository import ProviderStateRedisRepository
from asyncbalancer.state_factory import StateFactory
from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from asyncbalancer.models.resource import ResourceUnitUsage
from datetime import datetime, UTC

from asyncbalancer.router import ApiRouter
from unittest.mock import AsyncMock, MagicMock
import random

import pytest

@pytest.fixture
async def successful_router() -> ApiRouter:
    router = ApiRouter()

    factory_mock = MagicMock(spec=ProviderFactory)
    factory_mock.create.return_value = SuccessfulInMemoryProvider(name="successful")

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_providers.return_value = ["successful"]
    state_factory.get_tier_fallback_chain.return_value = [None]
    state_factory.provider_supports_tier.return_value = True
    state_factory.create.return_value = ProviderState(
        name="successful", 
        score=0.0, 
        circuit_breaker=CircuitBreaker(
            key="successful", 
            state=CircuitBreakerState.OPEN, 
            failures=0, 
            failure_threshold=3
        ), resource_units={
            "tpm": ResourceUnitUsage(key="tpm", capacity=100, weight=1, created_at=datetime.now(UTC).timestamp(), ttl=3600),
        })

    router.provider_factory = factory_mock
    router.state_factory = state_factory

    return router

@pytest.fixture
async def unsuccessful_router() -> ApiRouter:
    router = ApiRouter()

    factory_mock = MagicMock(spec=ProviderFactory)
    factory_mock.create.return_value = UnsuccessfulInMemoryProvider(name="unsuccessful")

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_providers.return_value = ["unsuccessful"]
    state_factory.get_tier_fallback_chain.return_value = [None]
    state_factory.provider_supports_tier.return_value = True
    state_factory.create.return_value = ProviderState(
        name="unsuccessful", 
        score=0.0, 
        circuit_breaker=CircuitBreaker(
            key="unsuccessful", 
            state=CircuitBreakerState.OPEN, 
            failures=0, 
            failure_threshold=1
        ), resource_units={
            "tpm": ResourceUnitUsage(key="tpm", capacity=100, weight=1, created_at=datetime.now(UTC).timestamp(), ttl=3600),
        })

    router.provider_factory = factory_mock
    router.state_factory = state_factory

    return router

@pytest.fixture
async def successful_router_with_retry_after() -> ApiRouter:
    from datetime import timedelta

    router = ApiRouter()

    factory_mock = MagicMock(spec=ProviderFactory)
    factory_mock.create.return_value = SuccessfulInMemoryProvider(name="successful")

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_providers.return_value = ["successful"]
    state_factory.get_tier_fallback_chain.return_value = [None]
    state_factory.provider_supports_tier.return_value = True
    state_factory.create.return_value = ProviderState(
        name="successful", 
        score=0.0, 
        circuit_breaker=CircuitBreaker(
            key="successful", 
            state=CircuitBreakerState.OPEN, 
            failures=3, 
            failure_threshold=3,
            retry_after=60,
            last_failure_time=(datetime.now(UTC) - timedelta(seconds=80)).timestamp(),
        ), resource_units={
            "tpm": ResourceUnitUsage(key="tpm", capacity=100, weight=1, created_at=datetime.now(UTC).timestamp(), ttl=3600),
        })

    router.provider_factory = factory_mock
    router.state_factory = state_factory
    return router

@pytest.fixture
async def redis_repo() -> ProviderStateRedisRepository:
    repo = ProviderStateRedisRepository(host="localhost", port=6379, db=0)
    yield repo
    await repo._client.flushdb()

def _build_state(
    name: str,
    score: float,
    breaker_state: CircuitBreakerState = CircuitBreakerState.CLOSED,
    used: int = 0,
    capacity: int = 10_000,
) -> ProviderState:
    return ProviderState(
        name=name,
        score=score,
        circuit_breaker=CircuitBreaker(
            key=name,
            state=breaker_state,
            failures=0,
            failure_threshold=3,
            retry_after=60,
            last_failure_time=datetime.now(UTC).timestamp(),
        ),
        resource_units={
            "tpm": ResourceUnitUsage(
                key="tpm",
                capacity=capacity,
                weight=1,
                created_at=datetime.now(UTC).timestamp(),
                ttl=3600,
                used=used,
            ),
        },
    )

@pytest.mark.asyncio
async def test_router_saves_score_when_successful(successful_router: ApiRouter, redis_repo: ProviderStateRedisRepository) -> ApiRouter:
    request = ProviderRequest(payload={'prompt': 'Hello, world!'})

    response = await successful_router.request(request)

    state = await redis_repo.get_state('successful')

    assert response.success
    assert state is not None
    assert state.resource_units["tpm"].reserved == 0
    assert state.resource_units["tpm"].used == 20


@pytest.mark.asyncio
async def test_router_saves_score_when_unsuccessful(unsuccessful_router: ApiRouter, redis_repo: ProviderStateRedisRepository) -> ApiRouter:
    request = ProviderRequest(payload={'prompt': 'Hello, world!'})

    response = await unsuccessful_router.request(request)

    state = await redis_repo.get_state('unsuccessful')

    assert not response.success
    assert state.circuit_breaker.state == CircuitBreakerState.OPEN
    assert state.circuit_breaker.failures == 1


@pytest.mark.asyncio
async def test_router_tries_model_when_retry_after_is_reached(successful_router_with_retry_after: ApiRouter, redis_repo: ProviderStateRedisRepository) -> ApiRouter:
    request = ProviderRequest(payload={'prompt': 'Hello, world!'})

    response = await successful_router_with_retry_after.request(request)

    state = await redis_repo.get_state('successful')

    assert response.success
    assert state.circuit_breaker.state == CircuitBreakerState.CLOSED
    assert state.circuit_breaker.failures == 0

@pytest.mark.asyncio
async def test_router_when_all_providers_are_unavailable_try_any_random(successful_router_with_retry_after: ApiRouter, redis_repo: ProviderStateRedisRepository) -> ApiRouter:
    request = ProviderRequest(payload={'prompt': 'Hello, world!'})

    response = await successful_router_with_retry_after.request(request)

    state = await redis_repo.get_state('successful')

    assert response.success
    assert state.circuit_breaker.state == CircuitBreakerState.CLOSED
    assert state.circuit_breaker.failures == 0

@pytest.mark.asyncio
async def test_find_best_provider_prefers_first_available_from_sorted_states() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "hello"})

    states = [
        _build_state("gemini", score=90.0),
        _build_state("chatgpt", score=70.0),
        _build_state("claude", score=50.0),
    ]

    providers = {
        "gemini": SuccessfulInMemoryProvider(name="gemini"),
        "chatgpt": SuccessfulInMemoryProvider(name="chatgpt"),
        "claude": SuccessfulInMemoryProvider(name="claude"),
    }

    router.provider_factory = MagicMock(spec=ProviderFactory)
    router.provider_factory.create.side_effect = lambda key: providers[key]

    state_by_name = {state.name: state for state in states}
    router.state_repository = MagicMock()
    router.state_repository.get_states = AsyncMock(return_value=states)
    router.state_repository.get_state = AsyncMock(side_effect=lambda key: state_by_name[key])

    selected_provider, _, selected_state = await router._find_best_provider(request, states)

    assert selected_state.name == "gemini"
    assert selected_provider.name == "gemini"

@pytest.mark.asyncio
async def test_find_best_when_all_providers_are_unavailable_try_any_random() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "hello"})

    states = [
        _build_state("gemini", score=90.0, breaker_state=CircuitBreakerState.OPEN),
    ]

    providers = {
        "gemini": UnsuccessfulInMemoryProvider(name="gemini"),
    }

    router.provider_factory = MagicMock(spec=ProviderFactory)
    router.provider_factory.create.side_effect = lambda key: providers[key]

    state_by_name = {state.name: state for state in states}
    router.state_repository = MagicMock()
    router.state_repository.get_states = AsyncMock(return_value=states)
    router.state_repository.get_state = AsyncMock(side_effect=lambda key: state_by_name[key])

    selected_provider, _, selected_state = await router._find_best_provider(request, states)

    assert selected_state.name == "gemini"
    assert selected_provider.name == "gemini"


@pytest.mark.asyncio
async def test_find_best_provider_skips_provider_when_cost_exceeds_capacity() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "hello"})

    states = [
        _build_state("gemini", score=90.0, used=9_995, capacity=10_000),
        _build_state("chatgpt", score=70.0),
        _build_state("claude", score=50.0),
    ]

    providers = {
        "gemini": SuccessfulInMemoryProvider(name="gemini"),
        "chatgpt": SuccessfulInMemoryProvider(name="chatgpt"),
        "claude": SuccessfulInMemoryProvider(name="claude"),
    }

    router.provider_factory = MagicMock(spec=ProviderFactory)
    router.provider_factory.create.side_effect = lambda key: providers[key]

    state_by_name = {state.name: state for state in states}
    router.state_repository = MagicMock()
    router.state_repository.get_states = AsyncMock(return_value=states)
    router.state_repository.get_state = AsyncMock(side_effect=lambda key: state_by_name[key])

    selected_provider, _, selected_state = await router._find_best_provider(request, states)

    assert selected_state.name == "chatgpt"
    assert selected_provider.name == "chatgpt"


@pytest.mark.asyncio
async def test_find_best_provider_uses_random_fallback_when_all_unavailable() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "hello"})

    # OPEN with fresh failure timestamp => unavailable (cannot retry yet).
    states = [
        _build_state("gemini", score=90.0, breaker_state=CircuitBreakerState.OPEN),
        _build_state("chatgpt", score=70.0, breaker_state=CircuitBreakerState.OPEN),
        _build_state("claude", score=50.0, breaker_state=CircuitBreakerState.OPEN),
    ]

    providers = {
        "gemini": SuccessfulInMemoryProvider(name="gemini"),
        "chatgpt": SuccessfulInMemoryProvider(name="chatgpt"),
        "claude": SuccessfulInMemoryProvider(name="claude"),
    }

    router.provider_factory = MagicMock(spec=ProviderFactory)
    router.provider_factory.create.side_effect = lambda key: providers[key]

    state_by_name = {state.name: state for state in states}
    router.state_repository = MagicMock()
    router.state_repository.get_states = AsyncMock(return_value=states)
    router.state_repository.get_state = AsyncMock(side_effect=lambda key: state_by_name[key])

    original_choice = random.choice
    random.choice = lambda seq: seq[2]
    try:
        selected_provider, _, selected_state = await router._find_best_provider(request, states)
    finally:
        random.choice = original_choice

    assert selected_state.name == "claude"
    assert selected_provider.name == "claude"


@pytest.mark.asyncio
async def test_router_raises_for_unregistered_provider_when_requesting() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "hello"})

    router.state_repository = MagicMock()
    router.state_repository.get_with_lowest_score = AsyncMock(return_value=[])

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_providers.return_value = ["missing_provider"]
    state_factory.get_tier_fallback_chain.return_value = [None]
    state_factory.provider_supports_tier.return_value = True
    router.state_factory = state_factory

    with pytest.raises(ValueError, match="Missing provider class registration"):
        await router.request(request)


@pytest.mark.asyncio
async def test_select_provider_uses_requested_tier_first() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "hello"}, tier="pro")

    states = [
        _build_state("pro_provider", score=90.0),
        _build_state("free_provider", score=80.0),
    ]

    providers = {
        "pro_provider": SuccessfulInMemoryProvider(name="pro_provider"),
        "free_provider": SuccessfulInMemoryProvider(name="free_provider"),
    }

    router.provider_factory = MagicMock(spec=ProviderFactory)
    router.provider_factory.create.side_effect = lambda key: providers[key]

    state_by_name = {state.name: state for state in states}
    router.state_repository = MagicMock()
    router.state_repository.get_states = AsyncMock(return_value=states)
    router.state_repository.get_state = AsyncMock(side_effect=lambda key: state_by_name[key])

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_tier_fallback_chain.return_value = ["pro", "free"]
    state_factory.provider_supports_tier.side_effect = (
        lambda provider, tier: provider == "pro_provider" if tier == "pro" else provider == "free_provider"
    )
    router.state_factory = state_factory

    ranked_provider_names = [state.name for state in states]
    selected_provider, _, selected_state = await router._select_provider_with_tier_fallback(
        request=request,
        ranked_provider_names=ranked_provider_names,
    )

    assert selected_state.name == "pro_provider"
    assert selected_provider.name == "pro_provider"


@pytest.mark.asyncio
async def test_select_provider_falls_back_to_lower_tier_when_needed() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "hello"}, tier="pro")

    states = [
        _build_state("pro_provider", score=90.0, used=9_995, capacity=10_000),
        _build_state("free_provider", score=80.0),
    ]

    providers = {
        "pro_provider": SuccessfulInMemoryProvider(name="pro_provider"),
        "free_provider": SuccessfulInMemoryProvider(name="free_provider"),
    }

    router.provider_factory = MagicMock(spec=ProviderFactory)
    router.provider_factory.create.side_effect = lambda key: providers[key]

    state_by_name = {state.name: state for state in states}
    router.state_repository = MagicMock()
    router.state_repository.get_states = AsyncMock(return_value=states)
    router.state_repository.get_state = AsyncMock(side_effect=lambda key: state_by_name[key])

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_tier_fallback_chain.return_value = ["pro", "free"]
    state_factory.provider_supports_tier.side_effect = (
        lambda provider, tier: provider == "pro_provider" if tier == "pro" else provider == "free_provider"
    )
    router.state_factory = state_factory

    ranked_provider_names = [state.name for state in states]
    selected_provider, _, selected_state = await router._select_provider_with_tier_fallback(
        request=request,
        ranked_provider_names=ranked_provider_names,
    )

    assert selected_state.name == "free_provider"
    assert selected_provider.name == "free_provider"