import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.ports import PersistedDailyBar
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.application.use_cases.adjusted_daily_bars import AdjustmentService
from aic_backend.application.use_cases.corporate_actions import (
    BackfillAdjustmentFactors,
    BackfillCorporateActions,
)
from aic_backend.application.use_cases.historical_daily_bars import HistoricalDailyBarService
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.data_foundation.tushare_corporate_actions import (
    TushareAdjustmentFactorNormalizer,
    TushareCorporateActionNormalizer,
)
from aic_backend.domain.market_data import (
    AdjustmentMode,
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)
from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.infrastructure.canonical_persistence import InMemoryCanonicalDailyBarRepository
from aic_backend.infrastructure.corporate_action_persistence import (
    PostgreSQLAdjustmentFactorRepository,
    PostgreSQLCorporateActionRepository,
    adjustment_factors,
    corporate_actions,
)
from aic_backend.infrastructure.historical_persistence import InMemoryBackfillMetadataRepository
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
    TUSHARE_ADJUSTMENT_FACTOR,
    TUSHARE_CORPORATE_ACTION,
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


class FixtureClient:
    async def post(self, url: str, *, json, timeout: float) -> httpx.Response:
        if json["api_name"] == "adj_factor":
            fields = ["ts_code", "trade_date", "adj_factor"]
            items = [["600000.SH", "20260814", "2"], ["600000.SH", "20260815", "4"]]
        else:
            fields = json["fields"].split(",")
            row = {key: None for key in fields}
            row.update(
                ts_code="600000.SH",
                ann_date="20260810",
                record_date="20260814",
                ex_date="20260815",
                pay_date="20260817",
                cash_div_tax="0.25",
                stk_bo_rate="0.10",
                stk_co_rate="0.05",
            )
            items = [[row[key] for key in fields]]
        return httpx.Response(
            200,
            json={"code": 0, "data": {"fields": fields, "items": items}},
            request=httpx.Request("POST", url),
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
        await connection.execute(delete(corporate_actions))
        await connection.execute(delete(adjustment_factors))
    yield value
    await value.dispose()


def factor(day="20260815", value="4"):
    return TushareAdjustmentFactorNormalizer().normalize(
        {"ts_code": "600000.SH", "trade_date": day, "adj_factor": value},
        provider_id="fixture",
        retrieved_at=NOW,
    )


def action():
    return TushareCorporateActionNormalizer().normalize_many(
        {
            "ts_code": "600000.SH",
            "ann_date": "20260810",
            "record_date": "20260814",
            "ex_date": "20260815",
            "pay_date": "20260817",
            "cash_div_tax": "0.25",
        },
        provider_id="fixture",
        retrieved_at=NOW,
    )[0]


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


def bar(day: int, price: str) -> PersistedDailyBar:
    provenance = DataProvenance(
        "fixture", "daily", "fixture://daily", None, False, 0, "1" * 64, "v1"
    )
    record = DailyBar(
        f"record-{day}",
        "1.0",
        INSTRUMENT,
        date(2026, 8, day),
        datetime(2026, 8, day, 7, tzinfo=UTC),
        NOW,
        NOW,
        provenance,
        Decimal(price),
        Decimal(price),
        Decimal(price),
        Decimal(price),
        100,
        Decimal("1000"),
    )
    return PersistedDailyBar("observation", record, DataQualityAssessment(100, 100, 100, 100, 100))


async def test_postgresql_round_trip_idempotency_conflict_and_order(engine: AsyncEngine) -> None:
    factors = PostgreSQLAdjustmentFactorRepository(engine)
    actions = PostgreSQLCorporateActionRepository(engine)
    first, second = factor("20260814", "2"), factor()
    assert (await factors.save(second)).status.value == "INSERTED"
    assert (await factors.save(second)).status.value == "ALREADY_EXISTS"
    await factors.save(first)
    assert await factors.list_adjustment_factors(
        INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31)
    ) == (first, second)
    assert await factors.get_adjustment_factor(INSTRUMENT, date(2026, 8, 13)) is None
    with pytest.raises(ValueError, match="end"):
        await factors.list_adjustment_factors(
            INSTRUMENT, date(2026, 8, 31), date(2026, 8, 1)
        )
    with pytest.raises(Exception, match="identity conflict"):
        await factors.save(replace(second, factor=Decimal("5")))
    value = action()
    assert (await actions.save(value)).status.value == "INSERTED"
    assert (await actions.save(value)).status.value == "ALREADY_EXISTS"
    assert await actions.get_corporate_action(value.action_id) == value
    assert await actions.get_corporate_action("missing") is None
    assert await actions.list_corporate_actions(
        INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31)
    ) == (value,)
    with pytest.raises(ValueError, match="end"):
        await actions.list_corporate_actions(
            INSTRUMENT, date(2026, 8, 31), date(2026, 8, 1)
        )
    with pytest.raises(Exception, match="identity conflict"):
        await actions.save(replace(value, cash_amount=Decimal("0.5")))


