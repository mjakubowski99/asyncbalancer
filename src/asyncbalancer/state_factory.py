from asyncbalancer.config import get_config
from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from asyncbalancer.models.resource import ResourceUnitUsage
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

class StateFactory:
    SUPPORTED_PERIODS = {
        "secondly",
        "minutely",
        "hourly",
        "daily",
        "weekly",
        "monthly",
        "quarterly",
        "yearly",
    }

    def get_providers(self) -> list[str]:
        providers = get_config().get('providers') or {}
        return list(providers.keys())

    def get_tier_fallback_chain(self, requested_tier: str | None) -> list[str]:
        if not requested_tier:
            return [None]

        tier = requested_tier.lower()
        tier_order = get_config().get("tier_order") or []
        tier_order = [str(item).lower() for item in tier_order]

        if not tier_order:
            return [tier]

        if tier not in tier_order:
            raise ValueError(
                f"Unknown tier: {requested_tier}. Supported tiers from config: "
                + ", ".join(tier_order)
            )

        tier_index = tier_order.index(tier)
        return list(reversed(tier_order[:tier_index + 1]))

    def provider_supports_tier(self, provider: str, tier: str | None) -> bool:
        if tier is None:
            return True
        providers = get_config().get('providers') or {}
        config = providers.get(provider) or {}
        configured_tiers = config.get("tiers")
        if not configured_tiers:
            return True
        return tier in [str(item).lower() for item in configured_tiers]

    def create(self, provider: str) -> ProviderState:
        providers = get_config().get('providers') or {}
        config = providers.get(provider) or {}
        resources = config.get('resources')

        if not isinstance(resources, list) or len(resources) == 0:
            raise ValueError(
                "Provider config is missing resources for "
                f"'{provider}'. Define 'providers.{provider}.resources' "
                "in config or external resources file."
            )

        timezone_name = self._resolve_timezone_name(provider)

        return ProviderState(
            name=provider,
            score=0.0,
            circuit_breaker=CircuitBreaker(
                key=provider,
                state=CircuitBreakerState.OPEN,
                failures=0,
                failure_threshold=3,
            ),
            resource_units={resource['name']: ResourceUnitUsage(
                key=resource['name'],
                capacity=resource['value'],
                weight=1,
                created_at=datetime.now().timestamp(),
                ttl=self._resolve_resource_ttl(provider, resource),
                period=str(resource.get("period")).lower() if resource.get("period") else None,
                timezone=timezone_name,
            ) for resource in resources},
        )

    def _resolve_resource_ttl(self, provider: str, resource: dict) -> int:
        # Backward compatibility with old schema.
        if "initial_ttl" in resource:
            return int(resource["initial_ttl"])

        period = resource.get("period")
        if not period:
            if "ttl" in resource:
                return int(resource["ttl"])
            raise ValueError(
                f"Resource '{resource.get('name', '<unknown>')}' for provider '{provider}' "
                "must define either 'period' or 'initial_ttl'."
            )

        period = str(period).lower()
        if period == "custom":
            if "ttl" not in resource:
                raise ValueError(
                    f"Resource '{resource.get('name', '<unknown>')}' for provider '{provider}' "
                    "with period='custom' requires 'ttl'."
                )
            return int(resource["ttl"])

        if period not in self.SUPPORTED_PERIODS:
            raise ValueError(
                f"Unknown period '{period}' for resource "
                f"'{resource.get('name', '<unknown>')}' in provider '{provider}'. "
                f"Supported periods: {', '.join(sorted(self.SUPPORTED_PERIODS))}, custom."
            )

        timezone_name = self._resolve_timezone_name(provider)
        timezone = self._get_timezone(timezone_name)
        return self._seconds_until_period_end(period, timezone)

    def _resolve_timezone_name(self, provider: str) -> str:
        providers = get_config().get("providers") or {}
        provider_config = providers.get(provider) or {}
        timezone_name = provider_config.get("timezone") or get_config().get("timezone") or "UTC"
        return str(timezone_name)

    def _get_timezone(self, timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Unknown timezone '{timezone_name}'. Use a valid IANA timezone, e.g. 'UTC' or 'Europe/Warsaw'."
            ) from exc

    def _seconds_until_period_end(self, period: str, timezone: ZoneInfo) -> int:
        now = datetime.now(timezone)

        if period == "secondly":
            period_end = (now + timedelta(seconds=1)).replace(microsecond=0)
        elif period == "minutely":
            period_end = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        elif period == "hourly":
            period_end = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        elif period == "daily":
            period_end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "weekly":
            days_until_next_week = 7 - now.weekday()
            period_end = (now + timedelta(days=days_until_next_week)).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        elif period == "monthly":
            if now.month == 12:
                period_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                period_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "quarterly":
            current_quarter = (now.month - 1) // 3 + 1
            next_quarter_start_month = current_quarter * 3 + 1
            if next_quarter_start_month > 12:
                period_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                period_end = now.replace(
                    month=next_quarter_start_month,
                    day=1,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
        elif period == "yearly":
            period_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            raise ValueError(f"Unsupported period '{period}'.")

        ttl_seconds = int((period_end - now).total_seconds())
        return max(ttl_seconds, 1)