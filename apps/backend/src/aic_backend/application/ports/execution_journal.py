"""Durable order claims and completed authoritative execution receipts."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from aic_backend.application.execution import ExecutionOrderIntent, ExecutionState
from aic_backend.domain.execution import (
    ExecutionOutcome,
    SettlementBook,
    SettlementPosition,
    SettlementRolloverEvent,
)
from aic_backend.domain.portfolio.accounting import PortfolioAccount
from aic_backend.domain.portfolio.models import (
    CashLedgerEntry,
    Money,
    OrderId,
    PortfolioId,
    PortfolioSnapshot,
    Position,
)


@dataclass(frozen=True, slots=True)
class ExecutionStateSnapshot:
    portfolio_id: PortfolioId
    initial_capital: Money
    cash: Decimal
    positions: tuple[Position, ...]
    cash_ledger: tuple[CashLedgerEntry, ...]
    settlement_positions: tuple[SettlementPosition, ...]
    last_trading_date: date | None
    last_snapshot: PortfolioSnapshot
    activity_date: date | None
    orders_today: int
    filled_orders_today: int
    daily_turnover: Decimal
    pending_settlement_event: SettlementRolloverEvent | None
    outcomes: tuple[ExecutionOutcome, ...]

    @classmethod
    def capture(cls, state: ExecutionState) -> "ExecutionStateSnapshot":
        return cls(
            state.account.portfolio_id,
            state.account.initial_capital,
            state.account.cash,
            tuple(
                sorted(
                    state.account.positions.values(), key=lambda p: p.key.instrument.canonical_key
                )
            ),
            tuple(state.account.cash_ledger),
            tuple(
                sorted(
                    state.settlement.positions.values(), key=lambda p: p.instrument.canonical_key
                )
            ),
            state.settlement.last_trading_date,
            state.last_snapshot,
            state.activity_date,
            state.orders_today,
            state.filled_orders_today,
            state.daily_turnover,
            state.pending_settlement_event,
            tuple(state.outcomes),
        )

    def thaw(self) -> ExecutionState:
        account = PortfolioAccount(self.portfolio_id, self.initial_capital)
        account.cash = self.cash
        account.positions = {p.key.instrument.canonical_key: p for p in self.positions}
        account.cash_ledger = list(self.cash_ledger)
        settlement = SettlementBook(self.portfolio_id)
        settlement.positions = {p.instrument.canonical_key: p for p in self.settlement_positions}
        settlement.last_trading_date = self.last_trading_date
        return ExecutionState(
            account,
            settlement,
            self.last_snapshot,
            self.activity_date,
            self.orders_today,
            self.filled_orders_today,
            self.daily_turnover,
            self.pending_settlement_event,
            list(self.outcomes),
        )


@dataclass(frozen=True, slots=True)
class ExecutionClaim:
    claim_id: str
    order_id: OrderId
    intent: ExecutionOrderIntent
    requested_at: datetime
    before: ExecutionStateSnapshot


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    claim: ExecutionClaim
    outcome: ExecutionOutcome
    after: ExecutionStateSnapshot

    def __post_init__(self) -> None:
        order = self.outcome.order
        if (
            order.order_id != self.claim.order_id
            or order.portfolio_id != self.claim.before.portfolio_id
            or order.instrument != self.claim.intent.instrument
            or order.side != self.claim.intent.side
            or order.quantity != self.claim.intent.quantity
            or order.requested_price != self.claim.intent.requested_price
            or self.outcome.risk_decision.as_of != self.claim.requested_at
            or self.after.portfolio_id != self.claim.before.portfolio_id
            or self.after.outcomes != self.claim.before.outcomes + (self.outcome,)
        ):
            raise ValueError("execution receipt does not match its immutable claim")


class ExecutionJournal(Protocol):
    async def get(self, order_id: OrderId) -> ExecutionClaim | ExecutionReceipt | None: ...

    async def claim(self, value: ExecutionClaim) -> bool:
        """Durably claim an unused order before execution; at most one caller succeeds."""
        ...

    async def complete(self, value: ExecutionReceipt) -> None:
        """Record one immutable result for the exact claim; never release/reuse a claim."""
        ...
