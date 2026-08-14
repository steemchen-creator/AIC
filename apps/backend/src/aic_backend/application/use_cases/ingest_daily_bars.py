"""Vendor-neutral batch orchestration for canonical daily bars."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from aic_backend.application.ports.persistence import SaveStatus
from aic_backend.application.use_cases.persist_ingestion import PersistIngestionSuccess
from aic_backend.data_foundation import (
    DataIngestionPipeline,
    IngestionFailure,
    QualityContext,
    SourceClassification,
    create_raw_observation,
)
from aic_backend.domain.market_data import DailyBar, DataCapability
from aic_backend.provider_runtime import (
    Clock,
    IdGenerator,
    ProviderCapability,
    ProviderRequestContext,
    ProviderRuntimePort,
)


@dataclass(frozen=True, slots=True)
class DailyBarBatchSummary:
    requested: int
    received: int
    succeeded: int
    failed: int
    persisted: int
    already_exists: int


class IngestDailyBars:
    """Invoke the selected Provider, then process each returned row independently."""

    def __init__(
        self,
        runtime: ProviderRuntimePort,
        capability: ProviderCapability,
        pipeline: DataIngestionPipeline,
        persistence: PersistIngestionSuccess,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._runtime = runtime
        self._capability = capability
        self._pipeline = pipeline
        self._persistence = persistence
        self._clock = clock
        self._ids = ids

    async def execute(
        self,
        parameters: Mapping[str, Any],
        *,
        timeout_ms: int = 5000,
    ) -> DailyBarBatchSummary:
        request_id = self._ids.new_id("request")
        result = await self._runtime.execute(
            ProviderRequestContext(
                request_id,
                self._capability,
                timeout_ms,
                symbol=str(parameters.get("ts_code", "")) or None,
            ),
            parameters,
        )
        rows = self._rows(result.data)
        succeeded = failed = persisted = already_exists = 0
        for row in rows:
            received_at = self._clock.now()
            observation = create_raw_observation(
                observation_id=self._ids.new_id("observation"),
                provider_id=result.provider_id,
                capability=DataCapability.DAILY_BAR,
                received_at=received_at,
                payload=row,
                source_metadata={"failover_count": result.failover_count},
            )
            ingestion = self._pipeline.ingest(
                ingestion_id=self._ids.new_id("ingestion"),
                record_type=DailyBar.RECORD_TYPE,
                observation=observation,
                reference_time=received_at,
                quality_context=QualityContext(SourceClassification.PUBLIC_FINANCIAL_API),
            )
            if isinstance(ingestion, IngestionFailure):
                failed += 1
                continue
            succeeded += 1
            saved = await self._persistence.execute(ingestion)
            if saved is not None and saved.status is SaveStatus.INSERTED:
                persisted += 1
            elif saved is not None:
                already_exists += 1
        return DailyBarBatchSummary(
            1, len(rows), succeeded, failed, persisted, already_exists
        )

    @staticmethod
    def _rows(data: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
        if data is None:
            return ()
        rows = data.get("rows")
        if not isinstance(rows, (list, tuple)) or any(
            not isinstance(row, Mapping) for row in rows
        ):
            raise ValueError("provider daily response must contain immutable rows")
        return tuple(rows)
