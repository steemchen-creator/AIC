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

from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.execution import (
    ExecutionOutcome,
    ExecutionPolicyVersions,
    RiskDecision,
    RiskDecisionType,
    RiskInputSummary,
    RiskReasonCode,
    RiskSnapshot,
    SettlementPosition,
    SettlementRolloverEvent,
    TradingEligibility,
)
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.models import (
    AuditEvent,
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
    Price,
    Quantity,
)
from aic_backend.infrastructure.execution_persistence import (
    InMemoryExecutionEvidenceRepository,
    PostgreSQLExecutionEvidenceRepository,
    execution_audit_events,
    risk_decisions,
    risk_snapshots,
    settlement_positions,
    settlement_rollovers,
)

NOW = datetime(2026, 8, 21, 7, tzinfo=UTC)
PORTFOLIO = PortfolioId("portfolio-execution-db")
ORDER_ID = OrderId("order-execution-db")
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
        for table in (
            execution_audit_events,
            settlement_positions,
            settlement_rollovers,
            risk_snapshots,
            risk_decisions,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


def outcome(nav: str = "500100") -> ExecutionOutcome:
    summary = RiskInputSummary(
        Money(Decimal("500000")),
        Money(Decimal("500000")),
        Money(Decimal("0")),
        Money(Decimal("10000")),
        Money(Decimal("10000")),
        Money(Decimal("489995")),
        0,
        0,
        Money(Decimal("0")),
    )
    decision = RiskDecision(
        "risk-execution-db",
        PORTFOLIO,
        ORDER_ID,
        NOW,
        RiskDecisionType.ALLOW,
        (),
        "risk/v1",
        summary,
    )
    order = Order(
        ORDER_ID,
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("1000")),
        OrderType.MARKET,
        None,
        NOW,
        OrderStatus.FILLED,
    )
    fill = Fill(
        FillId("fill-execution-db"),
        ORDER_ID,
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("1000")),
        Price(Decimal("10")),
        NOW,
        Money(Decimal("5")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        "execution/v1",
    )
    cash = CashLedgerEntry(
        "cash-execution-db",
        PORTFOLIO,
        NOW,
        CashEntryType.BUY_SETTLEMENT,
        Money(Decimal("-10000")),
        Money(Decimal("490000")),
        fill.fill_id.value,
    )
    position = SettlementPosition(INSTRUMENT, Decimal("1000"), Decimal("0"), Decimal("1000"))
    rollover = SettlementRolloverEvent(
        "settlement-execution-db",
        PORTFOLIO,
        date(2026, 8, 21),
        NOW,
        Decimal("0"),
        "settlement/v1",
    )
    snapshot = RiskSnapshot(
        "snapshot-execution-db",
        PORTFOLIO,
        NOW,
        Money(Decimal(nav)),
        Money(Decimal("489995")),
        Money(Decimal("10000")),
        Decimal("0.979794"),
        Decimal("0.019996"),
        1,
        Money(Decimal("10000")),
        1,
        1,
        "risk/v1",
    )
    event = AuditEvent(
        "audit-execution-db",
        NOW,
        "RISK_DECISION",
        decision.risk_decision_id,
        PORTFOLIO,
        {"decision": "ALLOW"},
    )
    return ExecutionOutcome(
        order,
        TradingEligibility(True, True, False, False, True),
        decision,
        fill,
        (cash,),
        position,
        rollover,
        snapshot,
        ExecutionPolicyVersions("execution/v1", "lot/v1", "limit/v1", "settlement/v1", "risk/v1"),
        (event,),
        {"fixture": "true"},
    )


def rejected_outcome() -> ExecutionOutcome:
    accepted = outcome()
    decision = RiskDecision(
        "risk-rejected-db",
        PORTFOLIO,
        OrderId("order-rejected-db"),
        NOW,
        RiskDecisionType.REJECT,
        (RiskReasonCode.INVALID_LOT_SIZE,),
        "risk/v1",
        accepted.risk_decision.input_summary,
    )
    return replace(
        accepted,
        order=replace(
            accepted.order,
            order_id=OrderId("order-rejected-db"),
            status=OrderStatus.REJECTED,
        ),
        risk_decision=decision,
        fill=None,
        cash_entries=(),
        settlement_position=None,
        settlement_event=None,
        risk_snapshot=None,
        audit_events=(),
    )


@pytest.mark.asyncio
async def test_postgresql_execution_evidence_is_insert_or_verify_and_readable(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLExecutionEvidenceRepository(engine)
    value = outcome()
    await repository.save(value)
    await repository.save(value)
    await repository.save(rejected_outcome())
    assert await repository.get_risk_decision("risk-execution-db") == value.risk_decision
    assert await repository.get_risk_decision("missing") is None
    async with engine.connect() as connection:
        counts = [
            (await connection.execute(select(func.count()).select_from(table))).scalar_one()
            for table in (
                risk_decisions,
                risk_snapshots,
                settlement_rollovers,
                settlement_positions,
                execution_audit_events,
            )
        ]
    assert counts == [2, 1, 1, 1, 1]
    with pytest.raises(PersistenceError) as error:
        await repository.save(outcome("500101"))
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


@pytest.mark.asyncio
async def test_postgresql_rejects_corrupt_risk_decision(engine: AsyncEngine) -> None:
    repository = PostgreSQLExecutionEvidenceRepository(engine)
    await repository.save(outcome())
    async with engine.begin() as connection:
        await connection.execute(
            update(risk_decisions)
            .where(risk_decisions.c.risk_decision_id == "risk-execution-db")
            .values(input_summary={"invalid": True})
        )
    with pytest.raises(PersistenceError) as error:
        await repository.get_risk_decision("risk-execution-db")
    assert error.value.code is PersistenceErrorCode.SERIALIZATION_ERROR


@pytest.mark.asyncio
async def test_in_memory_execution_evidence_detects_identity_conflict() -> None:
    repository = InMemoryExecutionEvidenceRepository()
    assert await repository.get_risk_decision("missing") is None
    await repository.save(outcome())
    await repository.save(outcome())
    with pytest.raises(PersistenceError) as error:
        await repository.save(outcome("500101"))
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


@pytest.mark.asyncio
async def test_postgresql_adapter_maps_transaction_failure() -> None:
    class BrokenEngine:
        def begin(self):
            raise SQLAlchemyError("unavailable")

    repository = PostgreSQLExecutionEvidenceRepository(BrokenEngine())  # type: ignore[arg-type]
    with pytest.raises(PersistenceError) as error:
        await repository.save(outcome())
    assert error.value.code is PersistenceErrorCode.TRANSACTION_ERROR


def test_execution_migration_fresh_previous_downgrade_and_upgrade() -> None:
    environment = clean_environment()
    for command in (
        ("downgrade", "base"),
        ("upgrade", "head"),
        ("downgrade", "20260820_0008"),
        ("upgrade", "20260903_0009"),
        ("downgrade", "20260820_0008"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            check=True,
            env=environment,
        )
