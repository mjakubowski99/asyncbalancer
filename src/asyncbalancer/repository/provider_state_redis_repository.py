from asyncbalancer.repository.istate_repository import IStateRepository
from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from redis.asyncio import Redis
from dataclasses import asdict
from asyncbalancer.models.resource import ResourceUnitUsage
from datetime import datetime
from datetime import timedelta
from enum import Enum
from datetime import UTC
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

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
            pipe.zadd('providers_by_score', {state.name: state.score})
            pipe.json().set(key, "$", asdict(state, dict_factory=custom_asdict_factory))

            await pipe.execute()

        return True

    async def remove_state(self, key: str) -> bool:
        key = self._get_key(key)
        return bool(await self._client.delete(key))

    async def get_state(self, key: str) -> ProviderState:
        states = await self.get_states([key])
        if not states:
            return None
        return states[0]

    async def get_states(self, keys: list[str]) -> list[ProviderState]:
        if len(keys) == 0:
            return []

        redis_keys = [self._get_key(key) for key in keys]

        async with self._client.pipeline() as pipe:
            for redis_key in redis_keys:
                pipe.json().get(redis_key, "$")
            raw_states = await pipe.execute()

        states: list[ProviderState] = []
        for original_key, raw_state in zip(keys, raw_states):
            state = self._deserialize_state(original_key, raw_state)
            if state is not None:
                states.append(state)

        return states

    async def get_with_lowest_score(self, limit: int = 5) -> list[str]:
        top_providers = await self._client.zrevrange("providers_by_score", 0, 100)

        top_providers = top_providers[:limit]

        top_providers = [p.decode('utf-8') for p in top_providers]

        return top_providers

    def _get_key(self, key: str) -> str:
        return f"provider_state:{key}:data"

    def _deserialize_state(self, original_key: str, raw_state) -> ProviderState | None:
        if raw_state is None or len(raw_state) == 0:
            return None

        state_data = raw_state[0]

        state = ProviderState(
            name=original_key,
            score=state_data["score"],
            circuit_breaker=CircuitBreaker(
                key=state_data["circuit_breaker"]["key"],
                state=CircuitBreakerState(state_data["circuit_breaker"]["state"]),
                failures=state_data["circuit_breaker"]["failures"],
                failure_threshold=state_data["circuit_breaker"]["failure_threshold"],
            ),
            resource_units={key: ResourceUnitUsage(**value) for key, value in state_data["resource_units"].items()},
        )

        now_ts = datetime.now(UTC).timestamp()
        for key, resource_unit in state.resource_units.items():
            if resource_unit.period and resource_unit.period != "custom":
                timezone = self._resolve_timezone(resource_unit.timezone)
                now_local = datetime.now(timezone)
                period_start, period_end = self._get_period_window(resource_unit.period, now_local)
                created_at_local = datetime.fromtimestamp(resource_unit.created_at, timezone)

                # Recalculate TTL dynamically each read.
                resource_unit.ttl = max(int((period_end - now_local).total_seconds()), 1)

                # If saved state belongs to previous period window, reset usage.
                if created_at_local < period_start:
                    state.resource_units[key].used = 0
                    state.resource_units[key].reserved = 0
                    state.resource_units[key].created_at = now_ts
            elif resource_unit.created_at + resource_unit.ttl < now_ts:
                state.resource_units[key].used = 0
                state.resource_units[key].reserved = 0
                state.resource_units[key].created_at = now_ts

        return state

    def _resolve_timezone(self, timezone_name: str | None) -> ZoneInfo:
        tz_name = timezone_name or "UTC"
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _get_period_window(self, period: str, now: datetime) -> tuple[datetime, datetime]:
        if period == "secondly":
            start = now.replace(microsecond=0)
            end = start + timedelta(seconds=1)
        elif period == "minutely":
            start = now.replace(second=0, microsecond=0)
            end = start + timedelta(minutes=1)
        elif period == "hourly":
            start = now.replace(minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
        elif period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif period == "weekly":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        elif period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
        elif period == "quarterly":
            quarter_start_month = ((now.month - 1) // 3) * 3 + 1
            start = now.replace(
                month=quarter_start_month,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            if quarter_start_month == 10:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=quarter_start_month + 3)
        elif period == "yearly":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=start.year + 1)
        else:
            # Fallback to a one-second window for unknown period values.
            start = now
            end = now + timedelta(seconds=1)

        return start, end