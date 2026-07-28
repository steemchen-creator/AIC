"""Deterministic in-memory adapters for TASK-002."""

from aic_backend.domain import DataRecord, DataRecordReceived


class InMemoryDataRepository:
    """Process-local repository used to prove the persistence boundary."""

    def __init__(self) -> None:
        self._records: dict[str, DataRecord] = {}

    async def get(self, record_id: str) -> DataRecord | None:
        return self._records.get(record_id)

    async def save(self, record: DataRecord) -> None:
        self._records[record.record_id] = record


class InMemoryDataCache:
    """Process-local cache without persistence responsibilities."""

    def __init__(self) -> None:
        self._records: dict[str, DataRecord] = {}

    async def get(self, record_id: str) -> DataRecord | None:
        return self._records.get(record_id)

    async def set(self, record: DataRecord) -> None:
        self._records[record.record_id] = record


class InMemoryEventBus:
    """Capture published events for deterministic tests and local use."""

    def __init__(self) -> None:
        self.events: list[DataRecordReceived] = []

    async def publish(self, event: DataRecordReceived) -> None:
        self.events.append(event)
