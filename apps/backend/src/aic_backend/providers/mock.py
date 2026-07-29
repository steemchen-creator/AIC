"""Deterministic provider used by TASK-002."""

from collections.abc import Iterable

from aic_backend.domain import DataRecord


class MockDataProvider:
    """Return predefined records without network or external-service access."""

    def __init__(self, records: Iterable[DataRecord] = ()) -> None:
        self._records = {record.record_id: record for record in records}
        self.fetch_count = 0

    async def fetch(self, record_id: str) -> DataRecord | None:
        self.fetch_count += 1
        return self._records.get(record_id)
