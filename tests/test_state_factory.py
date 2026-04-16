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

