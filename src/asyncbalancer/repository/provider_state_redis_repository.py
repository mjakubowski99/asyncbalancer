from asyncbalancer.repository.istate_repository import IStateRepository
from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from redis.asyncio import Redis
from dataclasses import asdict
from asyncbalancer.models.resource import ResourceUnitUsage
from datetime import datetime
from enum import Enum
from datetime import UTC

def custom_asdict_factory(data):

    def convert_value(obj):
        if isinstance(obj, Enum):
            return obj.value
        return obj

    return dict((k, convert_value(v)) for k, v in data)

class ProviderStateRedisRepository(IStateRepository):

    def __init__(
        self, 
        host: str,
        port: int = 6379,
        db: int = 0,
    ):
        self._client: Redis = Redis(host=host, port=port, db=db)

    async def lock(self, key: str) -> bool:
        return bool(await self._client.set(f'lock:{key}', '1', ex=10, nx=True))

    async def unlock(self, key: str) -> bool:
        return bool(await self._client.delete(f'lock:{key}'))

    async def save_state(self, state: ProviderState) -> bool:
        key = self._get_key(state.name)

        async with self._client.pipeline() as pipe:
            pipe.zadd(f'providers_by_score', {state.name: state.score})
            pipe.json().set(key, "$", asdict(state, dict_factory=custom_asdict_factory))

            await pipe.execute()

        return True

    async def remove_state(self, key: str) -> bool:
        key = self._get_key(key)
        return bool(await self._client.delete(key))

    async def get_state(self, key: str) -> ProviderState:
        original_key = key

        key = self._get_key(key)

        state = await self._client.json().get(key, "$")

        if state is None or len(state) == 0:
            return None

        state = state[0]

        state = ProviderState(
            name=original_key,
            score=state["score"],
            circuit_breaker=CircuitBreaker(
                key=state["circuit_breaker"]["key"],
                state=CircuitBreakerState(state["circuit_breaker"]["state"]),
                failures=state["circuit_breaker"]["failures"],
                failure_threshold=state["circuit_breaker"]["failure_threshold"],
            ),
            resource_units={key: ResourceUnitUsage(**value) for key, value in state["resource_units"].items()},
        )

        for key, resource_unit in state.resource_units.items():
            if resource_unit.created_at + resource_unit.ttl < datetime.now(UTC).timestamp():
                state.resource_units[key].used = 0
                state.resource_units[key].reserved = 0
                state.resource_units[key].created_at = datetime.now(UTC).timestamp()

        return state

    async def get_with_lowest_score(self, limit: int = 5) -> list[str]:
        top_providers = await self._client.zrevrange("providers_by_score", 0, 100)

        top_providers = top_providers[:limit]

        top_providers = [p.decode('utf-8') for p in top_providers]

        return top_providers

    def _get_key(self, key: str) -> str:
        return f"provider_state:{key}:data"