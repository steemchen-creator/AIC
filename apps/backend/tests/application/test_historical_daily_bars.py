from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.application.ports import (
    BackfillAttempt,
    BackfillAttemptStatus,
    DateInterval,
    PersistedDailyBar,
)
from aic_backend.application.ports.calendar import CalendarCoverageAttempt
from aic_backend.application.use_cases import (
    CoverageStatus,
    HistoricalDailyBarService,
    missing_intervals,
)
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
    TradingSessionDay,
    standard_a_share_session,
)
from aic_backend.infrastructure.calendar_persistence import (
    InMemoryCalendarCoverageRepository,
    InMemoryTradingCalendarRepository,
)
from aic_backend.infrastructure.canonical_persistence import InMemoryCanonicalDailyBarRepository
from aic_backend.infrastructure.historical_persistence import InMemoryBackfillMetadataRepository

NOW = datetime(2026, 1, 10, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


def stored(day: int) -> PersistedDailyBar:
    trading_date = date(2026, 1, day)
    event = datetime(2026, 1, day, 7, tzinfo=UTC)
    provenance = DataProvenance(
        "fixture",
        f"source-{day}",
        f"fixture://daily/{day}",
        None,
        False,
        0,
        f"{day:064x}",
        "v1",
    )
    record = DailyBar(
        f"record-{day}",
        "1.0",
        INSTRUMENT,
        trading_date,
        event,
        NOW,
        NOW,
        provenance,
        Decimal("10"),
        Decimal("11"),
        Decimal("9"),
        Decimal("10"),
        100,
        Decimal("1000"),
    )
    return PersistedDailyBar(
        f"observation-{day}", record, DataQualityAssessment(100, 100, 100, 100, 100)
    )


def attempt(start: int, end: int) -> BackfillAttempt:
    return BackfillAttempt(
        f"attempt-{start}-{end}",
        "fixture",
        "market.daily.read",
        INSTRUMENT,
        DateInterval(date(2026, 1, start), date(2026, 1, end)),
        NOW,
        NOW,
        BackfillAttemptStatus.COMPLETED,
        0,
        0,
        0,
        0,
    )


def test_missing_intervals_merge_overlap_and_preserve_inclusive_edges() -> None:
    requested = DateInterval(date(2026, 1, 1), date(2026, 1, 10))
    confirmed = (
        DateInterval(date(2025, 12, 20), date(2026, 1, 2)),
        DateInterval(date(2026, 1, 3), date(2026, 1, 4)),
        DateInterval(date(2026, 1, 7), date(2026, 1, 8)),
    )
    assert missing_intervals(requested, confirmed) == (
        DateInterval(date(2026, 1, 5), date(2026, 1, 6)),
        DateInterval(date(2026, 1, 9), date(2026, 1, 10)),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt_id": ""},
        {"capability": ""},
        {"requested_at": datetime(2026, 1, 10)},
        {"completed_at": datetime(2026, 1, 9, tzinfo=UTC)},
        {"failed_count": -1},
    ],
)
def test_backfill_attempt_rejects_invalid_operational_evidence(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "attempt_id": "attempt-1",
        "provider_id": "fixture",
        "capability": "market.daily.read",
        "instrument": INSTRUMENT,
        "interval": DateInterval(date(2026, 1, 1), date(2026, 1, 2)),
        "requested_at": NOW,
        "completed_at": NOW,
        "status": BackfillAttemptStatus.COMPLETED,
        "received_count": 0,
        "persisted_count": 0,
        "already_exists_count": 0,
        "failed_count": 0,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        BackfillAttempt(**values)  # type: ignore[arg-type]


async def test_empty_query_is_read_only_and_reports_unconfirmed_range() -> None:
    service = HistoricalDailyBarService(
        InMemoryCanonicalDailyBarRepository(), InMemoryBackfillMetadataRepository()
    )
    result = await service.get_daily_bars(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
    assert result.bars == ()
    assert result.coverage.coverage_status is CoverageStatus.EMPTY
    assert result.coverage.known_missing_intervals == (
        DateInterval(date(2026, 1, 1), date(2026, 1, 3)),
    )


async def test_query_is_inclusive_ordered_deterministic_and_preserves_canonical_data() -> None:
    repository = InMemoryCanonicalDailyBarRepository()
    metadata = InMemoryBackfillMetadataRepository()
    for value in (stored(3), stored(1), stored(2), stored(2)):
        await repository.save(value)
    await metadata.record(attempt(1, 3))
    service = HistoricalDailyBarService(repository, metadata)
    first = await service.get_daily_bars(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
    second = await service.get_daily_bars(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
    assert first == second
    assert tuple(item.record.trading_date.day for item in first.bars) == (1, 2, 3)
    assert first.coverage.coverage_status is CoverageStatus.COVERED
    assert first.coverage.earliest_available_date == date(2026, 1, 1)
    assert first.bars[0].record.volume == 100
    assert first.bars[0].record.provenance.provider_id == "fixture"


async def test_partial_confirmed_coverage_does_not_invent_trading_days() -> None:
    metadata = InMemoryBackfillMetadataRepository()
    await metadata.record(attempt(1, 2))
    result = await HistoricalDailyBarService(
        InMemoryCanonicalDailyBarRepository(), metadata
    ).get_daily_bars(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 5))
    assert result.coverage.coverage_status is CoverageStatus.PARTIAL
    assert result.coverage.known_missing_intervals == (
        DateInterval(date(2026, 1, 3), date(2026, 1, 5)),
    )
    assert result.coverage.last_backfill_at == NOW


async def test_calendar_excludes_closed_dates_and_reports_open_candidate_gap() -> None:
    bars = InMemoryCanonicalDailyBarRepository()
    await bars.save(stored(1))
    calendar = InMemoryTradingCalendarRepository()
    calendar_coverage = InMemoryCalendarCoverageRepository()
    provenance = stored(1).record.provenance
    for day, is_open in ((1, True), (2, False), (3, True)):
        value = date(2026, 1, day)
        await calendar.save(
            TradingSessionDay(
                Market.CN_SSE,
                value,
                is_open,
                standard_a_share_session(value) if is_open else None,
                NOW,
                provenance,
            )
        )
    await calendar_coverage.record(
        CalendarCoverageAttempt(
            "calendar-1",
            "fixture",
            Market.CN_SSE,
            DateInterval(date(2026, 1, 1), date(2026, 1, 3)),
            NOW,
            NOW,
            BackfillAttemptStatus.COMPLETED,
            3,
            3,
            0,
            0,
        )
    )
    result = await HistoricalDailyBarService(
        bars,
        InMemoryBackfillMetadataRepository(),
        calendar,
        calendar_coverage,
    ).get_daily_bars(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
    assert result.coverage.calendar_coverage_complete is True
    assert result.coverage.expected_missing_dates == (date(2026, 1, 3),)


async def test_partial_calendar_coverage_never_claims_candidate_gaps() -> None:
    result = await HistoricalDailyBarService(
        InMemoryCanonicalDailyBarRepository(),
        InMemoryBackfillMetadataRepository(),
        InMemoryTradingCalendarRepository(),
        InMemoryCalendarCoverageRepository(),
    ).get_daily_bars(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
    assert result.coverage.calendar_coverage_complete is False
    assert result.coverage.expected_missing_dates == ()
