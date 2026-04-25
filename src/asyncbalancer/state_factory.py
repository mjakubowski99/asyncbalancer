from asyncbalancer.config import get_config
from asyncbalancer.models.state import ProviderState
from asyncbalancer.models.circuit_breaker import CircuitBreaker, CircuitBreakerState
from asyncbalancer.models.resource import ResourceUnitUsage
from datetime import datetime

class StateFactory:
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
                ttl=resource['initial_ttl'],
            ) for resource in resources},
        )