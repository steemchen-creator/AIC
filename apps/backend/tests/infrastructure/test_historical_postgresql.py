import asyncio
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.ports.calendar import CalendarCoverageAttempt
from aic_backend.application.ports.historical import (
    BackfillAttempt,
    BackfillAttemptStatus,
    DateInterval,
)
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.application.use_cases import (
    BackfillDailyBars,
    BackfillStatus,
    BackfillTradingCalendar,
    HistoricalDailyBarService,
    IngestDailyBars,
    PersistIngestionSuccess,
    TradingCalendarService,
)
from aic_backend.data_foundation import DataIngestionPipeline
from aic_backend.data_foundation.quality import DailyBarQualityAssessor
from aic_backend.data_foundation.tushare_calendar import TushareCalendarNormalizer
from aic_backend.data_foundation.tushare_normalization import TushareDailyBarNormalizer
from aic_backend.data_foundation.validation import DailyBarValidator, ValidationContext
from aic_backend.domain.market_data import (
    DailyBar,
    InstrumentIdentity,
    InstrumentType,
    Market,
)
from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.infrastructure.calendar_persistence import (
    PostgreSQLCalendarCoverageRepository,
    PostgreSQLTradingCalendarRepository,
    calendar_backfill_attempts,
    trading_calendar_days,
)
from aic_backend.infrastructure.canonical_persistence import (
    PostgreSQLCanonicalDailyBarRepository,
    canonical_daily_bars,
)
from aic_backend.infrastructure.historical_persistence import (
    PostgreSQLBackfillMetadataRepository,
    daily_bar_backfill_attempts,
)
from aic_backend.provider_runtime import (
    FailoverPolicy,
    ProviderDefinition,
    ProviderFailoverManager,
    ProviderHealthManager,
    ProviderInvocationManager,
    ProviderLifecycleManager,
    ProviderRegistry,
    ProviderRuntime,
    ProviderSelector,
    QualityScorer,
)
from aic_backend.provider_runtime.models import HealthCheckPolicy
from aic_backend.providers.tushare import (
    TUSHARE_CALENDAR,
    TUSHARE_DAILY,
    TushareDailyProvider,
)

NOW = datetime(2026, 1, 10, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


class TushareFixtureClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, url: str, *, json: Mapping[str, Any], timeout: float) -> httpx.Response:
        del url, timeout
        self.calls += 1
        params = json["params"]
        assert isinstance(params, Mapping)
        assert params["ts_code"] == "600000.SH"
        assert params["start_date"] == "20260101"
        assert params["end_date"] == "20260103"
        fields = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
        items = [
            ["600000.SH", "20260103", "10.3", "10.8", "10.1", "10.5", "12", "2"],
            ["600000.SH", "20260102", "10.1", "10.5", "9.9", "10.2", "10", "1"],
        ]
        return httpx.Response(
            200,
            json={"code": 0, "data": {"fields": fields, "items": items}},
            request=httpx.Request("POST", "https://fixture.invalid"),
        )


@pytest.fixture
async def engine() -> AsyncEngine:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=environment)
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        await connection.execute(delete(calendar_backfill_attempts))
        await connection.execute(delete(trading_calendar_days))
        await connection.execute(delete(daily_bar_backfill_attempts))
        await connection.execute(delete(canonical_daily_bars))
    yield value
    await value.dispose()


async def build_backfill(
    engine: AsyncEngine,
) -> tuple[BackfillDailyBars, HistoricalDailyBarService, TushareFixtureClient]:
    clock = FixedClock()
    ids = SequentialIds()
    registry = ProviderRegistry(clock)
    lifecycle = ProviderLifecycleManager(registry, InMemoryEventBus(), clock, ids)
    client = TushareFixtureClient()
    definition = ProviderDefinition(
        "tushare_pro",
        "providers.tushare_daily",
        True,
        100,
        frozenset({TUSHARE_DAILY}),
        {},
    )
    provider = TushareDailyProvider(definition, "fixture-token", client)
    await lifecycle.register(provider)
    await lifecycle.initialize("tushare_pro")
    health = ProviderHealthManager(
        registry,
        lifecycle,
        clock,
        HealthCheckPolicy(timeout_ms=100, failure_threshold=2, recovery_threshold=1),
    )
    await health.check_once("tushare_pro")
    invocation = ProviderInvocationManager(registry, clock, {"tushare_pro": 1})
    runtime = ProviderRuntime(
        registry,
        ProviderFailoverManager(ProviderSelector(QualityScorer()), invocation, FailoverPolicy()),
        clock,
    )
    canonical = PostgreSQLCanonicalDailyBarRepository(engine)
    metadata = PostgreSQLBackfillMetadataRepository(engine)
    pipeline = DataIngestionPipeline(
        {DailyBar.RECORD_TYPE: TushareDailyBarNormalizer()},
        DailyBarValidator(ValidationContext(clock, timedelta(minutes=5), frozenset({"1.0"}))),
        DailyBarQualityAssessor(),
    )
    ingestion = IngestDailyBars(
        runtime, TUSHARE_DAILY, pipeline, PersistIngestionSuccess(canonical), clock, ids
    )
    historical = HistoricalDailyBarService(canonical, metadata)
    return (
        BackfillDailyBars(historical, ingestion, metadata, clock, ids, chunk_days=30),
        historical,
        client,
    )


