"""Concurrency-focused tests for :class:`asyncbalancer.router.ApiRouter` lock usage in ``__make_request``."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from asyncbalancer.models.client import ProviderRequest
from asyncbalancer.models.resource import ResourceUnitUsage
from asyncbalancer.models.state import ProviderState
from asyncbalancer.provider_factory import ProviderFactory
from asyncbalancer.repository.istate_repository import IStateRepository
from asyncbalancer.router import ApiRouter
from asyncbalancer.state_factory import StateFactory
from tests.fakes.in_memory_provider import SuccessfulInMemoryProvider


def _provider_state(name: str = "concurrent", *, capacity: int = 500_000) -> ProviderState:
    return ProviderState(
        name=name,
        score=0.0,
        circuit_breaker=CircuitBreaker(
            key=name,
            state=CircuitBreakerState.CLOSED,
            failures=0,
            failure_threshold=50,
        ),
        resource_units={
            "tpm": ResourceUnitUsage(
                key="tpm",
                capacity=capacity,
                weight=1,
                created_at=datetime.now(UTC).timestamp(),
                ttl=3600,
                used=0,
            ),
        },
    )


class SlowSuccessfulProvider(SuccessfulInMemoryProvider):
    """Adds delay in ``request`` so many coroutines overlap outside the state lock."""

    def __init__(self, name: str, *, delay_s: float = 0.03):
        super().__init__(name)
        self._delay_s = delay_s

    async def request(self, request):
        await asyncio.sleep(self._delay_s)
        return await super().request(request)


class LockDepthTrackingRepository(IStateRepository):
    """In-memory repo where ``lock`` / ``unlock`` use a per-key :class:`asyncio.Lock` (blocking).

    Tracks how many coroutines simultaneously hold any acquired repo lock (per key), so we can
    assert mutual exclusion for the same provider state name.
    """

    def __init__(self, state: ProviderState):
        self._states: dict[str, ProviderState] = {state.name: state}
        self._async_locks: dict[str, asyncio.Lock] = {}
        self._holders = 0
        self.max_concurrent_holders = 0

    def _async_lock(self, key: str) -> asyncio.Lock:
        return self._async_locks.setdefault(key, asyncio.Lock())

    async def lock(self, key: str) -> bool:
        await self._async_lock(key).acquire()
        self._holders += 1
        if self._holders > self.max_concurrent_holders:
            self.max_concurrent_holders = self._holders
        return True

    async def unlock(self, key: str) -> bool:
        self._holders -= 1
        self._async_lock(key).release()
        return True

    async def get_state(self, key: str) -> ProviderState:
        return self._states[key]

    async def get_states(self, keys: list[str]) -> list[ProviderState]:
        return [self._states[k] for k in keys if k in self._states]

    async def save_state(self, state: ProviderState) -> bool:
        self._states[state.name] = state
        return True

    async def remove_state(self, key: str) -> bool:
        self._states.pop(key, None)
        return True

    async def get_with_lowest_score(self, limit: int = 5) -> list[str]:
        names = sorted(self._states.keys(), key=lambda n: self._states[n].score)[:limit]
        return names


def _concurrency_router(repo: IStateRepository, provider: SuccessfulInMemoryProvider) -> ApiRouter:
    router = ApiRouter()
    router.state_repository = repo

    factory_mock = MagicMock(spec=ProviderFactory)
    factory_mock.create.return_value = provider

    state_factory = MagicMock(spec=StateFactory)
    state_factory.get_providers.return_value = [provider.name]
    state_factory.get_tier_fallback_chain.return_value = [None]
    state_factory.provider_supports_tier.return_value = True
    base = _provider_state(provider.name, capacity=500_000)
    state_factory.create.return_value = replace(base)

    router.provider_factory = factory_mock
    router.state_factory = state_factory
    return router


@pytest.mark.asyncio
async def test_make_request_serializes_per_key_lock_sections_under_concurrency() -> None:
    """Only one coroutine may hold the repo lock for a given state name at a time."""
    state = _provider_state("concurrent")
    repo = LockDepthTrackingRepository(state)
    router = _concurrency_router(repo, SlowSuccessfulProvider("concurrent", delay_s=0.04))

    n = 24
    req = ProviderRequest(payload={"prompt": "x"})

    await asyncio.gather(
        *[router._ApiRouter__make_request(req) for _ in range(n)],
    )

    assert repo.max_concurrent_holders == 1


@pytest.mark.asyncio
async def test_locked_state_raises_timeout_when_lock_never_acquired() -> None:
    router = ApiRouter()
    router.state_repository = MagicMock()
    router.state_repository.lock = AsyncMock(return_value=False)

    with pytest.raises(TimeoutError, match="Could not acquire lock for 'stale'"):
        async with router._locked_state("stale", max_retries=6, delay=0):
            pass


@pytest.mark.asyncio
async def test_unlock_runs_after_provider_error_so_next_lock_succeeds() -> None:
    """If ``provider.request`` raises, the failure path must ``unlock`` so a follow-up call is not stuck."""

    class FailsOnceProvider(SlowSuccessfulProvider):
        def __init__(self, name: str):
            super().__init__(name, delay_s=0)
            self._n = 0

        async def request(self, request):
            self._n += 1
            if self._n == 1:
                raise RuntimeError("transient downstream")
            return await super().request(request)

    state = _provider_state("concurrent")
    repo = LockDepthTrackingRepository(state)
    router = _concurrency_router(repo, FailsOnceProvider("concurrent"))

    req = ProviderRequest(payload={"prompt": "x"})
    with pytest.raises(RuntimeError, match="transient downstream"):
        await router._ApiRouter__make_request(req)

    resp = await router._ApiRouter__make_request(req)
    assert resp.success is True
    assert repo.max_concurrent_holders == 1
