import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
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
    command,
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
from aic_backend.domain.trade_plan import (
    DirectiveType,
    PlanObservation,
    TradePlanError,
    TradePlanErrorCode,
    TradePlanStatus,
)
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


class PausingFenceRepository(PostgreSQLTradePlanRepository):
    def __init__(self, database):
        super().__init__(database)
        self.acquired = asyncio.Event()
        self.release = asyncio.Event()

    @asynccontextmanager
    async def pair_fence(self, portfolio_id, instrument_key):
        async with super().pair_fence(portfolio_id, instrument_key):
            self.acquired.set()
            await self.release.wait()
            yield


class SignalingFenceRepository(PostgreSQLTradePlanRepository):
    def __init__(self, database):
        super().__init__(database)
        self.attempted = asyncio.Event()

    @asynccontextmanager
    async def pair_fence(self, portfolio_id, instrument_key):
        self.attempted.set()
        async with super().pair_fence(portfolio_id, instrument_key):
            yield


class PausingExecution:
    def __init__(self, delegate):
        self.delegate = delegate
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def reconcile(self, *args, **kwargs):
        return await self.delegate.reconcile(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        self.entered.set()
        await self.release.wait()
        return await self.delegate.execute(*args, **kwargs)

    async def outcome_attribution(self, *args, **kwargs):
        return await self.delegate.outcome_attribution(*args, **kwargs)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", [TradePlanStatus.CANCELLED, TradePlanStatus.COMPLETED])
@pytest.mark.parametrize("winner", ["execution", "terminal"])
async def test_postgresql_execution_and_terminal_transition_share_pair_fence(
    engine, terminal_status, winner
):
    setup_repository = PostgreSQLTradePlanRepository(engine)
    initial = await build(setup_repository, f"fence-{terminal_status.value}-{winner}")
    journal = PostgreSQLExecutionJournal(engine)
    durable = IdempotentExecutionService(authority(engine), journal)
    setup = TradePlanService(setup_repository, Calendar(), durable)
    directive = await setup.create_directive(
        initial.plan.plan_id,
        DirectiveType.REDUCE,
        Quantity(Decimal("100")),
        NOW + timedelta(hours=1),
        source_reference="blocker-08-race",
    )
    state = account()

    if winner == "execution":
        pausing_execution = PausingExecution(durable)
        executor = TradePlanService(
            PostgreSQLTradePlanRepository(engine), Calendar(), pausing_execution
        )
        terminal_repository = SignalingFenceRepository(engine)
        terminal = TradePlanService(terminal_repository, Calendar(), durable)
        execution_task = asyncio.create_task(
            executor.execute_directive(
                directive.directive_id,
                state,
                NEXT_OPEN,
                price_limit_band=PriceLimitBand(
                    Decimal("1"), Decimal("100"), "fixture", NEXT_OPEN
                ),
            )
        )
        await asyncio.wait_for(pausing_execution.entered.wait(), 2)
        terminal_task = asyncio.create_task(
            terminal.transition_terminal(
                initial.plan.plan_id,
                terminal_status,
                NEXT_OPEN + timedelta(minutes=1),
                "BLOCKER_08_RACE",
            )
        )
        await asyncio.wait_for(terminal_repository.attempted.wait(), 2)
        assert not terminal_task.done()
        pausing_execution.release.set()
        evidence, terminal_plan = await asyncio.gather(execution_task, terminal_task)
        assert evidence.fill_id is not None
        assert terminal_plan.status is terminal_status
        snapshot = ExecutionStateSnapshot.capture(state)
        assert snapshot.settlement_positions[0].total_quantity == Decimal("400")
    else:
        terminal_repository = PausingFenceRepository(engine)
        terminal = TradePlanService(terminal_repository, Calendar(), durable)
        execution_repository = SignalingFenceRepository(engine)
        executor = TradePlanService(execution_repository, Calendar(), durable)
        terminal_task = asyncio.create_task(
            terminal.transition_terminal(
                initial.plan.plan_id,
                terminal_status,
                NEXT_OPEN + timedelta(minutes=1),
                "BLOCKER_08_RACE",
            )
        )
        await asyncio.wait_for(terminal_repository.acquired.wait(), 2)
        execution_task = asyncio.create_task(
            executor.execute_directive(directive.directive_id, state, NEXT_OPEN)
        )
        await asyncio.wait_for(execution_repository.attempted.wait(), 2)
        assert not execution_task.done()
        terminal_repository.release.set()
        terminal_plan = await terminal_task
        with pytest.raises(TradePlanError) as blocked:
            await execution_task
        assert blocked.value.code is TradePlanErrorCode.TERMINAL_EXECUTION_BLOCKED
        assert terminal_plan.status is terminal_status
        snapshot = ExecutionStateSnapshot.capture(state)
        assert snapshot.orders_today == 0
        assert snapshot.settlement_positions[0].total_quantity == Decimal("500")

    stored = await setup_repository.get(initial.plan.plan_id)
    assert stored is not None
    assert stored.plan.status is terminal_status
    assert len(stored.executions) == (1 if winner == "execution" else 0)
    async with engine.connect() as connection:
        claim_count = (
            await connection.execute(select(func.count()).select_from(execution_claims))
        ).scalar_one()
        link_count = (
            await connection.execute(
                select(func.count()).select_from(trade_plan_execution_evidence)
            )
        ).scalar_one()
    assert claim_count == link_count == (1 if winner == "execution" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["terminal", "successor"])
async def test_postgresql_terminal_and_successor_activation_share_pair_fence(engine, winner):
    setup_repository = PostgreSQLTradePlanRepository(engine)
    predecessor = await build(setup_repository, f"activation-predecessor-{winner}")
    successor = command(f"activation-successor-{winner}")
    setup = TradePlanService(setup_repository, Calendar(), MustNotExecute())
    await setup.create_draft(successor)

    holder_repository = PausingFenceRepository(engine)
    waiter_repository = SignalingFenceRepository(engine)
    holder = TradePlanService(holder_repository, Calendar(), MustNotExecute())
    waiter = TradePlanService(waiter_repository, Calendar(), MustNotExecute())
    if winner == "terminal":
        holder_task = asyncio.create_task(
            holder.transition_terminal(
                predecessor.plan.plan_id,
                TradePlanStatus.CANCELLED,
                NOW + timedelta(hours=1),
                "BLOCKER_08_RACE",
            )
        )
        await asyncio.wait_for(holder_repository.acquired.wait(), 2)
        waiter_task = asyncio.create_task(
            waiter.activate(
                successor.plan_id,
                NOW + timedelta(hours=2),
                actor="aic-codex-cto",
                source="blocker-08",
            )
        )
    else:
        holder_task = asyncio.create_task(
            holder.activate(
                successor.plan_id,
                NOW + timedelta(hours=2),
                actor="aic-codex-cto",
                source="blocker-08",
            )
        )
        await asyncio.wait_for(holder_repository.acquired.wait(), 2)
        waiter_task = asyncio.create_task(
            waiter.transition_terminal(
                predecessor.plan.plan_id,
                TradePlanStatus.CANCELLED,
                NOW + timedelta(hours=1),
                "BLOCKER_08_RACE",
            )
        )
    await asyncio.wait_for(waiter_repository.attempted.wait(), 2)
    assert not waiter_task.done()
    holder_repository.release.set()

    if winner == "terminal":
        await asyncio.gather(holder_task, waiter_task)
        assert (await setup_repository.get(successor.plan_id)).plan.status is TradePlanStatus.ACTIVE
    else:
        with pytest.raises(TradePlanError) as duplicate:
            await holder_task
        assert duplicate.value.code is TradePlanErrorCode.DUPLICATE_ACTIVE_PLAN
        await waiter_task
        assert (await setup_repository.get(successor.plan_id)).plan.status is TradePlanStatus.DRAFT
    assert (
        await setup_repository.get(predecessor.plan.plan_id)
    ).plan.status is TradePlanStatus.CANCELLED


@pytest.mark.asyncio
async def test_postgresql_three_way_race_is_safe_and_survives_restart(engine):
    setup_repository = PostgreSQLTradePlanRepository(engine)
    predecessor = await build(setup_repository, "three-way-predecessor")
    durable = IdempotentExecutionService(
        authority(engine), PostgreSQLExecutionJournal(engine)
    )
    setup = TradePlanService(setup_repository, Calendar(), durable)
    pending = await setup.create_directive(
        predecessor.plan.plan_id,
        DirectiveType.ENTRY,
        Quantity(Decimal("100")),
        NOW + timedelta(hours=1),
        source_reference="predecessor-entry",
    )
    successor = command("three-way-successor")
    await setup.create_draft(successor)
    state = ExecutionState.initialize(PortfolioId("champion"), Money(Decimal("100000")), NOW)

    terminal_repository = PausingFenceRepository(engine)
    execution_repository = SignalingFenceRepository(engine)
    activation_repository = SignalingFenceRepository(engine)
    terminal = TradePlanService(terminal_repository, Calendar(), durable)
    executor = TradePlanService(execution_repository, Calendar(), durable)
    activator = TradePlanService(activation_repository, Calendar(), durable)
    terminal_task = asyncio.create_task(
        terminal.transition_terminal(
            predecessor.plan.plan_id,
            TradePlanStatus.CANCELLED,
            NOW + timedelta(hours=2),
            "BLOCKER_08_THREE_WAY",
        )
    )
    await asyncio.wait_for(terminal_repository.acquired.wait(), 2)
    execution_task = asyncio.create_task(
        executor.execute_directive(pending.directive_id, state, NEXT_OPEN)
    )
    activation_task = asyncio.create_task(
        activator.activate(
            successor.plan_id,
            NOW + timedelta(hours=3),
            actor="aic-codex-cto",
            source="blocker-08",
        )
    )
    await asyncio.wait_for(execution_repository.attempted.wait(), 2)
    await asyncio.wait_for(activation_repository.attempted.wait(), 2)
    assert not execution_task.done() and not activation_task.done()
    terminal_repository.release.set()
    await terminal_task
    with pytest.raises(TradePlanError) as blocked:
        await execution_task
    assert blocked.value.code is TradePlanErrorCode.TERMINAL_EXECUTION_BLOCKED
    assert (await activation_task).status is TradePlanStatus.ACTIVE

    entry = await setup.create_directive(
        successor.plan_id,
        DirectiveType.ENTRY,
        Quantity(Decimal("100")),
        NOW + timedelta(hours=4),
        source_reference="successor-entry",
    )
    successor_evidence = await setup.execute_directive(
        entry.directive_id,
        state,
        NEXT_OPEN,
        price_limit_band=PriceLimitBand(Decimal("1"), Decimal("100"), "fixture", NEXT_OPEN),
    )
    after_successor = ExecutionStateSnapshot.capture(state)
    assert after_successor.settlement_positions[0].total_quantity == Decimal("100")
    with pytest.raises(TradePlanError) as retry_blocked:
        await setup.execute_directive(pending.directive_id, state, NEXT_OPEN + timedelta(days=1))
    assert retry_blocked.value.code is TradePlanErrorCode.TERMINAL_EXECUTION_BLOCKED
    assert ExecutionStateSnapshot.capture(state) == after_successor

    await engine.dispose()
    restarted_engine = create_async_engine(os.environ["AIC_DATABASE_URL"])
    try:
        restarted_repository = PostgreSQLTradePlanRepository(restarted_engine)
        restarted = TradePlanService(
            restarted_repository,
            Calendar(),
            IdempotentExecutionService(
                MustNotExecute(), PostgreSQLExecutionJournal(restarted_engine)
            ),
        )
        with pytest.raises(TradePlanError) as restart_blocked:
            await restarted.execute_directive(
                pending.directive_id, state, NEXT_OPEN + timedelta(days=2)
            )
        assert restart_blocked.value.code is TradePlanErrorCode.TERMINAL_EXECUTION_BLOCKED
        assert ExecutionStateSnapshot.capture(state) == after_successor
        predecessor_record = await restarted_repository.get(predecessor.plan.plan_id)
        successor_record = await restarted_repository.get(successor.plan_id)
        assert predecessor_record.executions == ()
        assert successor_record.executions == (successor_evidence,)
        async with restarted_engine.connect() as connection:
            assert (
                await connection.execute(select(func.count()).select_from(execution_claims))
            ).scalar_one() == 1
            assert (
                await connection.execute(
                    select(func.count()).select_from(trade_plan_execution_evidence)
                )
            ).scalar_one() == 1
    finally:
        await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_terminal_predecessor_cannot_mutate_successor_after_postgresql_restart(engine):
    repository = PostgreSQLTradePlanRepository(engine)
    predecessor = await build(repository, "terminal-predecessor")
    journal = PostgreSQLExecutionJournal(engine)
    runtime = TradePlanService(
        repository, Calendar(), IdempotentExecutionService(authority(engine), journal)
    )
    pending = await runtime.create_directive(
        predecessor.plan.plan_id,
        DirectiveType.REDUCE,
        Quantity(Decimal("100")),
        NOW + timedelta(hours=1),
        source_reference="predecessor-reduce",
    )
    await runtime.transition_terminal(
        predecessor.plan.plan_id,
        TradePlanStatus.CANCELLED,
        NOW + timedelta(hours=2),
        "SUPERSEDED",
    )

    await engine.dispose()
    restarted_engine = create_async_engine(os.environ["AIC_DATABASE_URL"])
    try:
        restarted_repository = PostgreSQLTradePlanRepository(restarted_engine)
        restarted = TradePlanService(
            restarted_repository,
            Calendar(),
            IdempotentExecutionService(
                authority(restarted_engine), PostgreSQLExecutionJournal(restarted_engine)
            ),
        )
        successor = command("terminal-successor")
        await restarted.create_draft(successor)
        await restarted.activate(
            successor.plan_id,
            NOW + timedelta(hours=3),
            actor="aic-codex-cto",
            source="blocker-06",
        )
        entry = await restarted.create_directive(
            successor.plan_id,
            DirectiveType.ENTRY,
            Quantity(Decimal("100")),
            NOW + timedelta(hours=4),
            source_reference="successor-entry",
        )
        state = ExecutionState.initialize(PortfolioId("champion"), Money(Decimal("100000")), NOW)
        successor_evidence = await restarted.execute_directive(
            entry.directive_id,
            state,
            NEXT_OPEN,
            price_limit_band=PriceLimitBand(Decimal("1"), Decimal("100"), "fixture", NEXT_OPEN),
        )
        before_old_directive = ExecutionStateSnapshot.capture(state)
        with pytest.raises(TradePlanError) as error:
            await restarted.execute_directive(
                pending.directive_id, state, NEXT_OPEN + timedelta(days=1)
            )
        assert error.value.code is TradePlanErrorCode.TERMINAL_EXECUTION_BLOCKED
        assert ExecutionStateSnapshot.capture(state) == before_old_directive
        await restarted.transition_terminal(
            successor.plan_id,
            TradePlanStatus.CANCELLED,
            NEXT_OPEN + timedelta(hours=1),
            "TEST_COMPLETE",
        )
        outcome = await restarted.build_outcome(successor.plan_id)
        assert outcome.source_order_ids == (successor_evidence.order_id,)
        assert outcome.remaining_quantity == Decimal("100")
        assert outcome.attribution_provenance == "execution-order-claims/v1"
    finally:
        await restarted_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["expiry", "invalidation"])
