from datetime import UTC, datetime

import pytest

from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderMetadata,
    ProviderMetricsSnapshot,
    ProviderSnapshot,
    ProviderStatus,
    ProviderType,
    QualityScorer,
)

NOW = datetime(2026, 8, 2, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


def provider(
    *, status: ProviderStatus = ProviderStatus.READY,
    health: HealthStatus = HealthStatus.HEALTHY,
    priority: int = 0,
) -> ProviderSnapshot:
    return ProviderSnapshot(
        metadata=ProviderMetadata(
            "mock_primary", "Mock", ProviderType.MOCK, "1.0.0", priority=priority
        ),
        capabilities=frozenset({CAPABILITY}),
        lifecycle_status=status,
        health=HealthCheckResult(health, NOW),
        quality_score=None,
        in_flight_requests=0,
        registered_at=NOW,
        last_state_change_at=NOW,
    )


@pytest.mark.parametrize(
    ("status", "health", "expected"),
    [
        (ProviderStatus.READY, HealthStatus.HEALTHY, 100),
        (ProviderStatus.READY, HealthStatus.DEGRADED, 80),
        (ProviderStatus.DEGRADED, HealthStatus.HEALTHY, 70),
        (ProviderStatus.DEGRADED, HealthStatus.DEGRADED, 50),
        (ProviderStatus.UNAVAILABLE, HealthStatus.UNHEALTHY, 0),
    ],
)
def test_availability_matrix(
    status: ProviderStatus, health: HealthStatus, expected: float
) -> None:
    result = QualityScorer().score(
        provider(status=status, health=health),
        ProviderMetricsSnapshot("mock_primary"),
        NOW,
    )
    assert result.availability_score == expected


def test_best_and_worst_metrics_are_clamped_and_weighted() -> None:
    scorer = QualityScorer()
    best = scorer.score(
        provider(priority=1000),
        ProviderMetricsSnapshot(
            "mock_primary", total_calls=10, successful_calls=10, p95_latency_ms=0,
            data_freshness_seconds=0,
        ),
        NOW,
    )
    worst = scorer.score(
        provider(status=ProviderStatus.UNAVAILABLE, health=HealthStatus.UNHEALTHY),
        ProviderMetricsSnapshot(
            "mock_primary", total_calls=10, failed_calls=10, p95_latency_ms=6000,
            data_freshness_seconds=4000,
        ),
        NOW,
    )
    assert best.total_score == 100
    assert worst.total_score == 0


def test_new_provider_uses_approved_neutral_defaults() -> None:
    result = QualityScorer().score(provider(), ProviderMetricsSnapshot("mock_primary"), NOW)
    assert result.success_rate_score == 60
    assert result.latency_score == 60
    assert result.freshness_score == 50
    assert result.used_default_success_rate is True
    assert result.used_default_latency is True
    assert result.freshness_unknown is True


def test_p50_fallback_and_linear_scores_are_explainable() -> None:
    result = QualityScorer().score(
        provider(priority=500),
        ProviderMetricsSnapshot(
            "mock_primary", total_calls=4, successful_calls=2, failed_calls=2,
            p50_latency_ms=2550, data_freshness_seconds=1802.5,
        ),
        NOW,
    )
    assert result.success_rate_score == 50
    assert result.latency_score == pytest.approx(50)
    assert result.freshness_score == pytest.approx(50)
    assert result.priority_score == 50
    assert result.used_p50_latency is True
    assert result.total_score == pytest.approx(
        result.availability_score * 0.35 + result.success_rate_score * 0.30
        + result.latency_score * 0.20 + result.freshness_score * 0.10
        + result.priority_score * 0.05
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"total_calls": -1},
        {"total_calls": 1, "successful_calls": 2},
        {"p95_latency_ms": -1},
        {"data_freshness_seconds": -1},
        {"max_concurrency": 0},
    ],
)
def test_metrics_snapshot_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ProviderMetricsSnapshot("mock_primary", **kwargs)


def test_scoring_is_deterministic_and_does_not_modify_inputs() -> None:
    snapshot = provider(priority=250)
    metrics = ProviderMetricsSnapshot("mock_primary", total_calls=1, successful_calls=1)
    scorer = QualityScorer()
    assert scorer.score(snapshot, metrics, NOW) == scorer.score(snapshot, metrics, NOW)
    assert metrics.successful_calls == 1
