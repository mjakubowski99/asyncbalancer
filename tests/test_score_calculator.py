from asyncbalancer.models.client import ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCost, ResourceUnitCosts
from asyncbalancer.score_calculator import ProviderScoreCalculator


def _response(latency: int, *, success: bool = True, error: str | None = None) -> ProviderResponse:
    return ProviderResponse(success=success, data={}, latency=latency, error=error)


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


def test_score_is_always_in_range_min_to_100() -> None:
    calculator = ProviderScoreCalculator()
    minimum = ProviderScoreCalculator.MIN_SCORE

    score_low = calculator.calculate(_response(latency=0), _costs(tpm=0, rpm=0))
    score_high = calculator.calculate(_response(latency=100_000), _costs(tpm=1_000_000, rpm=1_000_000))

    assert minimum <= score_low <= 100.0
    assert minimum <= score_high <= 100.0


def test_failure_without_previous_uses_raw_score_times_failure_penalty() -> None:
    """``success=False`` and no ``previous_score``: ``base`` is ``raw_score``, then ``* FAILURE_PENALTY``."""
    calculator = ProviderScoreCalculator()
    costs = _costs(tpm=40, rpm=5)
    ok = calculator.calculate(_response(latency=150, success=True), costs)
    failed = calculator.calculate(_response(latency=150, success=False, error="upstream error"), costs)

    expected = max(
        ProviderScoreCalculator.MIN_SCORE,
        min(100.0, ok * ProviderScoreCalculator.FAILURE_PENALTY),
    )
    assert failed == expected


def test_failed_response_lower_than_success_same_metrics() -> None:
    calculator = ProviderScoreCalculator()
    costs = _costs(tpm=50, rpm=10)
    ok = calculator.calculate(_response(latency=200, success=True), costs)
    bad = calculator.calculate(_response(latency=200, success=False, error="upstream error"), costs)
    assert bad < ok


def test_failure_with_timeout_applies_failure_then_timeout_penalty() -> None:
    """Timeout-like ``error`` applies ``FAILURE_PENALTY * TIMEOUT_PENALTY`` on ``base`` (``raw_score`` when no previous)."""
    calculator = ProviderScoreCalculator()
    costs = _costs(tpm=30)
    raw_equivalent = calculator.calculate(_response(latency=100, success=True), costs)

    generic_fail = calculator.calculate(
        _response(latency=100, success=False, error="bad request"),
        costs,
    )
    timeout_fail = calculator.calculate(
        _response(latency=100, success=False, error="Request timed out after 30s"),
        costs,
    )

    assert generic_fail == max(
        ProviderScoreCalculator.MIN_SCORE,
        min(100.0, raw_equivalent * ProviderScoreCalculator.FAILURE_PENALTY),
    )
    assert timeout_fail == max(
        ProviderScoreCalculator.MIN_SCORE,
        min(
            100.0,
            raw_equivalent
            * ProviderScoreCalculator.FAILURE_PENALTY
            * ProviderScoreCalculator.TIMEOUT_PENALTY,
        ),
    )
    assert timeout_fail < generic_fail


def test_failure_with_previous_score_multiplies_previous_by_failure_penalty() -> None:
    calculator = ProviderScoreCalculator()
    costs = _costs(tpm=10)
    prev = 80.0
    failed = calculator.calculate(
        _response(latency=100, success=False, error="error"),
        costs,
        previous_score=prev,
    )
    assert failed == max(
        ProviderScoreCalculator.MIN_SCORE,
        min(100.0, prev * ProviderScoreCalculator.FAILURE_PENALTY),
    )
    assert failed == 48.0
