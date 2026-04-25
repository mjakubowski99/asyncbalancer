from asyncbalancer.config import configure
from asyncbalancer.state_factory import StateFactory
import pytest


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


def test_create_supports_period_based_resource_with_timezone() -> None:
    config = configure()
    config.add("timezone", "UTC")
    config.add(
        "providers",
        {
            "gemini": {
                "timezone": "Europe/Warsaw",
                "resources": [{"name": "rpm", "value": 1000, "period": "hourly"}],
            }
        },
    )

    state = StateFactory().create("gemini")
    resource = state.resource_units["rpm"]

    assert resource.period == "hourly"
    assert resource.timezone == "Europe/Warsaw"
    assert 1 <= resource.ttl <= 3600


def test_create_supports_custom_period_ttl() -> None:
    config = configure()
    config.add(
        "providers",
        {
            "gemini": {
                "resources": [{"name": "rpms", "value": 100, "period": "custom", "ttl": 7200}],
            }
        },
    )

    state = StateFactory().create("gemini")
    resource = state.resource_units["rpms"]

    assert resource.period == "custom"
    assert resource.ttl == 7200


def test_create_raises_for_unknown_period() -> None:
    config = configure()
    config.add(
        "providers",
        {
            "gemini": {
                "resources": [{"name": "x", "value": 1, "period": "fortnightly"}],
            }
        },
    )

    with pytest.raises(ValueError, match="Unknown period"):
        StateFactory().create("gemini")


def test_create_raises_for_invalid_timezone() -> None:
    config = configure()
    config.add(
        "providers",
        {
            "gemini": {
                "timezone": "Mars/Phobos",
                "resources": [{"name": "rpm", "value": 100, "period": "daily"}],
            }
        },
    )

    with pytest.raises(ValueError, match="Unknown timezone"):
        StateFactory().create("gemini")


@pytest.mark.parametrize(
    "resource_config, expected_ttl",
    [
        ({"name": "legacy", "value": 10, "initial_ttl": 123}, 123),
        ({"name": "plain_ttl", "value": 10, "ttl": 456}, 456),
        ({"name": "custom_ttl", "value": 10, "period": "custom", "ttl": 789}, 789),
    ],
)
def test_create_supports_multiple_ttl_config_variants(resource_config: dict, expected_ttl: int) -> None:
    config = configure()
    config.add("providers", {"gemini": {"resources": [resource_config]}})

    state = StateFactory().create("gemini")
    resource = state.resource_units[resource_config["name"]]

    assert resource.ttl == expected_ttl


def test_create_uses_global_timezone_when_provider_timezone_missing() -> None:
    config = configure()
    config.add("timezone", "Europe/Warsaw")
    config.add(
        "providers",
        {
            "gemini": {
                "resources": [{"name": "rpm", "value": 100, "period": "daily"}],
            }
        },
    )

    state = StateFactory().create("gemini")
    resource = state.resource_units["rpm"]

    assert resource.timezone == "Europe/Warsaw"


def test_create_uses_utc_timezone_when_no_timezone_defined() -> None:
    config = configure()
    config.add(
        "providers",
        {
            "gemini": {
                "resources": [{"name": "rpm", "value": 100, "period": "daily"}],
            }
        },
    )

    state = StateFactory().create("gemini")
    resource = state.resource_units["rpm"]

    assert resource.timezone == "UTC"


def test_create_raises_when_period_custom_has_no_ttl() -> None:
    config = configure()
    config.add(
        "providers",
        {
            "gemini": {
                "resources": [{"name": "rpms", "value": 100, "period": "custom"}],
            }
        },
    )

    with pytest.raises(ValueError, match="requires 'ttl'"):
        StateFactory().create("gemini")


def test_create_raises_when_resource_missing_period_and_ttl() -> None:
    config = configure()
    config.add(
        "providers",
        {
            "gemini": {
                "resources": [{"name": "broken", "value": 100}],
            }
        },
    )

    with pytest.raises(ValueError, match="must define either 'period' or 'initial_ttl'"):
        StateFactory().create("gemini")

