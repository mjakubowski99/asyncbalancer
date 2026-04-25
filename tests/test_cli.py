from datetime import datetime, UTC

import pytest

import asyncbalancer.cli as cli
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from asyncbalancer.models.resource import ResourceUnitUsage
from asyncbalancer.models.state import ProviderState


class _InMemoryRepo:
    def __init__(self, state: ProviderState):
        self._state = state

    async def lock(self, key: str) -> bool:
        return True

    async def unlock(self, key: str) -> bool:
        return True

    async def get_state(self, key: str) -> ProviderState | None:
        return self._state if self._state.name == key else None

    async def save_state(self, state: ProviderState) -> bool:
        self._state = state
        return True

    async def remove_state(self, key: str) -> bool:
        if self._state and self._state.name == key:
            self._state = None
            return True
        return False


def _build_state(period: str, timezone: str, created_at: float) -> ProviderState:
    return ProviderState(
        name="gemini",
        score=0.0,
        circuit_breaker=CircuitBreaker(
            key="gemini",
            state=CircuitBreakerState.CLOSED,
            failures=0,
            failure_threshold=3,
        ),
        resource_units={
            "rpm": ResourceUnitUsage(
                key="rpm",
                capacity=100,
                weight=1,
                created_at=created_at,
                ttl=3600,
                period=period,
                timezone=timezone,
                used=10,
                reserved=2,
            )
        },
    )


@pytest.mark.asyncio
async def test_sync_config_resets_created_at_when_period_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    old_created_at = datetime.now(UTC).timestamp() - 5000
    current_state = _build_state(period="hourly", timezone="UTC", created_at=old_created_at)
    template_state = _build_state(
        period="daily",
        timezone="Europe/Warsaw",
        created_at=datetime.now(UTC).timestamp(),
    )

    repo = _InMemoryRepo(current_state)

    class _StateFactoryMock:
        def get_providers(self) -> list[str]:
            return ["gemini"]

        def create(self, provider: str) -> ProviderState:
            assert provider == "gemini"
            return template_state

    monkeypatch.setattr(cli, "StateFactory", lambda: _StateFactoryMock())
    monkeypatch.setattr(cli.RepositoryRegistry, "create", lambda: repo)

    exit_code = await cli.sync_config(provider="gemini")

    assert exit_code == 0
    updated = await repo.get_state("gemini")
    assert updated is not None
    assert updated.resource_units["rpm"].period == "daily"
    assert updated.resource_units["rpm"].timezone == "Europe/Warsaw"
    assert updated.resource_units["rpm"].created_at > old_created_at


@pytest.mark.asyncio
async def test_reset_state_creates_state_with_period_and_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    old_created_at = datetime.now(UTC).timestamp() - 5000
    current_state = _build_state(period="hourly", timezone="UTC", created_at=old_created_at)
    template_state = _build_state(
        period="daily",
        timezone="Europe/Warsaw",
        created_at=datetime.now(UTC).timestamp(),
    )

    repo = _InMemoryRepo(current_state)

    class _StateFactoryMock:
        def get_providers(self) -> list[str]:
            return ["gemini"]

        def create(self, provider: str) -> ProviderState:
            assert provider == "gemini"
            return template_state

    monkeypatch.setattr(cli, "StateFactory", lambda: _StateFactoryMock())
    monkeypatch.setattr(cli.RepositoryRegistry, "create", lambda: repo)

    exit_code = await cli.reset_state(provider="gemini")

    assert exit_code == 0
    updated = await repo.get_state("gemini")
    assert updated is not None
    assert updated.resource_units["rpm"].period == "daily"
    assert updated.resource_units["rpm"].timezone == "Europe/Warsaw"
    assert updated.resource_units["rpm"].created_at > old_created_at
