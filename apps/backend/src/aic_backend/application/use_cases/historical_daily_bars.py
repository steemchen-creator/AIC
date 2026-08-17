"""Historical canonical query and conservative coverage calculation."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from aic_backend.application.ports.calendar import (
    CalendarCoverageRepository,
    TradingCalendarRepository,
)
from aic_backend.application.ports.historical import (
    BackfillAttemptStatus,
    BackfillMetadataRepository,
    DateInterval,
)
from aic_backend.application.ports.instruments import (
    InstrumentCoverageRepository,
    InstrumentMasterRepository,
    InstrumentTradingStatusRepository,
)
from aic_backend.application.ports.persistence import (
    CanonicalDailyBarRepository,
    PersistedDailyBar,
)
from aic_backend.application.use_cases.adjusted_daily_bars import AdjustmentService
from aic_backend.domain.market_data import (
    AdjustedDailyBar,
    AdjustmentMode,
    InstrumentIdentity,
    InstrumentTradingState,
    TradingSessionDay,
)


class CoverageStatus(StrEnum):
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    COVERED = "COVERED"
    UNKNOWN = "UNKNOWN"


class GapClassification(StrEnum):
    NOT_EXPECTED_MARKET_CLOSED = "NOT_EXPECTED_MARKET_CLOSED"
    NOT_EXPECTED_NOT_LISTED = "NOT_EXPECTED_NOT_LISTED"
    NOT_EXPECTED_DELISTED = "NOT_EXPECTED_DELISTED"
    NOT_EXPECTED_SUSPENDED = "NOT_EXPECTED_SUSPENDED"
    PROBABLE_DATA_GAP = "PROBABLE_DATA_GAP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DailyBarGap:
    trading_date: date
    classification: GapClassification


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
    expected_missing_dates: tuple[date, ...] = ()
    calendar_coverage_complete: bool = False
    gap_classifications: tuple[DailyBarGap, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoricalDailyBarSeries:
    bars: tuple[PersistedDailyBar, ...]
    coverage: DailyBarCoverage
    adjustment_mode: AdjustmentMode = AdjustmentMode.RAW
    adjusted_bars: tuple[AdjustedDailyBar, ...] = ()


def _dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


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
        calendar: TradingCalendarRepository | None = None,
        calendar_coverage: CalendarCoverageRepository | None = None,
        instruments: InstrumentMasterRepository | None = None,
        trading_statuses: InstrumentTradingStatusRepository | None = None,
        instrument_coverage: InstrumentCoverageRepository | None = None,
        trading_status_capability: str = "instrument.trading_status.read",
        adjustment: AdjustmentService | None = None,
    ) -> None:
        self._repository = repository
        self._metadata = metadata
        self._calendar = calendar
        self._calendar_coverage = calendar_coverage
        self._instruments = instruments
        self._trading_statuses = trading_statuses
        self._instrument_coverage = instrument_coverage
        self._trading_status_capability = trading_status_capability
        self._adjustment = adjustment

    async def get_daily_bars(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
        adjustment_mode: AdjustmentMode = AdjustmentMode.RAW,
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
            item.interval for item in attempts if item.status is BackfillAttemptStatus.COMPLETED
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
        candidate_missing: tuple[date, ...] = ()
        classifications: tuple[DailyBarGap, ...] = ()
        calendar_complete = False
        if self._calendar is not None and self._calendar_coverage is not None:
            calendar_attempts = await self._calendar_coverage.get_attempts(
                instrument.market, start, end
            )
            calendar_confirmed = tuple(
                item.interval
                for item in calendar_attempts
                if item.status is BackfillAttemptStatus.COMPLETED
            )
            calendar_complete = not missing_intervals(requested, calendar_confirmed)
            if calendar_complete:
                days = await self._calendar.list_days(instrument.market, start, end)
                stored_dates = set(dates)
                candidate_missing = tuple(
                    item.trading_date
                    for item in days
                    if item.is_open and item.trading_date not in stored_dates
                )
                if (
                    self._instruments is not None
                    and self._trading_statuses is not None
                    and self._instrument_coverage is not None
                ):
                    classifications = await self._classify_gaps(
                        instrument, start, end, stored_dates, days
                    )
            elif (
                self._instruments is not None
                and self._trading_statuses is not None
                and self._instrument_coverage is not None
            ):
                stored_dates = set(dates)
                classifications = tuple(
                    DailyBarGap(value, GapClassification.UNKNOWN)
                    for value in _dates(start, end)
                    if value not in stored_dates
                )
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
            candidate_missing,
            calendar_complete,
            classifications,
        )
        adjusted: tuple[AdjustedDailyBar, ...] = ()
        if adjustment_mode is not AdjustmentMode.RAW:
            if self._adjustment is None:
                raise ValueError("UNSUPPORTED_ADJUSTMENT_MODE")
            adjusted = await self._adjustment.adjust(bars, adjustment_mode)
        return HistoricalDailyBarSeries(bars, coverage, adjustment_mode, adjusted)

    async def _classify_gaps(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
        stored_dates: set[date],
        calendar_days: tuple[TradingSessionDay, ...],
    ) -> tuple[DailyBarGap, ...]:
        assert self._instruments is not None
        assert self._trading_statuses is not None
        assert self._instrument_coverage is not None
        master = await self._instruments.get_instrument(instrument)
        attempts = await self._instrument_coverage.get_attempts(
            self._trading_status_capability, instrument.market, instrument, start, end
        )
        confirmed = tuple(
            item.interval
            for item in attempts
            if item.status is BackfillAttemptStatus.COMPLETED and item.interval is not None
        )
        status_complete = not missing_intervals(DateInterval(start, end), confirmed)
        calendar_by_date = {item.trading_date: item for item in calendar_days}
        current = start
        results: list[DailyBarGap] = []
        while current <= end:
            if current not in stored_dates:
                day = calendar_by_date.get(current)
                classification = GapClassification.UNKNOWN
                if day is not None and not day.is_open:
                    classification = GapClassification.NOT_EXPECTED_MARKET_CLOSED
                elif day is not None and master is not None and master.listing_date is not None:
                    if current < master.listing_date:
                        classification = GapClassification.NOT_EXPECTED_NOT_LISTED
                    elif master.delisting_date is not None and current > master.delisting_date:
                        classification = GapClassification.NOT_EXPECTED_DELISTED
                    elif status_complete:
                        status = await self._trading_statuses.get_trading_status(
                            instrument, current
                        )
                        if status is not None and status.state is InstrumentTradingState.SUSPENDED:
                            classification = GapClassification.NOT_EXPECTED_SUSPENDED
                        elif status is not None and status.state is InstrumentTradingState.TRADING:
                            classification = GapClassification.PROBABLE_DATA_GAP
                results.append(DailyBarGap(current, classification))
            current += timedelta(days=1)
        return tuple(results)
