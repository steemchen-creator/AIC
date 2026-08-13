import asyncio
from datetime import UTC, datetime

import pytest

from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderEventType,
    ProviderLifecycleManager,
    ProviderMetadata,
    ProviderRegistry,
    ProviderStatus,
    ProviderType,
)
from aic_backend.provider_runtime.errors import (
    InvalidStateTransitionError,
    ProviderLifecycleError,
)

NOW = datetime(2026, 7, 30, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FixedIdGenerator:
    def __init__(self) -> None:
        self._next = 0

    def new_id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}_{self._next}"


class StubProvider:
    def __init__(self, *, initialize_error: Exception | None = None) -> None:
        self._metadata = ProviderMetadata(
            provider_id="mock_primary",
            display_name="Mock Primary",
            provider_type=ProviderType.MOCK,
            version="1.0.0",
        )
        self._initialize_error = initialize_error
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.initialize_entered = asyncio.Event()
        self.initialize_release: asyncio.Event | None = None

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset({CAPABILITY})

    async def initialize(self) -> None:
        self.initialize_calls += 1
        self.initialize_entered.set()
        if self.initialize_release is not None:
            await self.initialize_release.wait()
        if self._initialize_error is not None:
            raise self._initialize_error

    async def shutdown(self) -> None:
        self.shutdown_calls += 1

    async def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(HealthStatus.HEALTHY, NOW)


def build_lifecycle() -> tuple[ProviderRegistry, ProviderLifecycleManager, InMemoryEventBus]:
    clock = FixedClock()
    registry = ProviderRegistry(clock)
    bus = InMemoryEventBus()
    lifecycle = ProviderLifecycleManager(registry, bus, clock, FixedIdGenerator())
    return registry, lifecycle, bus


async def test_initialization_success_and_lifecycle_events() -> None:
    registry, lifecycle, bus = build_lifecycle()
    provider = StubProvider()
    await lifecycle.register(provider)

    snapshot = await lifecycle.initialize("mock_primary")

    assert snapshot.lifecycle_status is ProviderStatus.READY
    assert provider.initialize_calls == 1
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.READY
    assert [event.event_type for event in bus.events] == [
        ProviderEventType.REGISTERED,
        ProviderEventType.STATUS_CHANGED,
        ProviderEventType.STATUS_CHANGED,
        ProviderEventType.READY,
    ]


async def test_initialization_failure_transitions_to_failed_and_preserves_cause() -> None:
    registry, lifecycle, _ = build_lifecycle()
    await lifecycle.register(StubProvider(initialize_error=ValueError("secret detail")))

    with pytest.raises(ProviderLifecycleError, match="initialization failed") as raised:
        await lifecycle.initialize("mock_primary")

    assert isinstance(raised.value.__cause__, ValueError)
    assert "secret detail" not in str(raised.value)
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.FAILED


async def test_legal_and_illegal_state_transitions() -> None:
    registry, lifecycle, _ = build_lifecycle()
    await lifecycle.register(StubProvider())

    disabled = await lifecycle.disable("mock_primary", "operator request")
    initializing = await lifecycle.transition("mock_primary", ProviderStatus.INITIALIZING)

    assert disabled.lifecycle_status is ProviderStatus.DISABLED
    assert initializing.lifecycle_status is ProviderStatus.INITIALIZING
    with pytest.raises(InvalidStateTransitionError, match="cannot transition"):
        await lifecycle.transition("mock_primary", ProviderStatus.STOPPED)
    assert (
        await registry.get_snapshot("mock_primary")
    ).lifecycle_status is ProviderStatus.INITIALIZING


async def test_shutdown_moves_ready_provider_to_stopped() -> None:
    registry, lifecycle, _ = build_lifecycle()
    provider = StubProvider()
    await lifecycle.register(provider)
    await lifecycle.initialize("mock_primary")

    snapshot = await lifecycle.shutdown("mock_primary")

    assert snapshot.lifecycle_status is ProviderStatus.STOPPED
    assert provider.shutdown_calls == 1
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.STOPPED


async def test_concurrent_status_changes_are_serialized() -> None:
    registry, lifecycle, _ = build_lifecycle()
    provider = StubProvider()
    provider.initialize_release = asyncio.Event()
    await lifecycle.register(provider)

    first = asyncio.create_task(lifecycle.initialize("mock_primary"))
    await provider.initialize_entered.wait()
    second = asyncio.create_task(lifecycle.initialize("mock_primary"))
    provider.initialize_release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert sum(hasattr(result, "lifecycle_status") for result in results) == 1
    assert sum(isinstance(result, InvalidStateTransitionError) for result in results) == 1
    assert provider.initialize_calls == 1
    assert (await registry.get_snapshot("mock_primary")).lifecycle_status is ProviderStatus.READY