async def test_terminal_settlement_barrier_and_outcome_survive_postgresql_restart(engine, terminal):
    repository = PostgreSQLTradePlanRepository(engine)
    value = command(f"terminal-settlement-{terminal}")
    value = (
        replace(value, expiry_at=NOW + timedelta(minutes=30))
        if terminal == "expiry"
        else replace(value, thesis_invalidation_reference="terminal-policy")
    )
    runtime = TradePlanService(
        repository,
        Calendar(),
        IdempotentExecutionService(authority(engine), PostgreSQLExecutionJournal(engine)),
    )
    await runtime.create_draft(value)
    await runtime.activate(value.plan_id, NOW, actor="aic-codex-cto", source="blocker-06")
    settlement = (
        await runtime.evaluate(
            value.plan_id,
            PlanObservation(
                "terminal-observation",
                NOW + timedelta(minutes=30),
                NOW + timedelta(hours=1),
                Decimal("10"),
                Decimal("10"),
                Decimal("10"),
                Decimal("10"),
            ),
            NOW + timedelta(hours=1),
        )
        if terminal == "expiry"
        else await runtime.record_thesis_invalidation(
            value.plan_id,
            event_reference="terminal-event",
            as_of=NOW + timedelta(hours=1),
        )
    )
    successor = command(f"terminal-settlement-successor-{terminal}")
    await runtime.create_draft(successor)

    await engine.dispose()
    restarted_engine = create_async_engine(os.environ["AIC_DATABASE_URL"])
    try:
        restarted_repository = PostgreSQLTradePlanRepository(restarted_engine)
        restarted = TradePlanService(
            restarted_repository,
            Calendar(),
            IdempotentExecutionService(
                authority(restarted_engine), PostgreSQLExecutionJournal(restarted_engine)
            ),
        )
        with pytest.raises(TradePlanError) as error:
            await restarted.activate(
                successor.plan_id,
                NOW + timedelta(hours=2),
                actor="aic-codex-cto",
                source="blocker-06",
            )
        assert error.value.code is TradePlanErrorCode.TERMINAL_SETTLEMENT_PENDING
        evidence = await restarted.execute_directive(
            settlement.directive_id,
            account(),
            NEXT_OPEN,
            price_limit_band=PriceLimitBand(Decimal("1"), Decimal("100"), "fixture", NEXT_OPEN),
        )
        assert evidence.fill_id is not None
        await restarted.activate(
            successor.plan_id,
            NEXT_OPEN + timedelta(minutes=1),
            actor="aic-codex-cto",
            source="blocker-06",
        )
        outcome = await restarted.build_outcome(value.plan_id)
        assert outcome.remaining_quantity == 0
        assert outcome.source_order_ids == (evidence.order_id,)
        assert outcome.attribution_as_of == NEXT_OPEN
        await restarted_engine.dispose()

        second_restart = create_async_engine(os.environ["AIC_DATABASE_URL"])
        try:
            persisted = TradePlanService(
                PostgreSQLTradePlanRepository(second_restart),
                Calendar(),
                IdempotentExecutionService(
                    MustNotExecute(), PostgreSQLExecutionJournal(second_restart)
                ),
            )
            assert await persisted.build_outcome(value.plan_id) == outcome
        finally:
            await second_restart.dispose()
    finally:
        await restarted_engine.dispose()


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
