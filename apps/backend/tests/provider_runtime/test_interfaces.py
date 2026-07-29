from datetime import UTC, datetime

import pytest

from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.provider_runtime import (
    ProviderEventType,
    ProviderRuntimeEvent,
    UtcClock,
    UuidIdGenerator,
)
from aic_backend.provider_runtime.errors import (
    AllProvidersFailedError,
    ProviderInvocationError,
    ProviderRuntimeError,
)


def test_utc_clock_returns_timezone_aware_utc_time() -> None:
    value = UtcClock().now()

    assert value.tzinfo is UTC
    assert isinstance(value, datetime)


def test_uuid_generator_returns_prefixed_unique_ids() -> None:
    generator = UuidIdGenerator()

    first = generator.new_id("req")
    second = generator.new_id("req")

    assert first.startswith("req_")
    assert second.startswith("req_")
    assert first != second
    with pytest.raises(ValueError, match="prefix"):
        generator.new_id(" ")


def test_error_hierarchy_preserves_safe_context() -> None:
    error = AllProvidersFailedError(
        message="No configured provider succeeded.",
        request_id="req_1",
        capability="market.quote.snapshot",
        failover_occurred=True,
    )

    assert isinstance(error, ProviderInvocationError)
    assert isinstance(error, ProviderRuntimeError)
    assert str(error) == "No configured provider succeeded."
    assert error.error_code == "PROVIDER_ALL_FAILED"
    assert error.request_id == "req_1"
    assert error.failover_occurred is True
    assert error.retryable is True


async def test_existing_event_bus_accepts_provider_runtime_events() -> None:
    bus = InMemoryEventBus()
    event = ProviderRuntimeEvent(
        event_id="evt_1",
        event_type=ProviderEventType.REGISTERED,
        occurred_at=datetime(2026, 7, 29, tzinfo=UTC),
        payload={"provider_id": "mock_market_primary"},
    )

    await bus.publish(event)

    assert bus.events == [event]
