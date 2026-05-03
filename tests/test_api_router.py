from asyncbalancer.provider_factory import ProviderFactory
from asyncbalancer.models.client import ProviderRequest, ProviderResponse
from tests.fakes.in_memory_provider import SuccessfulInMemoryProvider, UnsuccessfulInMemoryProvider
from asyncbalancer.repository.provider_state_redis_repository import ProviderStateRedisRepository
from asyncbalancer.state_factory import StateFactory
from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from asyncbalancer.models.resource import ResourceUnitUsage
from datetime import datetime, UTC

from asyncbalancer.router import ApiRouter
from asyncbalancer.score_calculator import ProviderScoreCalculator
from unittest.mock import AsyncMock, MagicMock, patch
import random

import pytest


class ExplodingProvider(SuccessfulInMemoryProvider):
    """``request`` raises like a failing downstream API after capacity was reserved."""

    async def request(self, request):
        raise RuntimeError("api down")


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
async def exploding_router() -> ApiRouter:
    router = ApiRouter()

    factory_mock = MagicMock(spec=ProviderFactory)
    factory_mock.create.return_value = ExplodingProvider(name="exploding")

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_providers.return_value = ["exploding"]
    state_factory.get_tier_fallback_chain.return_value = [None]
    state_factory.provider_supports_tier.return_value = True
    state_factory.create.return_value = ProviderState(
        name="exploding",
        score=0.0,
        circuit_breaker=CircuitBreaker(
            key="exploding",
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
            ),
        },
    )

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
async def test_router_releases_redis_lock_after_request(
    successful_router: ApiRouter,
    redis_repo: ProviderStateRedisRepository,
) -> None:
    """``_locked_state`` must ``unlock`` so ``lock:<name>`` is removed; otherwise the next request would spin or time out."""
    lock_key = "lock:successful"
    request = ProviderRequest(payload={"prompt": "hello"})

    await successful_router.request(request)
    assert await redis_repo._client.exists(lock_key) == 0

    await successful_router.request(request)
    assert await redis_repo._client.exists(lock_key) == 0


@pytest.mark.asyncio
async def test_router_releases_redis_lock_when_provider_request_raises(
    exploding_router: ApiRouter,
    redis_repo: ProviderStateRedisRepository,
) -> None:
    """After ``provider.request`` raises, the failure path must still ``unlock`` the Redis lock key."""
    lock_key = "lock:exploding"
    request = ProviderRequest(payload={"prompt": "hello"})

    with pytest.raises(RuntimeError, match="api down"):
        await exploding_router.request(request, tries=1)

    assert await redis_repo._client.exists(lock_key) == 0


@pytest.mark.asyncio
async def test_router_falls_back_to_next_provider_when_first_api_raises(
    redis_repo: ProviderStateRedisRepository,
) -> None:
    """First ranked provider runs ``ExplodingProvider``; after one failure its breaker opens, next ``request`` try skips it and uses the healthy provider."""
    fragile = ProviderState(
        name="fragile",
        score=100.0,
        circuit_breaker=CircuitBreaker(
            key="fragile",
            state=CircuitBreakerState.CLOSED,
            failures=0,
            failure_threshold=1,
        ),
        resource_units={
            "tpm": ResourceUnitUsage(
                key="tpm",
                capacity=100_000,
                weight=1,
                created_at=datetime.now(UTC).timestamp(),
                ttl=3600,
                used=0,
            ),
        },
    )
    stable = ProviderState(
        name="stable",
        score=50.0,
        circuit_breaker=CircuitBreaker(
            key="stable",
            state=CircuitBreakerState.CLOSED,
            failures=0,
            failure_threshold=3,
        ),
        resource_units={
            "tpm": ResourceUnitUsage(
                key="tpm",
                capacity=100_000,
                weight=1,
                created_at=datetime.now(UTC).timestamp(),
                ttl=3600,
                used=0,
            ),
        },
    )
    await redis_repo.save_state(fragile)
    await redis_repo.save_state(stable)

    router = ApiRouter()
    factory_mock = MagicMock(spec=ProviderFactory)
    factory_mock.create.side_effect = lambda name: (
        ExplodingProvider(name=name) if name == "fragile" else SuccessfulInMemoryProvider(name=name)
    )

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_providers.return_value = ["fragile", "stable"]
    state_factory.get_tier_fallback_chain.return_value = [None]
    state_factory.provider_supports_tier.return_value = True
    state_factory.create.side_effect = lambda name: fragile if name == "fragile" else stable

    router.provider_factory = factory_mock
    router.state_factory = state_factory

    request = ProviderRequest(payload={"prompt": "hello"})
    with patch("asyncbalancer.router.asyncio.sleep", new_callable=AsyncMock):
        response = await router.request(request, tries=3)

    assert response.success is True

    fragile_after = await redis_repo.get_state("fragile")
    stable_after = await redis_repo.get_state("stable")
    assert fragile_after.circuit_breaker.state == CircuitBreakerState.OPEN
    assert fragile_after.circuit_breaker.failures >= 1
    assert stable_after.circuit_breaker.state == CircuitBreakerState.CLOSED
    assert stable_after.resource_units["tpm"].used == 20