async def test_historical_runtime_tushare_postgresql_e2e_is_ordered_and_idempotent(
    engine: AsyncEngine,
) -> None:
    backfill, historical, client = await build_backfill(engine)
    first = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
    second = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
    assert first.final_status is BackfillStatus.COMPLETED
    assert first.rows_inserted == 2
    assert second.chunks_attempted == 0
    assert client.calls == 1
    series = await historical.get_daily_bars(INSTRUMENT, date(2026, 1, 2), date(2026, 1, 3))
    assert tuple(item.record.trading_date for item in series.bars) == (
        date(2026, 1, 2),
        date(2026, 1, 3),
    )
    assert series.bars[0].record.volume == 1000
    assert series.bars[0].record.turnover == 1000
    assert series.bars[0].record.provenance.provider_id == "tushare_pro"
    async with engine.connect() as connection:
        facts = await connection.scalar(select(func.count()).select_from(canonical_daily_bars))
        attempts = await connection.scalar(
            select(func.count()).select_from(daily_bar_backfill_attempts)
        )
    assert facts == 2
    assert attempts == 1


async def test_concurrent_duplicate_backfill_preserves_unique_canonical_facts(
    engine: AsyncEngine,
) -> None:
    backfill, _, client = await build_backfill(engine)
    results = await asyncio.gather(
        backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3)),
        backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3)),
    )
    assert sum(item.rows_inserted for item in results) == 2
    assert sum(item.rows_already_existing for item in results) == 2
    assert client.calls == 2
    async with engine.connect() as connection:
        facts = await connection.scalar(select(func.count()).select_from(canonical_daily_bars))
        attempts = await connection.scalar(
            select(func.count()).select_from(daily_bar_backfill_attempts)
        )
    assert facts == 2
    assert attempts == 2


async def test_postgresql_adapters_translate_write_and_read_failures(
    engine: AsyncEngine,
) -> None:
    metadata = PostgreSQLBackfillMetadataRepository(engine)
    attempt = BackfillAttempt(
        "duplicate-attempt",
        "tushare_pro",
        TUSHARE_DAILY.name,
        INSTRUMENT,
        DateInterval(date(2026, 1, 1), date(2026, 1, 3)),
        NOW,
        NOW,
        BackfillAttemptStatus.COMPLETED,
        0,
        0,
        0,
        0,
        None,
    )
    await metadata.record(attempt)
    with pytest.raises(PersistenceError) as duplicate:
        await metadata.record(attempt)
    assert duplicate.value.code is PersistenceErrorCode.TRANSACTION_ERROR

    unavailable = create_async_engine(
        "postgresql+asyncpg://aic:redacted@127.0.0.1:1/missing",
        pool_pre_ping=True,
    )
    unavailable_metadata = PostgreSQLBackfillMetadataRepository(unavailable)
    unavailable_canonical = PostgreSQLCanonicalDailyBarRepository(unavailable)
    try:
        with pytest.raises(PersistenceError) as metadata_error:
            await unavailable_metadata.get_attempts(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3))
        assert metadata_error.value.code is PersistenceErrorCode.UNAVAILABLE
        with pytest.raises(PersistenceError) as canonical_error:
            await unavailable_canonical.get_daily_bars(
                INSTRUMENT, date(2026, 1, 1), date(2026, 1, 3)
            )
        assert canonical_error.value.code is PersistenceErrorCode.UNAVAILABLE
    finally:
        await unavailable.dispose()


async def test_historical_queries_reject_reversed_ranges(engine: AsyncEngine) -> None:
    repository = PostgreSQLCanonicalDailyBarRepository(engine)
    with pytest.raises(ValueError, match="end must not precede start"):
        await repository.get_daily_bars(INSTRUMENT, date(2026, 1, 3), date(2026, 1, 1))


def test_backfill_metadata_migration_downgrade_and_upgrade() -> None:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(["alembic", "downgrade", "20260814_0002"], check=True, env=environment)
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=environment)


