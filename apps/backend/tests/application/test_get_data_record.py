from datetime import UTC, datetime

import pytest

from aic_backend.application.use_cases import GetDataRecord
from aic_backend.domain import DataRecord
from aic_backend.infrastructure import (
    InMemoryDataCache,
    InMemoryDataRepository,
    InMemoryEventBus,
)
from aic_backend.providers import MockDataProvider


def make_record() -> DataRecord:
    return DataRecord(
        record_id="sample-1",
        source="mock",
        payload={"value": 42},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_use_case_fetches_persists_caches_and_publishes_once() -> None:
    record = make_record()
    cache = InMemoryDataCache()
    repository = InMemoryDataRepository()
    provider = MockDataProvider([record])
    event_bus = InMemoryEventBus()
    use_case = GetDataRecord(
        cache=cache,
        repository=repository,
        provider=provider,
        event_bus=event_bus,
        clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
    )

    first = await use_case.execute(record.record_id)
    second = await use_case.execute(record.record_id)

    assert first is record
    assert second is record
    assert await repository.get(record.record_id) is record
    assert await cache.get(record.record_id) is record
    assert provider.fetch_count == 1
    assert len(event_bus.events) == 1
    assert event_bus.events[0].record_id == record.record_id


@pytest.mark.asyncio
async def test_use_case_returns_none_without_side_effects_when_missing() -> None:
    event_bus = InMemoryEventBus()
    use_case = GetDataRecord(
        cache=InMemoryDataCache(),
        repository=InMemoryDataRepository(),
        provider=MockDataProvider(),
        event_bus=event_bus,
    )

    assert await use_case.execute("missing") is None
    assert event_bus.events == []


@pytest.mark.asyncio
async def test_use_case_uses_repository_before_provider() -> None:
    record = make_record()
    repository = InMemoryDataRepository()
    await repository.save(record)
    cache = InMemoryDataCache()
    provider = MockDataProvider()
    use_case = GetDataRecord(
        cache=cache,
        repository=repository,
        provider=provider,
        event_bus=InMemoryEventBus(),
    )

    assert await use_case.execute(record.record_id) is record
    assert await cache.get(record.record_id) is record
    assert provider.fetch_count == 0
