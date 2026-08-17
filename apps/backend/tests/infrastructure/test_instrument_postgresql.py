import os
import subprocess
import sys
from datetime import UTC, date, datetime
from typing import cast

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.instruments import InstrumentCoverageAttempt
from aic_backend.application.ports.persistence import PersistenceError, SaveStatus
from aic_backend.application.use_cases.instruments import (
    BackfillInstrumentTradingStatus,
    SyncInstrumentMaster,
)
from aic_backend.data_foundation.tushare_instruments import (
    TushareInstrumentMasterNormalizer,
    TushareTradingStatusNormalizer,
)
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.infrastructure.instrument_persistence import (
    PostgreSQLInstrumentCoverageRepository,
    PostgreSQLInstrumentMasterRepository,
    PostgreSQLInstrumentTradingStatusRepository,
    instrument_masters,
    instrument_sync_attempts,
    instrument_trading_statuses,
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
    TUSHARE_INSTRUMENT_MASTER,
    TUSHARE_TRADING_STATUS,
    TushareDailyProvider,
)

NOW = datetime(2026, 8, 17, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


class Clock:
    def now(self) -> datetime:
        return NOW


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


class InstrumentFixtureClient:
    async def post(self, url: str, *, json, timeout: float) -> httpx.Response:
        if json["api_name"] == "stock_basic":
            fields = [
                "ts_code",
                "symbol",
                "name",
                "exchange",
                "list_status",
                "list_date",
                "delist_date",
            ]
            items = [["600000.SH", "600000", "浦发银行", "SSE", "L", "19991110", None]]
        else:
            fields = ["ts_code", "trade_date", "suspend_timing", "suspend_type"]
            items = [["600000.SH", "20260817", "全天", "S"]]
        return httpx.Response(
            200,
            json={"code": 0, "data": {"fields": fields, "items": items}},
            request=httpx.Request("POST", url),
        )


@pytest.fixture
async def instrument_engine() -> AsyncEngine:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        await connection.execute(delete(instrument_sync_attempts))
        await connection.execute(delete(instrument_trading_statuses))
        await connection.execute(delete(instrument_masters))
    yield value
    await value.dispose()


def master(name="浦发银行"):
    return TushareInstrumentMasterNormalizer().normalize(
        {
            "ts_code": "600000.SH",
            "symbol": "600000",
            "name": name,
            "exchange": "SSE",
            "list_status": "L",
            "list_date": "19991110",
            "delist_date": None,
        },
        provider_id="fixture",
        retrieved_at=NOW,
    )


def status(kind="S"):
    return TushareTradingStatusNormalizer().normalize(
        {
            "ts_code": "600000.SH",
            "trade_date": "20260817",
            "suspend_type": kind,
            "suspend_timing": "全天",
        },
        provider_id="fixture",
        retrieved_at=NOW,
    )


async def test_postgresql_instrument_round_trip_idempotency_conflict_and_order(
    instrument_engine: AsyncEngine,
) -> None:
    masters = PostgreSQLInstrumentMasterRepository(instrument_engine)
    statuses = PostgreSQLInstrumentTradingStatusRepository(instrument_engine)
    assert (await masters.save(master())).status is SaveStatus.INSERTED
    assert (await masters.save(master())).status is SaveStatus.ALREADY_EXISTS
    assert (await masters.get_instrument(INSTRUMENT)).display_name == "浦发银行"
    assert (await masters.find_instrument(Market.CN_SSE, "600000")).instrument == INSTRUMENT
    assert (await masters.list_instruments())[0].instrument == INSTRUMENT
    assert (await masters.list_instruments(Market.CN_SSE))[0].instrument == INSTRUMENT
    assert await masters.find_instrument(Market.CN_SZSE, "000001") is None
    with pytest.raises(PersistenceError, match="identity conflict"):
        await masters.save(master("新名称"))
    assert (await statuses.save(status())).status is SaveStatus.INSERTED
    assert (await statuses.save(status())).status is SaveStatus.ALREADY_EXISTS
    assert (
        await statuses.get_trading_status(INSTRUMENT, date(2026, 8, 17))
    ).state.value == "SUSPENDED"
    assert (
        len(await statuses.list_trading_status(INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31)))
        == 1
    )
    assert await statuses.get_trading_status(INSTRUMENT, date(2026, 8, 18)) is None
    with pytest.raises(ValueError, match="precede"):
        await statuses.list_trading_status(INSTRUMENT, date(2026, 8, 18), date(2026, 8, 17))
    with pytest.raises(PersistenceError, match="identity conflict"):
        await statuses.save(status("R"))


