"""Reconcile durable execution receipts before any repeated financial operation."""

from dataclasses import fields
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from aic_backend.application.execution import ExecutionOrderIntent, ExecutionState
from aic_backend.application.ports.execution_journal import (
    ExecutionClaim,
    ExecutionJournal,
    ExecutionReceipt,
    ExecutionStateSnapshot,
)
from aic_backend.domain.execution import ExecutionOutcome, PriceLimitBand
from aic_backend.domain.portfolio.models import OrderId


class ExecutionReconciliationError(RuntimeError):
    """A durable order cannot safely be executed or projected again."""


class ExecutionEngine(Protocol):
    async def execute(
        self,
        state: ExecutionState,
        intent: ExecutionOrderIntent,
        order_id: OrderId,
        as_of: datetime,
        price_limit_band: PriceLimitBand | None,
    ) -> ExecutionOutcome: ...


class IdempotentExecutionService:
    def __init__(self, execution: ExecutionEngine, journal: ExecutionJournal) -> None:
        self._execution = execution
        self._journal = journal

    async def reconcile(
        self,
        state: ExecutionState,
        order_id: OrderId,
        as_of: datetime,
    ) -> ExecutionOutcome | None:
        entry = await self._journal.get(order_id)
        if entry is None:
            return None
        if isinstance(entry, ExecutionClaim):
            raise ExecutionReconciliationError("order has an unresolved durable execution claim")
        if entry.claim.before.portfolio_id != state.account.portfolio_id:
            raise ExecutionReconciliationError("order belongs to another account")
        if as_of < entry.outcome.risk_decision.as_of:
            raise ExecutionReconciliationError("execution outcome is not visible as_of")
        current = ExecutionStateSnapshot.capture(state)
        if current == entry.claim.before:
            self._restore(state, entry.after)
        elif current != entry.after and entry.outcome not in state.outcomes:
            raise ExecutionReconciliationError(
                "account state cannot reconcile the execution receipt"
            )
        # A later account state already containing this outcome must never be rolled back.
        return entry.outcome

    async def execute(
        self,
        state: ExecutionState,
        intent: ExecutionOrderIntent,
        order_id: OrderId,
        as_of: datetime,
        price_limit_band: PriceLimitBand | None,
    ) -> ExecutionOutcome:
        entry = await self._journal.get(order_id)
        if entry is not None:
            claim = entry.claim if isinstance(entry, ExecutionReceipt) else entry
            if claim.intent != intent or claim.before.portfolio_id != state.account.portfolio_id:
                raise ExecutionReconciliationError(
                    "order id identifies a different execution request"
                )
            outcome = await self.reconcile(state, order_id, as_of)
            assert outcome is not None
            return outcome
        before = ExecutionStateSnapshot.capture(state)
        claim = ExecutionClaim(str(uuid4()), order_id, intent, as_of, before)
        if not await self._journal.claim(claim):
            # The winner may still be executing; reconciliation fails closed for pending claims.
            winner = await self._journal.get(order_id)
            winner_claim = winner.claim if isinstance(winner, ExecutionReceipt) else winner
            if winner_claim is None or winner_claim.intent != intent:
                raise ExecutionReconciliationError(
                    "competing order claim identifies another request"
                )
            reconciled = await self.reconcile(state, order_id, as_of)
            if reconciled is None:
                raise ExecutionReconciliationError("durable execution claim disappeared")
            return reconciled
        working = before.thaw()
        outcome = await self._execution.execute(working, intent, order_id, as_of, price_limit_band)
        receipt = ExecutionReceipt(claim, outcome, ExecutionStateSnapshot.capture(working))
        await self._journal.complete(receipt)
        if ExecutionStateSnapshot.capture(state) != before:
            raise ExecutionReconciliationError(
                "account changed during execution; committed receipt requires reconciliation"
            )
        self._restore(state, receipt.after)
        return outcome

    @staticmethod
    def _restore(state: ExecutionState, snapshot: ExecutionStateSnapshot) -> None:
        restored = snapshot.thaw()
        for field in fields(ExecutionState):
            setattr(state, field.name, getattr(restored, field.name))
