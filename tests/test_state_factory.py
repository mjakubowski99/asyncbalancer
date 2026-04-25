from asyncbalancer.config import configure
from asyncbalancer.state_factory import StateFactory


def test_get_providers_returns_configured_names() -> None:
    config = configure()
    config.add(
        "providers",
        {
            "gemini": {"resources": [{"name": "tpm", "value": 10, "initial_ttl": 60}]},
            "claude": {"resources": [{"name": "tpm", "value": 10, "initial_ttl": 60}]},
        },
    )

    factory = StateFactory()
    providers = factory.get_providers()
    assert set(providers) == {"gemini", "claude"}


def test_get_tier_fallback_chain_without_requested_tier() -> None:
    configure()
    factory = StateFactory()
    assert factory.get_tier_fallback_chain(None) == [None]


def test_get_tier_fallback_chain_without_tier_order() -> None:
    configure()
    factory = StateFactory()
    assert factory.get_tier_fallback_chain("pro") == ["pro"]


def test_get_tier_fallback_chain_with_user_defined_order() -> None:
    config = configure()
    config.add("tier_order", ["basic", "plus", "vip"])
    factory = StateFactory()
    assert factory.get_tier_fallback_chain("plus") == ["plus", "basic"]

