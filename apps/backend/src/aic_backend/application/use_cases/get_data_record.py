"""Retrieve a data record through owned boundaries."""

from collections.abc import Callable
from datetime import UTC, datetime

from aic_backend.application.ports import DataCache, DataProvider, DataRepository, EventBus
from aic_backend.domain import DataRecord, DataRecordReceived


def utc_now() -> datetime:
    return datetime.now(UTC)


class GetDataRecord:
    """Resolve a record from cache, repository, or provider in that order."""

    def __init__(self, cache: DataCache, repository: DataRepository,
                 provider: DataProvider, event_bus: EventBus,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self._cache = cache
        self._repository = repository
        self._provider = provider
        self._event_bus = event_bus
        self._clock = clock

    async def execute(self, record_id: str) -> DataRecord | None:
        cached = await self._cache.get(record_id)
        if cached is not None:
            return cached
        persisted = await self._repository.get(record_id)
        if persisted is not None:
            await self._cache.set(persisted)
            return persisted
        supplied = await self._provider.fetch(record_id)
        if supplied is None:
            return None
        await self._repository.save(supplied)
        await self._cache.set(supplied)
        occurred_at = self._clock()
        await self._event_bus.publish(
            DataRecordReceived(
                event_id=(
                    f"data-record-received:{supplied.source}:"
                    f"{supplied.record_id}:{occurred_at.isoformat()}"
                ),
                record_id=supplied.record_id,
                source=supplied.source,
                payload=supplied.payload,
                occurred_at=occurred_at,
            )
        )
        return supplied
