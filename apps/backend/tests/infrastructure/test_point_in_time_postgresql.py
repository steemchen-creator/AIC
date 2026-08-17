import os
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.point_in_time import (
    AvailabilityMode,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.application.ports import PersistedDailyBar
from aic_backend.application.use_cases.point_in_time_market_data import PointInTimeMarketDataService
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.domain.market_data import (
    AdjustmentFactor,
    CorporateAction,
    CorporateActionType,
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentTradingState,
    InstrumentTradingStatus,
    InstrumentType,
    ListingStatus,
    Market,
    TradingSessionDay,
    standard_a_share_session,
)
from aic_backend.infrastructure.calendar_persistence import (
    PostgreSQLTradingCalendarRepository,
    trading_calendar_days,
)
from aic_backend.infrastructure.canonical_persistence import (
    PostgreSQLCanonicalDailyBarRepository,
    canonical_daily_bars,
)
from aic_backend.infrastructure.corporate_action_persistence import (
    PostgreSQLAdjustmentFactorRepository,
    PostgreSQLCorporateActionRepository,
    adjustment_factors,
    corporate_actions,
)
from aic_backend.infrastructure.instrument_persistence import (
    PostgreSQLInstrumentMasterRepository,
    PostgreSQLInstrumentTradingStatusRepository,
    instrument_masters,
    instrument_trading_statuses,
)

INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)
KNOWN_AT = datetime(2020, 1, 3, 8, tzinfo=UTC)
INGESTED_AT = datetime(2026, 8, 17, tzinfo=UTC)


def provenance() -> DataProvenance:
    return DataProvenance(
        "fixture", "source", "fixture://pit", KNOWN_AT, False, 0, "2" * 64, "pit/v1"
    )


@pytest.fixture
async def engine() -> AsyncEngine:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=environment
    )
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        for table in (
            instrument_trading_statuses,
            instrument_masters,
            corporate_actions,
            adjustment_factors,
            trading_calendar_days,
            canonical_daily_bars,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


async def test_postgresql_point_in_time_e2e_preserves_availability_evidence(
    engine: AsyncEngine,
) -> None:
    daily = PostgreSQLCanonicalDailyBarRepository(engine)
    factors = PostgreSQLAdjustmentFactorRepository(engine)
    actions = PostgreSQLCorporateActionRepository(engine)
    masters = PostgreSQLInstrumentMasterRepository(engine)
    statuses = PostgreSQLInstrumentTradingStatusRepository(engine)
    calendar = PostgreSQLTradingCalendarRepository(engine)
    bar = DailyBar(
        "pit-bar",
        "1.0",
        INSTRUMENT,
        date(2020, 1, 3),
        datetime(2020, 1, 3, 7, tzinfo=UTC),
        INGESTED_AT,
        INGESTED_AT,
        provenance(),
        Decimal("10"),
        Decimal("11"),
        Decimal("9"),
        Decimal("10"),
        100,
        Decimal("1000"),
    )
    await daily.save(
        PersistedDailyBar("pit-observation", bar, DataQualityAssessment(100, 100, 100, 100, 100))
    )
    await factors.save(
        AdjustmentFactor(
            "pit-factor",
            INSTRUMENT,
            date(2020, 1, 3),
            Decimal("2"),
            "v1",
            INGESTED_AT,
            provenance(),
        )
    )
    await actions.save(
        CorporateAction(
            "pit-action",
            INSTRUMENT,
            CorporateActionType.CASH_DIVIDEND,
            date(2020, 1, 2),
            date(2020, 1, 3),
            date(2020, 1, 6),
            date(2020, 1, 3),
            Decimal("0.1"),
            None,
            None,
            INGESTED_AT,
            provenance(),
        )
    )
    await masters.save(
        InstrumentMaster(
            INSTRUMENT,
            "Current Name",
            date(2010, 1, 1),
            None,
            ListingStatus.LISTED,
            INGESTED_AT,
            provenance(),
        )
    )
    await statuses.save(
        InstrumentTradingStatus(
            INSTRUMENT,
            date(2020, 1, 3),
            InstrumentTradingState.TRADING,
            None,
            INGESTED_AT,
            provenance(),
        )
    )
    await calendar.save(
        TradingSessionDay(
            Market.CN_SSE,
            date(2020, 1, 3),
            True,
            standard_a_share_session(date(2020, 1, 3)),
            INGESTED_AT,
            provenance(),
        )
    )
    service = PointInTimeMarketDataService(
        daily, factors, actions, masters, statuses, calendar, DataAvailabilityPolicy()
    )
    research = PointInTimeContext(
        datetime(2020, 1, 3, 9, tzinfo=UTC), AvailabilityMode.HISTORICAL_RESEARCH
    )
    replay = PointInTimeContext(
        datetime(2020, 1, 3, 9, tzinfo=UTC), AvailabilityMode.OPERATIONAL_REPLAY
    )
    daily_result = await service.get_daily_bars_as_of(
        INSTRUMENT, date(2020, 1, 3), date(2020, 1, 3), research
    )
    action_result = await service.list_corporate_actions_as_of(
        INSTRUMENT, date(2020, 1, 1), date(2020, 1, 31), research
    )
    factor_result = await service.list_adjustment_factors_as_of(
        INSTRUMENT, date(2020, 1, 1), date(2020, 1, 31), research
    )
    status_result = await service.list_trading_status_as_of(
        INSTRUMENT, date(2020, 1, 3), date(2020, 1, 3), research
    )
    universe = await service.list_instruments_as_of(date(2020, 1, 3), research)
    calendar_result = await service.list_calendar_as_of(
        Market.CN_SSE, date(2020, 1, 3), date(2020, 1, 3), research
    )
    operational = await service.get_daily_bars_as_of(
        INSTRUMENT, date(2020, 1, 3), date(2020, 1, 3), replay
    )
    assert all(
        result.available_count == 1
        for result in (
            daily_result,
            action_result,
            factor_result,
            status_result,
            universe,
            calendar_result,
        )
    )
    assert operational.excluded_future_count == 1
    assert daily_result.records[0].record.provenance.provider_timestamp == KNOWN_AT
    assert action_result.records[0].provenance.provider_timestamp == KNOWN_AT
    assert factor_result.records[0].provenance.provider_timestamp == KNOWN_AT
    assert status_result.records[0].provenance.provider_timestamp == KNOWN_AT


def test_point_in_time_migration_downgrade_and_upgrade() -> None:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260817_0006"],
        check=True,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=environment
    )