def test_calendar_migration_downgrades_to_previous_head_and_upgrades() -> None:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(["alembic", "downgrade", "20260817_0003"], check=True, env=environment)
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=environment)


class CalendarFixtureClient:
    async def post(self, url: str, *, json: Mapping[str, Any], timeout: float) -> httpx.Response:
        del url, timeout
        assert json["api_name"] == "trade_cal"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": ["exchange", "cal_date", "is_open"],
                    "items": [["SSE", "20260103", "1"], ["SSE", "20260102", "0"]],
                },
            },
            request=httpx.Request("POST", "https://fixture.invalid"),
        )


async def test_calendar_runtime_postgresql_historical_gap_e2e(engine: AsyncEngine) -> None:
    clock, ids = FixedClock(), SequentialIds()
    registry = ProviderRegistry(clock)
    lifecycle = ProviderLifecycleManager(registry, InMemoryEventBus(), clock, ids)
    definition = ProviderDefinition(
        "tushare_pro",
        "providers.tushare_daily",
        True,
        100,
        frozenset({TUSHARE_DAILY, TUSHARE_CALENDAR}),
        {},
    )
    await lifecycle.register(TushareDailyProvider(definition, "fixture", CalendarFixtureClient()))
    await lifecycle.initialize("tushare_pro")
    health = ProviderHealthManager(
        registry,
        lifecycle,
        clock,
        HealthCheckPolicy(timeout_ms=100, failure_threshold=2, recovery_threshold=1),
    )
    await health.check_once("tushare_pro")
    runtime = ProviderRuntime(
        registry,
        ProviderFailoverManager(
            ProviderSelector(QualityScorer()),
            ProviderInvocationManager(registry, clock, {"tushare_pro": 1}),
            FailoverPolicy(),
        ),
        clock,
    )
    calendar = PostgreSQLTradingCalendarRepository(engine)
    coverage = PostgreSQLCalendarCoverageRepository(engine)
    result = await BackfillTradingCalendar(
        runtime,
        TUSHARE_CALENDAR,
        calendar,
        coverage,
        TushareCalendarNormalizer(),
        clock,
        ids,
    ).execute(Market.CN_SSE, date(2026, 1, 2), date(2026, 1, 3))
    assert result.status is BackfillAttemptStatus.COMPLETED
    assert result.persisted == 2
    service = TradingCalendarService(calendar, coverage)
    assert await service.is_trading_day(Market.CN_SSE, date(2026, 1, 2)) is False
    open_day = await calendar.get_day(Market.CN_SSE, date(2026, 1, 3))
    assert open_day is not None
    assert (await calendar.save(open_day)).status.value == "ALREADY_EXISTS"
    conflicting = TushareCalendarNormalizer().normalize(
        {"exchange": "SSE", "cal_date": "20260103", "is_open": "0"},
        provider_id="tushare_pro",
        retrieved_at=NOW,
    )
    with pytest.raises(PersistenceError) as conflict:
        await calendar.save(conflicting)
    assert conflict.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    historical = HistoricalDailyBarService(
        PostgreSQLCanonicalDailyBarRepository(engine),
        PostgreSQLBackfillMetadataRepository(engine),
        calendar,
        coverage,
    )
    series = await historical.get_daily_bars(INSTRUMENT, date(2026, 1, 2), date(2026, 1, 3))
    assert series.coverage.calendar_coverage_complete is True
    assert series.coverage.expected_missing_dates == (date(2026, 1, 3),)


async def test_calendar_postgresql_errors_are_sanitized() -> None:
    unavailable = create_async_engine(
        "postgresql+asyncpg://aic:redacted@127.0.0.1:1/missing",
        pool_pre_ping=True,
    )
    calendar = PostgreSQLTradingCalendarRepository(unavailable)
    coverage = PostgreSQLCalendarCoverageRepository(unavailable)
    day = TushareCalendarNormalizer().normalize(
        {"exchange": "SSE", "cal_date": "20260103", "is_open": "1"},
        provider_id="fixture",
        retrieved_at=NOW,
    )
    attempt = CalendarCoverageAttempt(
        "unavailable",
        "fixture",
        Market.CN_SSE,
        DateInterval(date(2026, 1, 1), date(2026, 1, 3)),
        NOW,
        NOW,
        BackfillAttemptStatus.COMPLETED,
        1,
        1,
        0,
        0,
    )
    try:
        for operation in (
            calendar.save(day),
            calendar.list_days(Market.CN_SSE, date(2026, 1, 1), date(2026, 1, 3)),
            coverage.record(attempt),
            coverage.get_attempts(Market.CN_SSE, date(2026, 1, 1), date(2026, 1, 3)),
        ):
            with pytest.raises(PersistenceError):
                await operation
    finally:
        await unavailable.dispose()
