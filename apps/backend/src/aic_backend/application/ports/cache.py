"""Cache contract."""

from typing import Protocol

from aic_backend.domain import DataRecord


class DataCache(Protocol):
    """Cache data records without owning persistence behavior."""

    async def get(self, record_id: str) -> DataRecord | None:
        """Return a cached record when present."""
        ...

    async def set(self, record: DataRecord) -> None:
        """Cache a record by its identity."""
        ...
