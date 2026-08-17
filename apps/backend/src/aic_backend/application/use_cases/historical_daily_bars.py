"""Historical canonical query and conservative coverage calculation."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from aic_backend.application.ports.historical import (
    BackfillAttemptStatus,
    BackfillMetadataRepository,
    DateInterval,
)
from aic_backend.application.ports.persistence import (
    CanonicalDailyBarRepository,
    PersistedDailyBar,
)
from aic_backend.domain.market_data import InstrumentIdentity


class CoverageStatus(StrEnum):
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    COVERED = "COVERED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DailyBarCoverage:
    instrument: InstrumentIdentity
    requested_start: date
    requested_end: date
    earliest_available_date: date | None
    latest_available_date: date | None
    canonical_row_count: int
    coverage_status: CoverageStatus
    known_missing_intervals: tuple[DateInterval, ...]
    last_backfill_at: datetime | None


@dataclass(frozen=True, slots=True)
class HistoricalDailyBarSeries:
    bars: tuple[PersistedDailyBar, ...]
    coverage: DailyBarCoverage


def missing_intervals(
    requested: DateInterval,
    confirmed: tuple[DateInterval, ...],
) -> tuple[DateInterval, ...]:
    clipped = sorted(
        (
            DateInterval(max(item.start, requested.start), min(item.end, requested.end))
            for item in confirmed
            if item.end >= requested.start and item.start <= requested.end
        ),
        key=lambda item: (item.start, item.end),
    )
    merged: list[DateInterval] = []
    for item in clipped:
        if merged and item.start <= merged[-1].end + timedelta(days=1):
            merged[-1] = DateInterval(merged[-1].start, max(merged[-1].end, item.end))
        else:
            merged.append(item)
    cursor = requested.start
    gaps: list[DateInterval] = []
    for item in merged:
        if cursor < item.start:
            gaps.append(DateInterval(cursor, item.start - timedelta(days=1)))
        cursor = max(cursor, item.end + timedelta(days=1))
    if cursor <= requested.end:
        gaps.append(DateInterval(cursor, requested.end))
    return tuple(gaps)


class HistoricalDailyBarService:
    def __init__(
        self,
        repository: CanonicalDailyBarRepository,
        metadata: BackfillMetadataRepository,
    ) -> None:
        self._repository = repository
        self._metadata = metadata

    async def get_daily_bars(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
    ) -> HistoricalDailyBarSeries:
        requested = DateInterval(start, end)
        stored = await self._repository.get_daily_bars(instrument, start, end)
        bars = tuple(
            sorted(
                stored,
                key=lambda item: (item.record.trading_date, item.record.record_id),
            )
        )
        attempts = await self._metadata.get_attempts(instrument, start, end)
        confirmed = tuple(
            item.interval
            for item in attempts
            if item.status is BackfillAttemptStatus.COMPLETED
        )
        gaps = missing_intervals(requested, confirmed)
        if not bars and not confirmed:
            status = CoverageStatus.EMPTY
        elif not gaps:
            status = CoverageStatus.COVERED
        else:
            status = CoverageStatus.PARTIAL
        dates = tuple(item.record.trading_date for item in bars)
        completed = tuple(item.completed_at for item in attempts)
        coverage = DailyBarCoverage(
            instrument,
            start,
            end,
            min(dates) if dates else None,
            max(dates) if dates else None,
            len(bars),
            status,
            gaps,
            max(completed) if completed else None,
        )
        return HistoricalDailyBarSeries(bars, coverage)