async def test_postgresql_instrument_coverage_round_trip(instrument_engine: AsyncEngine) -> None:
    repository = PostgreSQLInstrumentCoverageRepository(instrument_engine)
    attempt = InstrumentCoverageAttempt(
        "attempt",
        "fixture",
        TUSHARE_TRADING_STATUS.name,
        Market.CN_SSE,
        INSTRUMENT,
        DateInterval(date(2026, 8, 1), date(2026, 8, 17)),
        NOW,
        NOW,
        BackfillAttemptStatus.COMPLETED,
        1,
        1,
        0,
        0,
    )
    await repository.record(attempt)
    assert await repository.get_attempts(
        TUSHARE_TRADING_STATUS.name, Market.CN_SSE, INSTRUMENT, date(2026, 8, 1), date(2026, 8, 17)
    ) == (attempt,)


async def test_runtime_tushare_normalizers_postgresql_instrument_e2e(
    instrument_engine: AsyncEngine,
) -> None:
    clock, ids = Clock(), Ids()
    registry = ProviderRegistry(clock)
    lifecycle = ProviderLifecycleManager(registry, InMemoryEventBus(), clock, ids)
    definition = ProviderDefinition(
        "tushare_pro",
        "providers.tushare_daily",
        True,
        100,
        frozenset({TUSHARE_INSTRUMENT_MASTER, TUSHARE_TRADING_STATUS}),
        {},
    )
    await lifecycle.register(
        TushareDailyProvider(definition, "fixture-token", InstrumentFixtureClient())
    )
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
    masters = PostgreSQLInstrumentMasterRepository(instrument_engine)
    statuses = PostgreSQLInstrumentTradingStatusRepository(instrument_engine)
    coverage = PostgreSQLInstrumentCoverageRepository(instrument_engine)
    synced = await SyncInstrumentMaster(
        runtime,
        TUSHARE_INSTRUMENT_MASTER,
        masters,
        coverage,
        TushareInstrumentMasterNormalizer(),
        clock,
        ids,
    ).execute(Market.CN_SSE)
    backfilled = await BackfillInstrumentTradingStatus(
        runtime,
        TUSHARE_TRADING_STATUS,
        statuses,
        coverage,
        TushareTradingStatusNormalizer(),
        clock,
        ids,
    ).execute(INSTRUMENT, date(2026, 8, 17), date(2026, 8, 17))
    assert (synced.persisted, backfilled.persisted) == (1, 1)
    assert (await masters.get_instrument(INSTRUMENT)).instrument == INSTRUMENT
    assert (
        await statuses.get_trading_status(INSTRUMENT, date(2026, 8, 17))
    ).state.value == "SUSPENDED"


def test_instrument_migration_downgrade_and_upgrade() -> None:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260817_0004"],
        check=True,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )


class BrokenContext:
    async def __aenter__(self):
        raise OSError("database unavailable")

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class BrokenEngine:
    def begin(self):
        return BrokenContext()

    def connect(self):
        return BrokenContext()


async def test_postgresql_instrument_errors_are_translated() -> None:
    engine = cast(AsyncEngine, BrokenEngine())
    masters = PostgreSQLInstrumentMasterRepository(engine)
    statuses = PostgreSQLInstrumentTradingStatusRepository(engine)
    coverage = PostgreSQLInstrumentCoverageRepository(engine)
    attempt = InstrumentCoverageAttempt(
        "attempt",
        "fixture",
        TUSHARE_TRADING_STATUS.name,
        Market.CN_SSE,
        INSTRUMENT,
        DateInterval(date(2026, 8, 17), date(2026, 8, 17)),
        NOW,
        NOW,
        BackfillAttemptStatus.COMPLETED,
        0,
        0,
        0,
        0,
    )
    operations = (
        masters.save(master()),
        masters.find_instrument(Market.CN_SSE, "600000"),
        masters.list_instruments(),
        statuses.save(status()),
        statuses.list_trading_status(INSTRUMENT, date(2026, 8, 17), date(2026, 8, 17)),
        coverage.record(attempt),
        coverage.get_attempts(
            TUSHARE_TRADING_STATUS.name,
            Market.CN_SSE,
            INSTRUMENT,
            date(2026, 8, 17),
            date(2026, 8, 17),
        ),
    )
    for operation in operations:
        with pytest.raises(PersistenceError):
            await operation
