"""Persist one successful ingestion without re-running pipeline stages."""

from aic_backend.application.ports.persistence import (
    CanonicalDailyBarRepository,
    PersistedDailyBar,
    SaveResult,
)
from aic_backend.data_foundation import IngestionFailure, IngestionSuccess


class PersistIngestionSuccess:
    def __init__(self, repository: CanonicalDailyBarRepository) -> None:
        self._repository = repository

    async def execute(self, result: IngestionSuccess | IngestionFailure) -> SaveResult | None:
        if isinstance(result, IngestionFailure):
            return None
        return await self._repository.save(
            PersistedDailyBar(result.observation_id, result.record, result.quality)
        )
