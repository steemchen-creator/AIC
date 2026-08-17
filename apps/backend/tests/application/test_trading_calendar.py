from datetime import UTC, date, datetime

import pytest

from aic_backend.application.ports.historical import BackfillAttemptStatus
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.application.use_cases import BackfillTradingCalendar, TradingCalendarService
from aic_backend.data_foundation.tushare_calendar import TushareCalendarNormalizer
from aic_backend.domain.market_data import (
    Market,
    TradingSession,
    TradingSessionDay,
    standard_a_share_session,
)
from aic_backend.infrastructure.calendar_persistence import (
    InMemoryCalendarCoverageRepository,
    InMemoryTradingCalendarRepository,
)
from aic_backend.provider_runtime import ProviderInvocationResult, ProviderRequestContext
from aic_backend.providers.tushare import TUSHARE_CALENDAR

NOW = datetime(2026, 8, 20, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


class Runtime:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.calls = 0

    async def execute(self, context: ProviderRequestContext, payload):
        self.calls += 1
        assert context.capability == TUSHARE_CALENDAR
        assert payload["exchange"] in {"SSE", "SZSE"}
        return ProviderInvocationResult(
            context.request_id,
            "tushare_pro",
            True,
            {"rows": self.rows},
            None,
            1,
            NOW,
            NOW,
        )


def build(rows: list[object]):
    repository = InMemoryTradingCalendarRepository()
    coverage = InMemoryCalendarCoverageRepository()
    runtime = Runtime(rows)
    backfill = BackfillTradingCalendar(
        runtime,
        TUSHARE_CALENDAR,
        repository,
        coverage,
        TushareCalendarNormalizer(),
        Clock(),
        Ids(),
    )
    return backfill, TradingCalendarService(repository, coverage), repository, coverage, runtime


def test_standard_session_has_break_and_timezone() -> None:
    session = standard_a_share_session(date(2026, 8, 17))
    assert (session.morning_open.hour, session.break_start.hour) == (1, 3)
    assert (session.break_end.hour, session.session_close.hour) == (5, 7)
    assert session.session_close.tzinfo is UTC


def test_calendar_fact_validation() -> None:
    with pytest.raises(ValueError):
        TradingSessionDay(Market.CN_SSE, date(2026, 8, 17), True, None, NOW, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TradingSession(datetime(2026, 8, 17, 9), NOW, NOW, NOW)
    session = standard_a_share_session(date(2026, 8, 17))
    with pytest.raises(ValueError):
        TradingSession(
            session.session_close, session.break_start, session.break_end, session.morning_open
        )
    with pytest.raises(ValueError):
        TradingSessionDay(
            Market.CN_SSE, date(2026, 8, 17), False, session, NOW, stored_provenance()
        )
    with pytest.raises(ValueError, match="SSE or SZSE"):
        TradingSessionDay(
            "CN.OTHER",  # type: ignore[arg-type]
            date(2026, 8, 17),
            True,
            session,
            NOW,
            stored_provenance(),
        )
    with pytest.raises(ValueError, match="retrieved_at"):
        TradingSessionDay(
            Market.CN_SSE,
            date(2026, 8, 17),
            True,
            session,
            datetime(2026, 8, 17),
            stored_provenance(),
        )


async def test_in_memory_repository_rejects_conflicts_and_orders_ranges() -> None:
    repository = InMemoryTradingCalendarRepository()
    normalizer = TushareCalendarNormalizer()
    original = normalizer.normalize(
        {"exchange": "SSE", "cal_date": "20260817", "is_open": "1"},
        provider_id="fixture",
        retrieved_at=NOW,
    )
    conflicting = normalizer.normalize(
        {"exchange": "SSE", "cal_date": "20260817", "is_open": "0"},
        provider_id="fixture",
        retrieved_at=NOW,
    )
    await repository.save(original)
    with pytest.raises(PersistenceError, match="calendar identity conflict"):
        await repository.save(conflicting)


def stored_provenance():
    return (
        TushareCalendarNormalizer()
        .normalize(
            {"exchange": "SSE", "cal_date": "20260817", "is_open": "1"},
            provider_id="fixture",
            retrieved_at=NOW,
        )
        .provenance
    )


async def test_backfill_persists_open_closed_and_is_idempotent() -> None:
    rows = [
        {"exchange": "SSE", "cal_date": "20260817", "is_open": "1"},
        {"exchange": "SSE", "cal_date": "20260816", "is_open": "0"},
    ]
    backfill, service, _, coverage, runtime = build(rows)
    first = await backfill.execute(Market.CN_SSE, date(2026, 8, 16), date(2026, 8, 17))
    second = await backfill.execute(Market.CN_SSE, date(2026, 8, 16), date(2026, 8, 17))
    assert first.status is BackfillAttemptStatus.COMPLETED
    assert (first.persisted, second.persisted, second.already_exists) == (2, 0, 0)
    assert await service.is_trading_day(Market.CN_SSE, date(2026, 8, 17)) is True
    assert await service.is_trading_day(Market.CN_SSE, date(2026, 8, 16)) is False
    assert await service.is_trading_day(Market.CN_SZSE, date(2026, 8, 17)) is None
    assert len(coverage.attempts) == 1
    assert runtime.calls == 1


async def test_query_range_previous_next_and_order() -> None:
    rows = [
        {"exchange": "SZSE", "cal_date": "20260818", "is_open": "1"},
        {"exchange": "SZSE", "cal_date": "20260816", "is_open": "0"},
        {"exchange": "SZSE", "cal_date": "20260817", "is_open": "1"},
    ]
    backfill, service, _, _, _ = build(rows)
    await backfill.execute(Market.CN_SZSE, date(2026, 8, 16), date(2026, 8, 18))
    days = await service.list_trading_days(Market.CN_SZSE, date(2026, 8, 16), date(2026, 8, 18))
    assert tuple(day.trading_date for day in days) == (date(2026, 8, 17), date(2026, 8, 18))
    assert await service.previous_trading_day(Market.CN_SZSE, date(2026, 8, 18)) == date(
        2026, 8, 17
    )
    assert await service.next_trading_day(Market.CN_SZSE, date(2026, 8, 17)) == date(2026, 8, 18)


@pytest.mark.parametrize(
    "row",
    [
        {"exchange": "X", "cal_date": "20260817", "is_open": "1"},
        {"exchange": "SSE", "cal_date": "bad", "is_open": "1"},
        {"exchange": "SSE", "cal_date": "20260817", "is_open": "x"},
    ],
)
async def test_invalid_rows_make_partial_result(row: dict[str, object]) -> None:
    backfill, _, _, coverage, _ = build([row])
    result = await backfill.execute(Market.CN_SSE, date(2026, 8, 17), date(2026, 8, 17))
    assert result.status is BackfillAttemptStatus.PARTIAL
    assert result.failed == 1
    assert coverage.attempts[0].status is BackfillAttemptStatus.PARTIAL


async def test_malformed_envelope_is_failed_and_recorded() -> None:
    backfill, _, _, coverage, runtime = build([])
    runtime.rows = ["bad"]
    result = await backfill.execute(Market.CN_SSE, date(2026, 8, 17), date(2026, 8, 17))
    assert result.status is BackfillAttemptStatus.FAILED
    assert result.error_code == "ValueError"
    assert coverage.attempts[0].status is BackfillAttemptStatus.FAILED


def test_backfill_rejects_invalid_chunk_size() -> None:
    repository = InMemoryTradingCalendarRepository()
    coverage = InMemoryCalendarCoverageRepository()
    with pytest.raises(ValueError, match="chunk_days"):
        BackfillTradingCalendar(
            Runtime([]),
            TUSHARE_CALENDAR,
            repository,
            coverage,
            TushareCalendarNormalizer(),
            Clock(),
            Ids(),
            chunk_days=0,
        )


def test_normalizer_rejects_naive_retrieval_time() -> None:
    with pytest.raises(ValueError, match="retrieved_at"):
        TushareCalendarNormalizer().normalize(
            {"exchange": "SSE", "cal_date": "20260817", "is_open": "1"},
            provider_id="fixture",
            retrieved_at=datetime(2026, 8, 17),
        )
