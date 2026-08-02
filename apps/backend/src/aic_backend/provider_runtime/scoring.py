"""Pure, deterministic Provider quality scoring."""

from datetime import datetime

from aic_backend.provider_runtime.models import (
    HealthStatus,
    ProviderMetricsSnapshot,
    ProviderSnapshot,
    ProviderStatus,
    QualityScoreBreakdown,
)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


class QualityScorer:
    """Calculate an explainable score without I/O or mutable state."""

    def score(
        self,
        provider: ProviderSnapshot,
        metrics: ProviderMetricsSnapshot,
        now: datetime,
    ) -> QualityScoreBreakdown:
        del now  # Explicit input reserved for time-relative approved scoring rules.
        health = provider.health.status if provider.health else HealthStatus.UNKNOWN
        availability = {
            (ProviderStatus.READY, HealthStatus.HEALTHY): 100.0,
            (ProviderStatus.READY, HealthStatus.DEGRADED): 80.0,
            (ProviderStatus.DEGRADED, HealthStatus.HEALTHY): 70.0,
            (ProviderStatus.DEGRADED, HealthStatus.DEGRADED): 50.0,
        }.get((provider.lifecycle_status, health), 0.0)
        default_success = metrics.total_calls == 0
        success = 60.0 if default_success else _clamp(
            metrics.successful_calls / metrics.total_calls * 100
        )
        if metrics.p95_latency_ms is not None:
            latency = _clamp(100 * (5000 - metrics.p95_latency_ms) / 4900)
            used_p50 = False
            default_latency = False
        elif metrics.p50_latency_ms is not None:
            latency = _clamp(100 * (5000 - metrics.p50_latency_ms) / 4900)
            used_p50 = True
            default_latency = False
        else:
            latency = 60.0
            used_p50 = False
            default_latency = True
        freshness_unknown = metrics.data_freshness_seconds is None
        if metrics.data_freshness_seconds is None:
            freshness = 50.0
        else:
            freshness = _clamp(
                100 * (3600 - metrics.data_freshness_seconds) / 3595
            )
        priority = _clamp(provider.metadata.priority / 1000 * 100)
        total = _clamp(
            availability * 0.35
            + success * 0.30
            + latency * 0.20
            + freshness * 0.10
            + priority * 0.05
        )
        return QualityScoreBreakdown(
            total_score=total,
            availability_score=availability,
            success_rate_score=success,
            latency_score=latency,
            freshness_score=freshness,
            priority_score=priority,
            used_default_success_rate=default_success,
            used_default_latency=default_latency,
            used_p50_latency=used_p50,
            freshness_unknown=freshness_unknown,
        )
