"""Reconcile durable execution receipts before any repeated financial operation."""

from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from aic_backend.application.execution import ExecutionOrderIntent, ExecutionState
from aic_backend.application.ports.execution_journal import (
    ExecutionClaim,
    ExecutionJournal,
    ExecutionReceipt,
    ExecutionStateSnapshot,
)
from aic_backend.application.ports.trade_plan import (
    AuthoritativeOutcomeAttribution,
    OutcomeAttributionError,
)
from aic_backend.domain.execution import ExecutionOutcome, PriceLimitBand
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import OrderId, OrderSide, PortfolioId, Position
from aic_backend.domain.trade_plan import DirectiveType, PlanExecutionEvidence, stable_plan_id


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
    OUTCOME_PROVENANCE = "execution-order-claims/v1"

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

    async def outcome_attribution(
        self,
        portfolio_id: PortfolioId,
        instrument: InstrumentIdentity,
        evidence: tuple[PlanExecutionEvidence, ...],
        as_of: datetime,
    ) -> AuthoritativeOutcomeAttribution:
        if not evidence:
            raise OutcomeAttributionError(
                "outcome attribution requires durable plan execution evidence"
            )
        if len({item.order_id for item in evidence}) != len(evidence):
            raise OutcomeAttributionError("outcome attribution contains duplicate order evidence")
        receipts: list[ExecutionReceipt] = []
        for link in sorted(evidence, key=lambda item: (item.executed_at, item.order_id)):
            entry = await self._journal.get(OrderId(link.order_id))
            if not isinstance(entry, ExecutionReceipt):
                raise OutcomeAttributionError(
                    "plan execution link has no completed authoritative receipt"
                )
            outcome = entry.outcome
            expected_side = (
                OrderSide.BUY
                if link.directive_type in (DirectiveType.ENTRY, DirectiveType.SCALE_IN)
                else OrderSide.SELL
            )
            if (
                link.fill_id != (None if outcome.fill is None else outcome.fill.fill_id.value)
                or link.executed_at != outcome.risk_decision.as_of
                or link.rejected_reason_codes
                != tuple(item.value for item in outcome.risk_decision.reason_codes)
                or outcome.order.portfolio_id != portfolio_id
                or outcome.order.instrument != instrument
                or outcome.order.side is not expected_side
                or entry.claim.before.portfolio_id != portfolio_id
                or entry.after.portfolio_id != portfolio_id
                or outcome.risk_decision.as_of > as_of
            ):
                raise OutcomeAttributionError(
                    "plan execution link conflicts with authoritative ledger evidence"
                )
            receipts.append(entry)

        def position(snapshot: ExecutionStateSnapshot) -> Position | None:
            return next(
                (item for item in snapshot.positions if item.key.instrument == instrument), None
            )

        realized = Decimal("0")
        average: Decimal | None = None
        remaining = Decimal("0")
        for receipt in receipts:
            before = position(receipt.claim.before)
            after = position(receipt.after)
            before_realized = Decimal("0") if before is None else before.realized_pnl
            after_realized = Decimal("0") if after is None else after.realized_pnl
            realized += after_realized - before_realized
            for candidate in (after, before):
                if candidate is not None and candidate.quantity > 0:
                    average = candidate.average_cost
                    break
            remaining = Decimal("0") if after is None else after.quantity
        order_ids = tuple(receipt.outcome.order.order_id.value for receipt in receipts)
        source_id = stable_plan_id(
            "outcome-attribution", portfolio_id.value, instrument.canonical_key, *order_ids
        )
        return AuthoritativeOutcomeAttribution(
            source_id,
            portfolio_id,
            instrument,
            max(receipt.outcome.risk_decision.as_of for receipt in receipts),
            self.OUTCOME_PROVENANCE,
            average,
            remaining,
            realized,
            order_ids,
        )

    @staticmethod
    def _restore(state: ExecutionState, snapshot: ExecutionStateSnapshot) -> None:
        restored = snapshot.thaw()
        for field in fields(ExecutionState):
            setattr(state, field.name, getattr(restored, field.name))
