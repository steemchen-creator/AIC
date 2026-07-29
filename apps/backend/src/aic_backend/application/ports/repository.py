"""Repository contract."""

from typing import Protocol

from aic_backend.domain import DataRecord


class DataRepository(Protocol):
    """Persist and retrieve owned data records."""

    async def get(self, record_id: str) -> DataRecord | None:
        """Return a persisted record when present."""
        ...

    async def save(self, record: DataRecord) -> None:
        """Persist a record by its identity."""
        ...
