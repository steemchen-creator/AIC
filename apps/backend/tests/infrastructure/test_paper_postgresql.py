import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.execution import ExecutionState
from aic_backend.application.ports.paper import PaperTradingRecord
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.paper import (
    CapitalMode,
    ExecutionTiming,
    MetricSampleStatus,
    OperationalStatus,
    PaperAccount,
    PaperAccountStatus,
    PaperMode,
    PaperOrderIntent,
    PaperPerformanceSnapshot,
    PaperPortfolioState,
    PaperSession,
    PaperSessionStatus,
    PaperStateEvent,
)
from aic_backend.domain.portfolio.models import Money, OrderSide, PortfolioId, Quantity
from aic_backend.infrastructure.paper_persistence import (
    InMemoryPaperTradingRepository,
    PostgreSQLPaperTradingRepository,
    _json_fallback,
    paper_account_state_events,
    paper_accounts,
    paper_order_intents,
    paper_performance_snapshots,
    paper_sessions,
    paper_trade_episodes,
)

NOW = datetime(2026, 9, 4, 8, tzinfo=UTC)
TRADING_DATE = date(2026, 9, 4)
ACCOUNT_ID = "paper-postgresql"
PORTFOLIO_ID = PortfolioId("portfolio-postgresql")
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600001", InstrumentType.EQUITY)


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
        for table in (
            paper_trade_episodes,
            paper_performance_snapshots,
            paper_order_intents,
            paper_account_state_events,
            paper_sessions,
            paper_accounts,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


def record() -> PaperTradingRecord:
    account = PaperAccount(
        ACCOUNT_ID,
        PORTFOLIO_ID,
        "AIC Champion Paper Portfolio",
        Money(Decimal("500000")),
        PaperMode.FORWARD_PAPER,
        CapitalMode.CONTINUOUS_COMPOUNDING,
        PaperAccountStatus.RUNNING,
        NOW,
        NOW,
        TRADING_DATE,
    )
    execution = ExecutionState.initialize(PORTFOLIO_ID, account.initial_capital, NOW)
    state = PaperPortfolioState(
        Money(execution.account.cash),
        (),
        tuple(execution.account.cash_ledger),
        (),
        execution.last_snapshot,
        TRADING_DATE,
        TRADING_DATE,
    )
    session = PaperSession(
        "paper-session-postgresql",
        ACCOUNT_ID,
        TRADING_DATE,
        PaperSessionStatus.FINALIZED,
        NOW,
        NOW,
        NOW,
        "daily-bar-forward-paper/v1",
    )
    intent = PaperOrderIntent(
        "paper-intent-postgresql",
        ACCOUNT_ID,
        datetime(2026, 9, 3, 8, tzinfo=UTC),
        TRADING_DATE,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("100")),
        "manual:fixture",
        ExecutionTiming.NEXT_OPEN,
    )
    performance = PaperPerformanceSnapshot(
        "paper-performance-postgresql",
        ACCOUNT_ID,
        session.session_id,
        TRADING_DATE,
        NOW,
        Money(Decimal("500000")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("500000")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Decimal("1"),
        Decimal("0"),
        0,
        Decimal("3000"),
        Decimal("0"),
        Decimal("0"),
        Money(Decimal("500000")),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        None,
        None,
        None,
        None,
        None,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        0,
        MetricSampleStatus.INSUFFICIENT_SAMPLE,
        "paper-performance/v1",
        (),
    )
    event = PaperStateEvent(
        "paper-event-postgresql",
        ACCOUNT_ID,
        NOW,
        "SESSION_FINALIZED",
        session.session_id,
        OperationalStatus.IDLE,
        session.session_id,
        PaperSessionStatus.MARKING.value,
        PaperSessionStatus.FINALIZED.value,
        {"nav": "500000"},
    )
    return PaperTradingRecord(
        account,
        state,
        (session,),
        (intent,),
        (),
        (performance,),
        (),
        (event,),
    )


@pytest.mark.asyncio
async def test_in_memory_paper_evidence_is_immutable_and_append_only() -> None:
    repository = InMemoryPaperTradingRepository()
    value = record()
    await repository.save(value)
    with pytest.raises(PersistenceError) as error:
        await repository.save(replace(value, sessions=()))
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    with pytest.raises(PersistenceError) as error:
        await repository.save(replace(value, intents=()))
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    with pytest.raises(TypeError, match="unsupported recovery projection"):
        _json_fallback(object())


@pytest.mark.asyncio
async def test_postgresql_paper_record_round_trip_and_idempotency(engine: AsyncEngine) -> None:
    repository = PostgreSQLPaperTradingRepository(engine)
    value = record()
    await repository.save(value)
    await repository.save(value)
    assert await repository.get(ACCOUNT_ID) == value
    assert await repository.get("missing") is None
    async with engine.connect() as connection:
        counts = [
            (await connection.execute(select(func.count()).select_from(table))).scalar_one()
            for table in (
                paper_accounts,
                paper_sessions,
                paper_order_intents,
                paper_performance_snapshots,
                paper_account_state_events,
                paper_trade_episodes,
            )
        ]
    assert counts == [1, 1, 1, 1, 1, 0]


@pytest.mark.asyncio
async def test_postgresql_rejects_identity_conflict_and_corrupt_projection(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLPaperTradingRepository(engine)
    value = record()
    await repository.save(value)
    with pytest.raises(PersistenceError) as error:
        await repository.save(
            replace(value, account=replace(value.account, display_name="Different"))
        )
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    async with engine.begin() as connection:
        await connection.execute(
            update(paper_accounts)
            .where(paper_accounts.c.account_id == ACCOUNT_ID)
            .values(recovery_projection={"invalid": True})
        )
    with pytest.raises(PersistenceError) as error:
        await repository.get(ACCOUNT_ID)
    assert error.value.code is PersistenceErrorCode.SERIALIZATION_ERROR


@pytest.mark.asyncio
async def test_postgresql_rejects_normalized_evidence_conflicts(engine: AsyncEngine) -> None:
    repository = PostgreSQLPaperTradingRepository(engine)
    value = record()
    await repository.save(value)
    async with engine.begin() as connection:
        await connection.execute(
            update(paper_order_intents)
            .where(paper_order_intents.c.intent_id == value.intents[0].intent_id)
            .values(source_reference="tampered")
        )
    with pytest.raises(PersistenceError) as error:
        await repository.save(value)
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


@pytest.mark.asyncio
async def test_postgresql_updates_unfinalized_session_and_rejects_finalized_rewrite(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLPaperTradingRepository(engine)
    finalized = record()
    marking = replace(
        finalized,
        account=replace(finalized.account, last_finalized_date=None),
        sessions=(
            replace(
                finalized.sessions[0],
                status=PaperSessionStatus.MARKING,
                finalized_at=None,
            ),
        ),
    )
    await repository.save(marking)
    blocked = replace(
        marking,
        sessions=(replace(marking.sessions[0], status=PaperSessionStatus.BLOCKED),),
    )
    await repository.save(blocked)
    assert await repository.get(ACCOUNT_ID) == blocked

    async with engine.begin() as connection:
        await connection.execute(
            update(paper_sessions)
            .where(paper_sessions.c.session_id == blocked.sessions[0].session_id)
            .values(status=PaperSessionStatus.FINALIZED.value)
        )
    with pytest.raises(PersistenceError) as error:
        await repository.save(blocked)
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


@pytest.mark.asyncio
async def test_postgresql_maps_missing_session_for_intent_to_transaction_error(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLPaperTradingRepository(engine)
    with pytest.raises(PersistenceError) as error:
        await repository.save(replace(record(), sessions=()))
    assert error.value.code is PersistenceErrorCode.TRANSACTION_ERROR


@pytest.mark.asyncio
async def test_postgresql_adapter_maps_transaction_failure() -> None:
    class BrokenEngine:
        def begin(self):
            raise SQLAlchemyError("unavailable")

    repository = PostgreSQLPaperTradingRepository(BrokenEngine())  # type: ignore[arg-type]
    with pytest.raises(PersistenceError) as error:
        await repository.save(record())
    assert error.value.code is PersistenceErrorCode.TRANSACTION_ERROR


def test_paper_migration_fresh_previous_downgrade_and_upgrade() -> None:
    environment = clean_environment()
    for command in (
        ("downgrade", "base"),
        ("upgrade", "head"),
        ("downgrade", "20260903_0009"),
        ("upgrade", "20260904_0010"),
        ("downgrade", "20260903_0009"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            check=True,
            env=environment,
        )
