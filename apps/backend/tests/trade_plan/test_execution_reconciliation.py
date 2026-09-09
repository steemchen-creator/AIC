import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from apps.backend.tests.infrastructure.test_trade_plan_execution_reconciliation import (
    INSTRUMENT,
    NEXT_OPEN,
    MustNotExecute,
    account,
    authority,
)

from aic_backend.application.execution import ExecutionOrderIntent
from aic_backend.application.idempotent_execution import (
    ExecutionReconciliationError,
    IdempotentExecutionService,
)
from aic_backend.application.ports.execution_journal import ExecutionReceipt, ExecutionStateSnapshot
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.domain.execution import PriceLimitBand
from aic_backend.domain.portfolio.models import OrderId, OrderSide, PortfolioId, Quantity
from aic_backend.infrastructure.execution_journal import _RECEIPT, InMemoryExecutionJournal, _json


def intent():
    return ExecutionOrderIntent(INSTRUMENT, OrderSide.BUY, Quantity(Decimal("100")))


@pytest.mark.asyncio
async def test_receipt_replay_identity_pit_and_account_projection_guards():
    state = account()
    before = ExecutionStateSnapshot.capture(state)
    journal = InMemoryExecutionJournal()
    runtime = IdempotentExecutionService(authority(), journal)
    order_id = OrderId("replay")
    outcome = await runtime.execute(
        state,
        intent(),
        order_id,
        NEXT_OPEN,
        PriceLimitBand(Decimal("1"), Decimal("100"), "fixture", NEXT_OPEN),
    )
    assert outcome.fill is not None
    after = ExecutionStateSnapshot.capture(state)
    receipt = await journal.get(order_id)
    assert isinstance(receipt, ExecutionReceipt)
    assert _RECEIPT.validate_python(_json(receipt)) == receipt
    restarted = IdempotentExecutionService(MustNotExecute(), journal)
    restored = before.thaw()
    assert (
        await restarted.execute(restored, intent(), order_id, NEXT_OPEN + timedelta(days=1), None)
        == outcome
    )
    assert ExecutionStateSnapshot.capture(restored) == after
    restored.orders_today += 1
    later = ExecutionStateSnapshot.capture(restored)
    assert await restarted.reconcile(restored, order_id, NEXT_OPEN + timedelta(days=1)) == outcome
    assert ExecutionStateSnapshot.capture(restored) == later
    with pytest.raises(ExecutionReconciliationError, match="different execution request"):
        await restarted.execute(
            state, replace(intent(), quantity=Quantity(Decimal("200"))), order_id, NEXT_OPEN, None
        )
    with pytest.raises(ExecutionReconciliationError, match="visible as_of"):
        await restarted.reconcile(state, order_id, NEXT_OPEN - timedelta(seconds=1))
    unrelated = before.thaw()
    unrelated.account.cash += Decimal("1")
    with pytest.raises(ExecutionReconciliationError, match="account state"):
        await restarted.reconcile(unrelated, order_id, NEXT_OPEN)
    unrelated.account.portfolio_id = PortfolioId("another")
    with pytest.raises(ExecutionReconciliationError, match="another account"):
        await restarted.reconcile(unrelated, order_id, NEXT_OPEN)
    assert ExecutionStateSnapshot.capture(state) == after
    await journal.complete(receipt)
    with pytest.raises(PersistenceError):
        await journal.complete(replace(receipt, claim=replace(receipt.claim, claim_id="forged")))
    with pytest.raises(ValueError, match="immutable claim"):
        replace(receipt, after=before)


@pytest.mark.asyncio
@pytest.mark.parametrize("change_account", [False, True])
async def test_same_order_concurrent_caller_cannot_execute_pending_claim(change_account):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class PausingAuthority:
        async def execute(self, *args):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return await authority().execute(*args)

    journal = InMemoryExecutionJournal()
    runtime = IdempotentExecutionService(PausingAuthority(), journal)
    state = account()
    first = asyncio.create_task(
        runtime.execute(state, intent(), OrderId("concurrent"), NEXT_OPEN, None)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(ExecutionReconciliationError, match="unresolved durable"):
            await runtime.execute(state, intent(), OrderId("concurrent"), NEXT_OPEN, None)
        if change_account:
            state.account.cash += Decimal("1")
            changed = ExecutionStateSnapshot.capture(state)
            release.set()
            with pytest.raises(ExecutionReconciliationError, match="account changed"):
                await first
            assert ExecutionStateSnapshot.capture(state) == changed
            assert calls == 1
            return
        release.set()
        outcome = await first
        assert outcome.fill is None  # rejected executions also own their permanent identity
        assert (
            await runtime.execute(state, intent(), OrderId("concurrent"), NEXT_OPEN, None)
            == outcome
        )
        assert calls == 1 and state.orders_today == 1
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
