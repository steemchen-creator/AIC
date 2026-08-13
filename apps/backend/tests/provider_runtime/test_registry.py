import asyncio
from datetime import UTC, datetime

import pytest

from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderMetadata,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRegistrySnapshot,
    ProviderStatus,
    ProviderType,
)
from aic_backend.provider_runtime.errors import DuplicateProviderError, ProviderNotFoundError

NOW = datetime(2026, 7, 29, tzinfo=UTC)
QUOTE = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)
NEWS = ProviderCapability("news.market.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class StubProvider:
    def __init__(
        self,
        provider_id: str,
        *,
        enabled: bool = True,
        capabilities: frozenset[ProviderCapability] = frozenset({QUOTE}),
    ) -> None:
        self._metadata = ProviderMetadata(
            provider_id=provider_id,
            display_name=provider_id,
            provider_type=ProviderType.MOCK,
            version="1.0.0",
            enabled=enabled,
        )
        self._capabilities = capabilities
        self.lifecycle_calls = 0

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return self._capabilities

    async def initialize(self) -> None:
        self.lifecycle_calls += 1

    async def shutdown(self) -> None:
        self.lifecycle_calls += 1

    async def health_check(self) -> HealthCheckResult:
        self.lifecycle_calls += 1
        return HealthCheckResult(HealthStatus.HEALTHY, NOW)


async def test_register_returns_registration_without_lifecycle_side_effects() -> None:
    registry = ProviderRegistry(FixedClock())
    provider = StubProvider("mock_primary")

    registration = await registry.register(provider)

    assert registration == ProviderRegistration(
        provider_id="mock_primary",
        lifecycle_status=ProviderStatus.REGISTERED,
        registered_at=NOW,
    )
    assert await registry.get("mock_primary") is provider
    assert provider.lifecycle_calls == 0


async def test_disabled_provider_is_registered_as_disabled() -> None:
    registry = ProviderRegistry(FixedClock())

    await registry.register(StubProvider("mock_disabled", enabled=False))

    assert (await registry.list())[0].lifecycle_status is ProviderStatus.DISABLED


async def test_list_and_registry_snapshot_are_immutable_and_deterministic() -> None:
    registry = ProviderRegistry(FixedClock())
    await registry.register(StubProvider("mock_secondary"))
    await registry.register(StubProvider("mock_primary"))

    items = await registry.list()
    snapshot = await registry.snapshot()

    assert tuple(item.metadata.provider_id for item in items) == (
        "mock_primary",
        "mock_secondary",
    )
    assert snapshot.providers == items
    assert snapshot.captured_at == NOW
    assert all(item.health is None for item in items)
    assert all(item.quality_score is None for item in items)
    with pytest.raises(ValueError, match="duplicate"):
        ProviderRegistrySnapshot(providers=items + items, captured_at=NOW)


def test_registration_rejects_lifecycle_managed_status() -> None:
    with pytest.raises(ValueError, match="registration status"):
        ProviderRegistration(
            provider_id="mock_primary",
            lifecycle_status=ProviderStatus.READY,
            registered_at=NOW,
        )


async def test_find_by_capability_uses_exact_capability_identity() -> None:
    registry = ProviderRegistry(FixedClock())
    await registry.register(StubProvider("mock_quotes", capabilities=frozenset({QUOTE})))
    await registry.register(StubProvider("mock_news", capabilities=frozenset({NEWS})))

    matches = await registry.find_by_capability(QUOTE)

    assert tuple(item.metadata.provider_id for item in matches) == ("mock_quotes",)
    different_version = ProviderCapability(
        "market.quote.snapshot", "2.0.0", CapabilityMode.SNAPSHOT
    )
    assert await registry.find_by_capability(different_version) == ()


async def test_registration_captures_capabilities_for_stable_snapshots() -> None:
    registry = ProviderRegistry(FixedClock())
    provider = StubProvider("mock_primary", capabilities=frozenset({QUOTE}))
    await registry.register(provider)

    provider._capabilities = frozenset({NEWS})

    assert (await registry.list())[0].capabilities == frozenset({QUOTE})


async def test_unregister_removes_provider_and_missing_ids_are_explicit() -> None:
    registry = ProviderRegistry(FixedClock())
    await registry.register(StubProvider("mock_primary"))

    await registry.unregister("mock_primary")

    with pytest.raises(ProviderNotFoundError, match="not registered"):
        await registry.get("mock_primary")
    with pytest.raises(ProviderNotFoundError, match="not registered"):
        await registry.unregister("mock_primary")


async def test_concurrent_duplicate_registration_is_atomic() -> None:
    registry = ProviderRegistry(FixedClock())

    results = await asyncio.gather(
        registry.register(StubProvider("mock_primary")),
        registry.register(StubProvider("mock_primary")),
        return_exceptions=True,
    )

    assert sum(isinstance(item, ProviderRegistration) for item in results) == 1
    assert sum(isinstance(item, DuplicateProviderError) for item in results) == 1
    assert len(await registry.list()) == 1
