import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from apps.backend.tests.application.test_a_share_execution import PitFixture, service
from apps.backend.tests.infrastructure.test_trade_plan_postgresql import (
    INSTRUMENT,
    NEXT_OPEN,
    NOW,
    Calendar,
    build,
    clean_environment,
)
from apps.backend.tests.infrastructure.test_trade_plan_postgresql import engine as engine
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from aic_backend.application.execution import ExecutionState
from aic_backend.application.idempotent_execution import (
    ExecutionReconciliationError,
    IdempotentExecutionService,
)
from aic_backend.application.ports.execution_journal import (
    ExecutionClaim,
    ExecutionReceipt,
    ExecutionStateSnapshot,
)
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.application.trade_plan import TradePlanService
from aic_backend.domain.execution import PriceLimitBand, SettlementPosition
from aic_backend.domain.market_data import InstrumentTradingState
from aic_backend.domain.portfolio.models import (
    Money,
    OrderId,
    PortfolioId,
    Position,
    PositionKey,
    Quantity,
)
from aic_backend.domain.trade_plan import DirectiveType
from aic_backend.infrastructure.execution_journal import (
    PostgreSQLExecutionJournal,
    execution_claims,
)
from aic_backend.infrastructure.execution_persistence import (
    PostgreSQLExecutionEvidenceRepository,
    risk_decisions,
)
from aic_backend.infrastructure.trade_plan_persistence import (
    PostgreSQLTradePlanRepository,
    trade_plan_execution_evidence,
)


def authority(database=None):
    pit = PitFixture()
    pit.calendar[NEXT_OPEN.date()] = True
    pit.lifecycle[INSTRUMENT.canonical_key] = "listed"
    pit.statuses[(INSTRUMENT.canonical_key, NEXT_OPEN.date())] = (
        InstrumentTradingState.TRADING,
        NEXT_OPEN,
    )
    pit.prices[(INSTRUMENT.canonical_key, NEXT_OPEN.date())] = (Decimal("10"), NEXT_OPEN)
    return service(
        pit,
        repository=None if database is None else PostgreSQLExecutionEvidenceRepository(database),
    )


def account() -> ExecutionState:
    state = ExecutionState.initialize(PortfolioId("champion"), Money(Decimal("100000")), NOW)
    state.account.positions[INSTRUMENT.canonical_key] = Position(
        PositionKey(state.account.portfolio_id, INSTRUMENT), Decimal("500"), Decimal("10")
    )
    state.settlement.seed(
        SettlementPosition(INSTRUMENT, Decimal("500"), Decimal("500"), Decimal("0"))
    )
    return state


class MustNotExecute:
    async def execute(self, *args, **kwargs):
        raise AssertionError("reconciliation must never create another execution")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [DirectiveType.SCALE_IN, DirectiveType.REDUCE, DirectiveType.EXIT])
