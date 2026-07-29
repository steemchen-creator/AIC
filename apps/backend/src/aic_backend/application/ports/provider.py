"""Provider contract."""

from typing import Protocol

from aic_backend.domain import DataRecord


class DataProvider(Protocol):
    """Obtain one record without caching or persistence side effects."""

    async def fetch(self, record_id: str) -> DataRecord | None:
        """Return a record when the configured source contains it."""
        ...