async def test_runtime_to_postgresql_to_adjusted_historical_e2e(engine: AsyncEngine) -> None:
    clock, ids = Clock(), Ids()
    registry = ProviderRegistry(clock)
    lifecycle = ProviderLifecycleManager(registry, InMemoryEventBus(), clock, ids)
    definition = ProviderDefinition(
        "tushare",
        "providers.tushare_daily",
        True,
        100,
        frozenset({TUSHARE_ADJUSTMENT_FACTOR, TUSHARE_CORPORATE_ACTION}),
        {},
    )
    await lifecycle.register(TushareDailyProvider(definition, "fixture-token", FixtureClient()))
    await lifecycle.initialize("tushare")
    health = ProviderHealthManager(registry, lifecycle, clock, HealthCheckPolicy(timeout_ms=100))
    await health.check_once("tushare")
    runtime = ProviderRuntime(
        registry,
        ProviderFailoverManager(
            ProviderSelector(QualityScorer()),
            ProviderInvocationManager(registry, clock, {"tushare": 1}),
            FailoverPolicy(),
        ),
        clock,
    )
    factors = PostgreSQLAdjustmentFactorRepository(engine)
    actions = PostgreSQLCorporateActionRepository(engine)
    metadata = InMemoryBackfillMetadataRepository()
    factor_result = await BackfillAdjustmentFactors(
        runtime,
        TUSHARE_ADJUSTMENT_FACTOR,
        factors,
        metadata,
        TushareAdjustmentFactorNormalizer(),
        clock,
        ids,
    ).execute(INSTRUMENT, date(2026, 8, 14), date(2026, 8, 15))
    action_result = await BackfillCorporateActions(
        runtime,
        TUSHARE_CORPORATE_ACTION,
        actions,
        metadata,
        TushareCorporateActionNormalizer(),
        clock,
        ids,
    ).execute(INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31))
    assert (factor_result.persisted, action_result.persisted) == (2, 3)
    daily = InMemoryCanonicalDailyBarRepository()
    await daily.save(bar(14, "10"))
    await daily.save(bar(15, "20"))
    historical = HistoricalDailyBarService(daily, metadata, adjustment=AdjustmentService(factors))
    result = await historical.get_daily_bars(
        INSTRUMENT, date(2026, 8, 14), date(2026, 8, 15), AdjustmentMode.FORWARD_ADJUSTED
    )
    assert tuple(value.close for value in result.adjusted_bars) == (Decimal("5.0"), Decimal("20"))
    assert tuple(value.record.close for value in result.bars) == (Decimal("10"), Decimal("20"))


async def test_corporate_action_postgresql_errors_are_translated() -> None:
    engine = cast(AsyncEngine, BrokenEngine())
    factors = PostgreSQLAdjustmentFactorRepository(engine)
    actions = PostgreSQLCorporateActionRepository(engine)
    operations = (
        factors.save(factor()),
        factors.list_adjustment_factors(
            INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31)
        ),
        actions.save(action()),
        actions.get_corporate_action("missing"),
        actions.list_corporate_actions(
            INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31)
        ),
    )
    for operation in operations:
        with pytest.raises(PersistenceError):
            await operation


def test_corporate_action_migration_downgrade_and_upgrade() -> None:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260817_0005"], check=True, env=environment
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=environment
    )
