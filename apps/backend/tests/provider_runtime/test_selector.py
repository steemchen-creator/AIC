from datetime import UTC, datetime, timedelta
from time import perf_counter

import pytest

from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderExclusionReason,
    ProviderMetadata,
    ProviderMetricsSnapshot,
    ProviderRegistrySnapshot,
    ProviderRequestContext,
    ProviderSelector,
    ProviderSnapshot,
    ProviderStatus,
    ProviderType,
    QualityScorer,
)
from aic_backend.provider_runtime.errors import (
    CapabilityUnavailableError,
    NoProviderAvailableError,
)

NOW = datetime(2026, 8, 2, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)
OTHER = ProviderCapability("news.market.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


def provider(
    provider_id: str,
    *,
    enabled: bool = True,
    capability: ProviderCapability = CAPABILITY,
    status: ProviderStatus = ProviderStatus.READY,
    health: HealthStatus = HealthStatus.HEALTHY,
    priority: int = 0,
) -> ProviderSnapshot:
    metadata = ProviderMetadata(
        provider_id,
        provider_id,
        ProviderType.MOCK,
        "1.0.0",
        priority=priority,
        enabled=enabled,
    )
    return ProviderSnapshot(
        metadata,
        frozenset({capability}),
        status,
        HealthCheckResult(health, NOW),
        None,
        0,
        NOW,
        NOW,
    )


def context(**kwargs: object) -> ProviderRequestContext:
    values: dict[str, object] = {
        "request_id": "req_1",
        "capability": CAPABILITY,
        "timeout_ms": 100,
    }
    values.update(kwargs)
    return ProviderRequestContext(**values)


def select(
    providers: tuple[ProviderSnapshot, ...],
    *,
    ctx: ProviderRequestContext | None = None,
    metrics: dict[str, ProviderMetricsSnapshot] | None = None,
):
    return ProviderSelector(QualityScorer()).select(
        ctx or context(), ProviderRegistrySnapshot(providers, NOW), metrics or {}, NOW
    )


def test_request_context_is_defensive_and_validated() -> None:
    preferred = ["mock_b", "mock_a"]
    excluded = {"mock_c"}
    value = context(
        preferred_provider_ids=preferred,
        excluded_provider_ids=excluded,
        allow_degraded=True,
    )
    preferred.append("mock_d")
    excluded.add("mock_d")
    assert value.preferred_provider_ids == ("mock_b", "mock_a")
    assert value.excluded_provider_ids == frozenset({"mock_c"})
    with pytest.raises(ValueError, match="request_id"):
        context(request_id=" ")
    with pytest.raises(ValueError, match="timeout_ms"):
        context(timeout_ms=-1)
    with pytest.raises(ValueError, match="preferred"):
        context(preferred_provider_ids=("",))


NON_SELECTABLE = (
    ProviderStatus.REGISTERED,
    ProviderStatus.INITIALIZING,
    ProviderStatus.UNAVAILABLE,
    ProviderStatus.FAILED,
    ProviderStatus.STOPPING,
    ProviderStatus.STOPPED,
    ProviderStatus.DISABLED,
)


@pytest.mark.parametrize("status", NON_SELECTABLE)
def test_non_selectable_lifecycle_states_are_excluded(status: ProviderStatus) -> None:
    decision = select((provider("mock_a", status=status), provider("mock_valid")))
    assert (
        decision.excluded_providers["mock_a"]
        is ProviderExclusionReason.LIFECYCLE_NOT_SELECTABLE
    )


@pytest.mark.parametrize(
    ("snapshot", "ctx", "reason"),
    [
        (provider("mock_a", enabled=False), context(), ProviderExclusionReason.PROVIDER_DISABLED),
        (
            provider("mock_a", capability=OTHER),
            context(),
            ProviderExclusionReason.CAPABILITY_NOT_SUPPORTED,
        ),
        (
            provider("mock_a"),
            context(excluded_provider_ids={"mock_a"}),
            ProviderExclusionReason.EXPLICITLY_EXCLUDED,
        ),
        (
            provider("mock_a", status=ProviderStatus.DEGRADED),
            context(),
            ProviderExclusionReason.DEGRADED_NOT_ALLOWED,
        ),
        (
            provider("mock_a", health=HealthStatus.UNHEALTHY),
            context(),
            ProviderExclusionReason.HEALTH_UNHEALTHY,
        ),
        (
            provider("mock_a", health=HealthStatus.UNKNOWN),
            context(),
            ProviderExclusionReason.HEALTH_UNKNOWN,
        ),
    ],
)
def test_filtering_records_first_reason(
    snapshot: ProviderSnapshot,
    ctx: ProviderRequestContext,
    reason: ProviderExclusionReason,
) -> None:
    decision = select((snapshot, provider("mock_valid")), ctx=ctx)
    assert decision.excluded_providers[snapshot.metadata.provider_id] is reason


def test_cooldown_capacity_and_degraded_rules() -> None:
    providers = (
        provider("mock_cool"),
        provider("mock_full"),
        provider("mock_degraded", status=ProviderStatus.DEGRADED),
    )
    metrics = {
        "mock_cool": ProviderMetricsSnapshot(
            "mock_cool", cooldown_until=NOW + timedelta(seconds=1)
        ),
        "mock_full": ProviderMetricsSnapshot(
            "mock_full", in_flight_requests=2, max_concurrency=2
        ),
        "mock_degraded": ProviderMetricsSnapshot("mock_degraded"),
    }
    decision = select(providers, ctx=context(allow_degraded=True), metrics=metrics)
    assert decision.ordered_candidate_provider_ids == ("mock_degraded",)
    assert (
        decision.excluded_providers["mock_cool"]
        is ProviderExclusionReason.PROVIDER_IN_COOLDOWN
    )
    assert (
        decision.excluded_providers["mock_full"]
        is ProviderExclusionReason.CONCURRENCY_CAPACITY_EXHAUSTED
    )
    metrics["mock_cool"] = ProviderMetricsSnapshot("mock_cool", cooldown_until=NOW)
    metrics["mock_full"] = ProviderMetricsSnapshot(
        "mock_full", in_flight_requests=1, max_concurrency=2
    )
    candidates = select(
        providers, ctx=context(allow_degraded=True), metrics=metrics
    ).ordered_candidate_provider_ids
    assert set(candidates) == {"mock_cool", "mock_full", "mock_degraded"}


def test_preferred_order_overrides_score_but_not_exclusion() -> None:
    providers = (
        provider("mock_a", priority=1000),
        provider("mock_b"),
        provider("mock_c"),
    )
    decision = select(
        providers,
        ctx=context(
            preferred_provider_ids=("missing", "mock_c", "mock_b"),
            excluded_provider_ids={"mock_b"},
        ),
    )
    assert decision.ordered_candidate_provider_ids == ("mock_c", "mock_a")
    assert (
        decision.excluded_providers["mock_b"]
        is ProviderExclusionReason.EXPLICITLY_EXCLUDED
    )


def test_sorting_is_deterministic_across_input_order() -> None:
    providers = (
        provider("mock_c", priority=10),
        provider("mock_a", priority=10),
        provider("mock_b", priority=20),
    )
    expected = ("mock_b", "mock_a", "mock_c")
    assert select(providers).ordered_candidate_provider_ids == expected
    assert select(tuple(reversed(providers))).ordered_candidate_provider_ids == expected
    assert all(select(providers).ordered_candidate_provider_ids == expected for _ in range(100))


def test_ready_precedes_degraded_even_with_lower_score() -> None:
    providers = (
        provider("mock_ready"),
        provider("mock_degraded", status=ProviderStatus.DEGRADED, priority=1000),
    )
    decision = select(providers, ctx=context(allow_degraded=True))
    assert decision.ordered_candidate_provider_ids[0] == "mock_ready"


def test_no_candidate_errors_are_distinct() -> None:
    with pytest.raises(CapabilityUnavailableError):
        select((provider("mock_a", capability=OTHER),))
    with pytest.raises(NoProviderAvailableError, match="none are available") as raised:
        select((provider("mock_a", enabled=False),))
    assert raised.value.supported_provider_count == 1
    assert raised.value.exclusion_summary == {"mock_a": "provider_disabled"}


def test_selection_decision_is_immutable_and_consistent() -> None:
    decision = select((provider("mock_a"),))
    assert decision.selected_provider_id == decision.ordered_candidate_provider_ids[0]
    assert decision.decided_at is NOW
    with pytest.raises(TypeError):
        decision.candidate_scores["mock_a"] = 0  # type: ignore[index]


def test_selection_performance_for_one_hundred_providers() -> None:
    providers = tuple(provider(f"mock_{index:03d}", priority=index) for index in range(100))
    registry = ProviderRegistrySnapshot(providers, NOW)
    selector = ProviderSelector(QualityScorer())
    durations = []
    for index in range(1000):
        started = perf_counter()
        decision = selector.select(context(), registry, {}, NOW)
        durations.append(perf_counter() - started)
        assert decision.selected_provider_id == "mock_099"
    p95 = sorted(durations)[949]
    assert p95 < 0.01
