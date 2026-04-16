from asyncbalancer.models.client import ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCost, ResourceUnitCosts
from asyncbalancer.score_calculator import ProviderScoreCalculator


def _response(latency: int) -> ProviderResponse:
    return ProviderResponse(success=True, data={}, latency=latency, error=None)


def _costs(tpm: float, rpm: float = 0.0) -> ResourceUnitCosts:
    return ResourceUnitCosts(
        costs={
            "tpm": ResourceUnitCost(key="tpm", amount=tpm),
            "rpm": ResourceUnitCost(key="rpm", amount=rpm),
        }
    )


def test_score_is_higher_for_lower_resource_usage() -> None:
    calculator = ProviderScoreCalculator()

    low_usage_score = calculator.calculate(_response(latency=300), _costs(tpm=10, rpm=5))
    high_usage_score = calculator.calculate(_response(latency=300), _costs(tpm=500, rpm=200))

    assert low_usage_score > high_usage_score


def test_latency_penalizes_but_is_not_primary_factor() -> None:
    calculator = ProviderScoreCalculator()

    low_usage_high_latency = calculator.calculate(_response(latency=4000), _costs(tpm=20))
    high_usage_low_latency = calculator.calculate(_response(latency=100), _costs(tpm=200))

    assert low_usage_high_latency > high_usage_low_latency


def test_score_is_always_in_range_0_to_100() -> None:
    calculator = ProviderScoreCalculator()

    score_low = calculator.calculate(_response(latency=0), _costs(tpm=0, rpm=0))
    score_high = calculator.calculate(_response(latency=100_000), _costs(tpm=1_000_000, rpm=1_000_000))

    assert 0.0 <= score_low <= 100.0
    assert 0.0 <= score_high <= 100.0

