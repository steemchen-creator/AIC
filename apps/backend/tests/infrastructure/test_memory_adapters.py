from datetime import UTC, datetime

import pytest

from aic_backend.application.ports import DataCache, DataRepository, EventBus
from aic_backend.domain import DataRecord, DataRecordReceived
from aic_backend.infrastructure import (
    InMemoryDataCache,
    InMemoryDataRepository,
    InMemoryEventBus,
)


@pytest.fixture
def record() -> DataRecord:
    return DataRecord(
        record_id="sample-1",
        source="mock",
        payload={"value": 42},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_repository_saves_and_retrieves(record: DataRecord) -> None:
    repository: DataRepository = InMemoryDataRepository()

    assert await repository.get(record.record_id) is None
    await repository.save(record)

    assert await repository.get(record.record_id) is record


@pytest.mark.asyncio
async def test_cache_sets_and_retrieves(record: DataRecord) -> None:
    cache: DataCache = InMemoryDataCache()

    assert await cache.get(record.record_id) is None
    await cache.set(record)

    assert await cache.get(record.record_id) is record


@pytest.mark.asyncio
async def test_event_bus_captures_published_event(record: DataRecord) -> None:
    event = DataRecordReceived(
        event_id="event-1",
        record_id=record.record_id,
        source=record.source,
        payload=record.payload,
        occurred_at=record.observed_at,
    )
    event_bus = InMemoryEventBus()
    contract: EventBus = event_bus

    await contract.publish(event)

    assert event_bus.events == [event]
