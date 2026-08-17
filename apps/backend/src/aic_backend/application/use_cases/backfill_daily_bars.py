"""Sequential, resumable historical DailyBar backfill orchestration."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

from aic_backend.application.ports.historical import (
    BackfillAttempt,
    BackfillAttemptStatus,
    BackfillMetadataRepository,
    DateInterval,
)
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.application.use_cases.historical_daily_bars import (
    HistoricalDailyBarSeries,
    HistoricalDailyBarService,
)
from aic_backend.application.use_cases.ingest_daily_bars import IngestDailyBars
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.provider_runtime import Clock, IdGenerator
from aic_backend.provider_runtime.errors import ProviderRuntimeError

logger = logging.getLogger(__name__)


class BackfillStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class FailedBackfillInterval:
    interval: DateInterval
    error_code: str


@dataclass(frozen=True, slots=True)
class DailyBarBackfillResult:
    instrument: InstrumentIdentity
    requested_start: date
    requested_end: date
    chunks_attempted: int
    chunks_succeeded: int
    rows_received: int
    rows_valid: int
    rows_failed: int
    rows_inserted: int
    rows_already_existing: int
    identity_conflicts: int
    final_status: BackfillStatus
    failed_intervals: tuple[FailedBackfillInterval, ...]
    series: HistoricalDailyBarSeries


def chunk_intervals(
    intervals: tuple[DateInterval, ...],
    chunk_days: int,
) -> tuple[DateInterval, ...]:
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
    chunks: list[DateInterval] = []
    for interval in intervals:
        start = interval.start
        while start <= interval.end:
            end = min(interval.end, start + timedelta(days=chunk_days - 1))
            chunks.append(DateInterval(start, end))
            start = end + timedelta(days=1)
    return tuple(chunks)


class BackfillDailyBars:
    def __init__(
        self,
        historical: HistoricalDailyBarService,
        ingestion: IngestDailyBars,
        metadata: BackfillMetadataRepository,
        clock: Clock,
        ids: IdGenerator,
        *,
        chunk_days: int = 365,
    ) -> None:
        if chunk_days <= 0:
            raise ValueError("chunk_days must be positive")
        self._historical = historical
        self._ingestion = ingestion
        self._metadata = metadata
        self._clock = clock
        self._ids = ids
        self._chunk_days = chunk_days

    async def execute(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
        *,
        force_refresh: bool = False,
    ) -> DailyBarBackfillResult:
        requested = DateInterval(start, end)
        before = await self._historical.get_daily_bars(instrument, start, end)
        intervals = (requested,) if force_refresh else before.coverage.known_missing_intervals
        chunks = chunk_intervals(intervals, self._chunk_days)
        attempted = succeeded = received = valid = failed = inserted = existing = conflicts = 0
        failures: list[FailedBackfillInterval] = []
        for chunk in chunks:
            attempted += 1
            requested_at = self._clock.now()
            provider_id = "unselected"
            summary = None
            try:
                summary = await self._ingestion.execute(self._parameters(instrument, chunk))
                provider_id = summary.provider_id
                received += summary.received
                valid += summary.succeeded
                failed += summary.failed
                inserted += summary.persisted
                existing += summary.already_exists
                conflicts += summary.identity_conflicts
                status = (
                    BackfillAttemptStatus.COMPLETED
                    if summary.failed == 0 and summary.identity_conflicts == 0
                    else BackfillAttemptStatus.PARTIAL
                )
                if status is BackfillAttemptStatus.COMPLETED:
                    succeeded += 1
                else:
                    failures.append(FailedBackfillInterval(chunk, "ROW_PROCESSING_FAILED"))
            except (ProviderRuntimeError, PersistenceError, ValueError) as error:
                if isinstance(error, ProviderRuntimeError) and error.provider_id:
                    provider_id = error.provider_id
                error_code = self._error_code(error)
                status = BackfillAttemptStatus.FAILED
                failures.append(FailedBackfillInterval(chunk, error_code))
            completed_at = self._clock.now()
            await self._metadata.record(
                BackfillAttempt(
                    self._ids.new_id("backfill"),
                    provider_id,
                    "market.daily.read",
                    instrument,
                    chunk,
                    requested_at,
                    completed_at,
                    status,
                    summary.received if summary is not None else 0,
                    summary.persisted if summary is not None else 0,
                    summary.already_exists if summary is not None else 0,
                    summary.failed if summary is not None else 0,
                    (
                        failures[-1].error_code
                        if status is not BackfillAttemptStatus.COMPLETED
                        else None
                    ),
                )
            )
            if status is not BackfillAttemptStatus.COMPLETED:
                break
        after = await self._historical.get_daily_bars(instrument, start, end)
        final_status = (
            BackfillStatus.COMPLETED
            if not failures
            else BackfillStatus.PARTIAL
            if succeeded or inserted or existing
            else BackfillStatus.FAILED
        )
        logger.info(
            "historical_daily_bar_backfill",
            extra={
                "instrument": instrument.canonical_key,
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "chunks_attempted": attempted,
                "rows_received": received,
                "rows_inserted": inserted,
                "rows_already_existing": existing,
                "rows_failed": failed,
                "final_status": final_status.value,
            },
        )
        return DailyBarBackfillResult(
            instrument,
            start,
            end,
            attempted,
            succeeded,
            received,
            valid,
            failed,
            inserted,
            existing,
            conflicts,
            final_status,
            tuple(failures),
            after,
        )

    @staticmethod
    def _parameters(
        instrument: InstrumentIdentity,
        interval: DateInterval,
    ) -> Mapping[str, Any]:
        return {
            "symbol": instrument.symbol,
            "market": instrument.market.value,
            "start_date": interval.start.isoformat(),
            "end_date": interval.end.isoformat(),
        }

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, ProviderRuntimeError):
            return error.error_code
        if isinstance(error, PersistenceError):
            return error.code.value
        return "INVALID_BACKFILL_REQUEST"
