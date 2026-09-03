import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.ports.backtest import BacktestRecord
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.models import (
    AuditEvent,
    BacktestResult,
    BacktestRun,
    BacktestRunId,
    BacktestStatus,
    CashEntryType,
    CashLedgerEntry,
    Fill,
    FillId,
    Money,
    Order,
    OrderId,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioId,
    PortfolioSnapshot,
    PositionSnapshot,
    Price,
    Quantity,
)
from aic_backend.infrastructure.backtest_persistence import (
    InMemoryBacktestRepository,
    PostgreSQLBacktestRepository,
    audit_events,
    backtest_runs,
    cash_ledger,
    fills,
    nav_snapshots,
    orders,
)

NOW = datetime(2026, 1, 5, 7, tzinfo=UTC)
PORTFOLIO = PortfolioId("portfolio-db")
RUN_ID = BacktestRunId("run-db")
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    return environment


@pytest.fixture
async def engine() -> AsyncEngine:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=clean_environment(),
    )
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        for table in (audit_events, nav_snapshots, cash_ledger, fills, orders, backtest_runs):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


def record(final_nav: Decimal = Decimal("1001")) -> BacktestRecord:
    run = BacktestRun(
        RUN_ID,
        PORTFOLIO,
        NOW,
        NOW,
        Money(Decimal("1000")),
        "point-in-time-availability/v1",
        "fee/v1",
        "slippage/v1",
        "execution/v1",
        NOW,
    )
    order = Order(
        OrderId("order-db"),
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("1")),
        OrderType.MARKET,
        None,
        NOW,
        OrderStatus.FILLED,
    )
    fill = Fill(
        FillId("fill-db"),
        order.order_id,
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("1")),
        Price(Decimal("10")),
        NOW,
        Money(Decimal("1")),
        Money(Decimal("0")),
        Money(Decimal("0.1")),
        "policy/v1",
    )
    entry = CashLedgerEntry(
        "cash-db",
        PORTFOLIO,
        NOW,
        CashEntryType.BUY_SETTLEMENT,
        Money(Decimal("-10")),
        Money(Decimal("990")),
        fill.fill_id.value,
    )
    position = PositionSnapshot(
        INSTRUMENT,
        Decimal("1"),
        Decimal("11"),
        Decimal("11"),
        Decimal("11"),
        Decimal("0"),
        Decimal("0"),
    )
    snapshot = PortfolioSnapshot(
        PORTFOLIO,
        NOW,
        Money(Decimal("990")),
        (position,),
        Money(Decimal("11")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(final_nav),
    )
    event = AuditEvent("event-db", NOW, "FILL", fill.fill_id.value, PORTFOLIO, {"ok": "true"})
    result = BacktestResult(
        RUN_ID,
        Money(Decimal("1000")),
        Money(final_nav),
        Money(Decimal("2.1")),
        Money(Decimal("1")),
        Money(Decimal("0")),
        Money(Decimal("0.1")),
        Money(final_nav - Decimal("1000")),
        (final_nav - Decimal("1000")) / Decimal("1000"),
        Money(Decimal("0")),
        Money(Decimal("0")),
        1,
        Decimal("0"),
        (final_nav - Decimal("1000")) / Decimal("1000"),
        BacktestStatus.COMPLETED,
    )
    return BacktestRecord(run, (order,), (fill,), (entry,), (snapshot,), (event,), result)


@pytest.mark.asyncio
async def test_postgresql_backtest_is_normalized_idempotent_and_readable(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLBacktestRepository(engine)
    value = record()
    await repository.save(value)
    await repository.save(value)
    assert await repository.get_result(RUN_ID.value) == value.result
    async with engine.connect() as connection:
        counts = [
            (await connection.execute(select(func.count()).select_from(table))).scalar_one()
            for table in (backtest_runs, orders, fills, cash_ledger, nav_snapshots, audit_events)
        ]
    assert counts == [1, 1, 1, 1, 1, 1]
    assert await repository.get_result("missing") is None
    with pytest.raises(PersistenceError) as error:
        await repository.save(record(Decimal("999")))
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    async with engine.begin() as connection:
        await connection.execute(
            update(backtest_runs)
            .where(backtest_runs.c.run_id == RUN_ID.value)
            .values(result={"invalid": True})
        )
    with pytest.raises(PersistenceError) as invalid:
        await repository.get_result(RUN_ID.value)
    assert invalid.value.code is PersistenceErrorCode.SERIALIZATION_ERROR


@pytest.mark.asyncio
async def test_in_memory_backtest_repository_detects_identity_conflict() -> None:
    repository = InMemoryBacktestRepository()
    assert await repository.get_result("missing") is None
    await repository.save(record())
    with pytest.raises(PersistenceError) as error:
        await repository.save(record(Decimal("999")))
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


def test_backtest_migration_previous_head_downgrade_and_upgrade() -> None:
    environment = clean_environment()
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260817_0007"],
        check=True,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260820_0008"],
        check=True,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260817_0007"],
        check=True,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )
