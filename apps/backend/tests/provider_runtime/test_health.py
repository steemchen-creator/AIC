import asyncio
from collections import deque
from datetime import UTC, datetime

import pytest

from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckPolicy,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderHealthManager,
    ProviderLifecycleManager,
    ProviderMetadata,
    ProviderRegistry,
    ProviderStatus,
    ProviderType,
)

NOW = datetime(2026, 7, 30, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FixedIdGenerator:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_fixed"


class HealthProvider:
    def __init__(self) -> None:
        self._metadata = ProviderMetadata(
            provider_id="mock_primary",
            display_name="Mock Primary",
            provider_type=ProviderType.MOCK,
            version="1.0.0",
        )
        self.results: deque[HealthCheckResult] = deque()
        self.health_entered = asyncio.Event()
        self.health_release: asyncio.Event | None = None
        self.health_cancelled = False

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset({CAPABILITY})

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> HealthCheckResult:
        self.health_entered.set()
        try:
            if self.health_release is not None:
                await self.health_release.wait()
        except asyncio.CancelledError:
            self.health_cancelled = True
            raise
        if self.results:
            return self.results.popleft()
        return HealthCheckResult(HealthStatus.HEALTHY, NOW)


async def build_health(
    *, timeout_ms: int = 100, failure_threshold: int = 3, recovery_threshold: int = 2
) -> tuple[ProviderRegistry, ProviderLifecycleManager, ProviderHealthManager, HealthProvider]:
    clock = FixedClock()
    registry = ProviderRegistry(clock)
    lifecycle = ProviderLifecycleManager(registry, InMemoryEventBus(), clock, FixedIdGenerator())
    health = ProviderHealthManager(
        registry,
        lifecycle,
        clock,
        HealthCheckPolicy(
            ready_interval_seconds=0.01,
            degraded_interval_seconds=0.01,
            unavailable_interval_seconds=0.01,
            timeout_ms=timeout_ms,
            failure_threshold=failure_threshold,
            recovery_threshold=recovery_threshold,
        ),
    )
    provider = HealthProvider()
    await lifecycle.register(provider)
    await lifecycle.initialize("mock_primary")
    return registry, lifecycle, health, provider


async def test_successful_health_check_keeps_provider_ready() -> None:
    registry, _, health, _ = await build_health()

    result = await health.check_once("mock_primary")

    snapshot = await registry.get_snapshot("mock_primary")
    assert result.status is HealthStatus.HEALTHY
    assert snapshot.lifecycle_status is ProviderStatus.READY
    assert snapshot.health == result


async def test_health_check_timeout_is_unhealthy_and_degrades_provider() -> None:
    registry, _, health, provider = await build_health(timeout_ms=10)
    provider.health_release = asyncio.Event()

    result = await health.check_once("mock_primary")

    assert result.status is HealthStatus.UNHEALTHY
    assert result.message == "Health check timed out."
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.DEGRADED


async def test_health_check_exception_is_safely_recorded() -> None:
    registry, _, health, provider = await build_health()

    async def fail_health_check() -> HealthCheckResult:
        raise RuntimeError("private provider detail")

    provider.health_check = fail_health_check  # type: ignore[method-assign]

    result = await health.check_once("mock_primary")

    assert result.status is HealthStatus.UNHEALTHY
    assert result.message == "Health check failed."
    assert "private provider detail" not in result.message
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.DEGRADED


async def test_consecutive_failures_make_provider_unavailable() -> None:
    registry, _, health, provider = await build_health(failure_threshold=3)
    unhealthy = HealthCheckResult(
        HealthStatus.UNHEALTHY, NOW, message="dependency unavailable"
    )
    provider.results.extend([unhealthy, unhealthy, unhealthy])

    await health.check_once("mock_primary")
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.DEGRADED
    await health.check_once("mock_primary")
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.DEGRADED
    await health.check_once("mock_primary")
    assert (
        await registry.get_snapshot("mock_primary")
    ).lifecycle_status is ProviderStatus.UNAVAILABLE


async def test_consecutive_successes_recover_in_two_controlled_steps() -> None:
    registry, _, health, provider = await build_health(
        failure_threshold=2, recovery_threshold=2
    )
    unhealthy = HealthCheckResult(HealthStatus.UNHEALTHY, NOW)
    healthy = HealthCheckResult(HealthStatus.HEALTHY, NOW)
    provider.results.extend([unhealthy, unhealthy, healthy, healthy, healthy, healthy])

    await health.check_once("mock_primary")
    await health.check_once("mock_primary")
    assert (
        await registry.get_snapshot("mock_primary")
    ).lifecycle_status is ProviderStatus.UNAVAILABLE
    await health.check_once("mock_primary")
    await health.check_once("mock_primary")
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.DEGRADED
    await health.check_once("mock_primary")
    await health.check_once("mock_primary")
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.READY


async def test_background_health_task_is_cancelled_cleanly() -> None:
    _, _, health, provider = await build_health(timeout_ms=1000)
    provider.health_release = asyncio.Event()

    health.start("mock_primary")
    await provider.health_entered.wait()
    await health.stop("mock_primary")

    assert provider.health_cancelled is True
    await health.shutdown()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ready_interval_seconds": 0},
        {"timeout_ms": 0},
        {"failure_threshold": 0},
        {"recovery_threshold": 0},
    ],
)
def test_health_policy_rejects_non_positive_values(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="positive"):
        HealthCheckPolicy(**kwargs)