@pytest.mark.parametrize("rejected", [False, True])
async def test_durable_execution_reconciles_after_trade_plan_save_conflict(engine, kind, rejected):
    writer = PostgreSQLTradePlanRepository(engine)
    initial = await build(writer, f"reconcile-{kind.value}-{rejected}")
    journal = PostgreSQLExecutionJournal(engine)
    authoritative = IdempotentExecutionService(authority(engine), journal)
    setup = TradePlanService(writer, Calendar(), authoritative)
    directive = await setup.create_directive(
        initial.plan.plan_id,
        kind,
        None if kind is DirectiveType.EXIT else Quantity(Decimal("100")),
        NOW + timedelta(hours=1),
        source_reference="execution-reconciliation",
    )

    class ConcurrentAppendRepository(PostgreSQLTradePlanRepository):
        async def save(self, record):
            if record.executions:
                receipt = await journal.get(OrderId(record.executions[0].order_id))
                assert isinstance(receipt, ExecutionReceipt)
                # This write commits after the financial operation returned, before its link save.
                await setup.create_directive(
                    initial.plan.plan_id,
                    DirectiveType.HOLD,
                    None,
                    NOW + timedelta(hours=2),
                    source_reference="concurrent-writer",
                )
            await super().save(record)

    state = account()
    before = ExecutionStateSnapshot.capture(state)
    runtime = TradePlanService(ConcurrentAppendRepository(engine), Calendar(), authoritative)
    with pytest.raises(PersistenceError) as conflict:
        await runtime.execute_directive(
            directive.directive_id,
            state,
            NEXT_OPEN,
            price_limit_band=None
            if rejected
            else PriceLimitBand(Decimal("1"), Decimal("100"), "fixture", NEXT_OPEN),
        )
    assert conflict.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    after = ExecutionStateSnapshot.capture(state)
    assert after.orders_today == 1 and len(after.outcomes) == 1
    assert after.filled_orders_today == (0 if rejected else 1)
    result = after.outcomes[0]
    assert (result.fill is None) is rejected
    assert after.settlement_positions[0].total_quantity == (
        Decimal("500")
        if rejected
        else Decimal("600")
        if kind is DirectiveType.SCALE_IN
        else Decimal("400")
        if kind is DirectiveType.REDUCE
        else Decimal("0")
    )
    assert (await writer.get(initial.plan.plan_id)).executions == ()
    stored_receipt = await journal.get(result.order.order_id)
    assert isinstance(stored_receipt, ExecutionReceipt)

    # Drop services/connections: recover both from the durable pre-execution account and from
    # an already-applied account. Neither path can call the authoritative financial operation.
    await engine.dispose()
    restarted_engine = create_async_engine(os.environ["AIC_DATABASE_URL"])
    try:
        restarted_journal = PostgreSQLExecutionJournal(restarted_engine)
        restarted_plans = PostgreSQLTradePlanRepository(restarted_engine)
        restarted = TradePlanService(
            restarted_plans,
            Calendar(),
            IdempotentExecutionService(MustNotExecute(), restarted_journal),
        )
        recovered_state = before.thaw()
        evidence = await restarted.execute_directive(
            directive.directive_id, recovered_state, NEXT_OPEN + timedelta(days=1)
        )
        assert ExecutionStateSnapshot.capture(recovered_state) == after
        assert (
            await restarted.execute_directive(
                directive.directive_id, state, NEXT_OPEN + timedelta(days=2)
            )
            == evidence
        )
        assert ExecutionStateSnapshot.capture(state) == after
        assert evidence.executed_at == NEXT_OPEN
        assert evidence.fill_id == (None if result.fill is None else result.fill.fill_id.value)
        assert evidence.order_id == result.order.order_id.value
        record = await restarted_plans.get(initial.plan.plan_id)
        assert record.executions == (evidence,)
        assert len(record.directives) == 3  # initial HOLD, executable, concurrent HOLD
        assert await restarted_journal.get(result.order.order_id) == stored_receipt
        async with restarted_engine.connect() as connection:
            for table, column in (
                (execution_claims, execution_claims.c.order_id),
                (risk_decisions, risk_decisions.c.order_id),
                (trade_plan_execution_evidence, trade_plan_execution_evidence.c.order_id),
            ):
                assert (
                    await connection.execute(
                        select(func.count()).select_from(table).where(column == evidence.order_id)
                    )
                ).scalar_one() == 1
    finally:
        await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_unresolved_claim_blocks_restart_after_receipt_write_failure(engine):
    class FailedReceiptJournal(PostgreSQLExecutionJournal):
        async def complete(self, value):
            raise RuntimeError("receipt storage unavailable")

    from aic_backend.application.execution import ExecutionOrderIntent
    from aic_backend.domain.portfolio.models import OrderSide

    state = account()
    before = ExecutionStateSnapshot.capture(state)
    intent = ExecutionOrderIntent(INSTRUMENT, OrderSide.BUY, Quantity(Decimal("100")))
    order_id = OrderId("receipt-failure")
    runtime = IdempotentExecutionService(authority(engine), FailedReceiptJournal(engine))
    with pytest.raises(RuntimeError, match="receipt storage unavailable"):
        await runtime.execute(
            state,
            intent,
            order_id,
            NEXT_OPEN,
            PriceLimitBand(Decimal("1"), Decimal("100"), "fixture", NEXT_OPEN),
        )
    assert ExecutionStateSnapshot.capture(state) == before
    await engine.dispose()
    restarted = create_async_engine(os.environ["AIC_DATABASE_URL"])
    try:
        journal = PostgreSQLExecutionJournal(restarted)
        assert isinstance(await journal.get(order_id), ExecutionClaim)
        runtime = IdempotentExecutionService(MustNotExecute(), journal)
        with pytest.raises(ExecutionReconciliationError, match="unresolved durable"):
            await runtime.execute(state, intent, order_id, NEXT_OPEN + timedelta(days=1), None)
        assert ExecutionStateSnapshot.capture(state) == before
    finally:
        await restarted.dispose()


def test_execution_claim_migration_round_trip():
    for arguments in (
        ("downgrade", "20260909_0014"),
        ("upgrade", "head"),
        ("downgrade", "20260909_0014"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments], check=True, env=clean_environment()
        )


@pytest.mark.asyncio
async def test_postgresql_claim_race_receipt_immutability_and_corruption(engine):
    from aic_backend.application.execution import ExecutionOrderIntent
    from aic_backend.domain.portfolio.models import OrderSide

    journal = PostgreSQLExecutionJournal(engine)
    before = ExecutionStateSnapshot.capture(account())
    order_id = OrderId("claim-race")
    intent = ExecutionOrderIntent(INSTRUMENT, OrderSide.BUY, Quantity(Decimal("100")))
    claim = ExecutionClaim("owner-one", order_id, intent, NEXT_OPEN, before)
    competitor = replace(claim, claim_id="owner-two")
    results = await asyncio.gather(journal.claim(claim), journal.claim(competitor))
    assert sorted(results) == [False, True]
    winner = await journal.get(order_id)
    assert winner == (claim if results[0] else competitor)
    working = before.thaw()
    outcome = await authority(engine).execute(working, intent, order_id, NEXT_OPEN, None)
    receipt = ExecutionReceipt(winner, outcome, ExecutionStateSnapshot.capture(working))
    await journal.complete(receipt)
    await journal.complete(receipt)
    assert await journal.get(order_id) == receipt
    for changed in (
        replace(receipt, claim=replace(winner, claim_id="forged-owner")),
        replace(receipt, after=replace(receipt.after, cash=receipt.after.cash + Decimal("1"))),
    ):
        with pytest.raises(PersistenceError) as error:
            await journal.complete(changed)
        assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    assert await journal.get(OrderId("missing-order")) is None
    async with engine.begin() as connection:
        await connection.execute(
            update(execution_claims)
            .where(execution_claims.c.order_id == order_id.value)
            .values(receipt={"corrupt": True})
        )
    with pytest.raises(PersistenceError) as error:
        await journal.get(order_id)
    assert error.value.code is PersistenceErrorCode.SERIALIZATION_ERROR