@pytest.mark.asyncio
async def test_router_saves_score_when_unsuccessful(unsuccessful_router: ApiRouter, redis_repo: ProviderStateRedisRepository) -> ApiRouter:
    request = ProviderRequest(payload={'prompt': 'Hello, world!'})

    response = await unsuccessful_router.request(request, tries=1)

    state = await redis_repo.get_state('unsuccessful')

    assert not response.success
    assert state.circuit_breaker.state == CircuitBreakerState.OPEN
    assert state.circuit_breaker.failures == 1


@pytest.mark.asyncio
async def test_router_lowers_score_when_api_returns_unsuccessful(
    unsuccessful_router: ApiRouter,
    redis_repo: ProviderStateRedisRepository,
) -> None:
    """Failed HTTP-style response applies ``ProviderScoreCalculator`` failure penalty to ``state.score``."""
    initial_score = 90.0
    seeded = ProviderState(
        name="unsuccessful",
        score=initial_score,
        circuit_breaker=CircuitBreaker(
            key="unsuccessful",
            state=CircuitBreakerState.CLOSED,
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
            ),
        },
    )
    await redis_repo.save_state(seeded)

    request = ProviderRequest(payload={"prompt": "hello"})
    response = await unsuccessful_router.request(request, tries=1)

    assert response.success is False
    state = await redis_repo.get_state("unsuccessful")
    expected = max(
        ProviderScoreCalculator.MIN_SCORE,
        min(100.0, initial_score * ProviderScoreCalculator.FAILURE_PENALTY),
    )
    assert state.score == expected
    assert state.score < initial_score


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


def _ok_response() -> ProviderResponse:
    return ProviderResponse(success=True, data={}, latency=1, error=None)


def _fail_response() -> ProviderResponse:
    return ProviderResponse(success=False, data={}, latency=1, error="err")


@pytest.mark.asyncio
async def test_request_returns_immediately_on_success() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "x"})
    with (
        patch.object(router, "_ApiRouter__make_request", new_callable=AsyncMock) as make,
        patch("asyncbalancer.router.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
    ):
        make.return_value = _ok_response()
        result = await router.request(request, tries=3)

    assert result.success is True
    assert make.await_count == 1
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_retries_on_failure_then_succeeds() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "x"})
    with (
        patch.object(router, "_ApiRouter__make_request", new_callable=AsyncMock) as make,
        patch("asyncbalancer.router.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
    ):
        make.side_effect = [_fail_response(), _fail_response(), _ok_response()]
        result = await router.request(request, tries=5)

    assert result.success is True
    assert make.await_count == 3
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_request_retries_on_exception_then_succeeds() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "x"})
    with (
        patch.object(router, "_ApiRouter__make_request", new_callable=AsyncMock) as make,
        patch("asyncbalancer.router.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
    ):
        make.side_effect = [RuntimeError("down"), _ok_response()]
        result = await router.request(request, tries=3)

    assert result.success is True
    assert make.await_count == 2
    assert sleep_mock.await_count == 1


@pytest.mark.asyncio
async def test_request_raises_after_exhausting_tries_on_failures() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "x"})
    with (
        patch.object(router, "_ApiRouter__make_request", new_callable=AsyncMock) as make,
        patch("asyncbalancer.router.asyncio.sleep", new_callable=AsyncMock),
    ):
        make.return_value = _fail_response()
        await router.request(request, tries=3)

    assert make.await_count == 3


@pytest.mark.asyncio
async def test_request_raises_when_elapsed_time_exceeds_timeout() -> None:
    router = ApiRouter()
    request = ProviderRequest(payload={"prompt": "x"})
    with (
        patch.object(router, "_ApiRouter__make_request", new_callable=AsyncMock) as make,
        patch("asyncbalancer.router.time.time", side_effect=[1000, 20000]),
        patch("asyncbalancer.router.asyncio.sleep", new_callable=AsyncMock),
    ):
        make.return_value = _fail_response()
        with pytest.raises(Exception, match="Api router timed out"):
            await router.request(request, tries=2, timeout_seconds=10)

    assert make.await_count == 1