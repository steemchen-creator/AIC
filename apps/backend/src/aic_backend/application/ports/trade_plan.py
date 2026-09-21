"""Application-owned persistence and execution ports for Trade Plans."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from aic_backend.application.execution import ExecutionOrderIntent, ExecutionState
from aic_backend.domain.execution import ExecutionOutcome, PriceLimitBand
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import OrderId, PortfolioId
from aic_backend.domain.trade_plan import PlanExecutionEvidence, TradePlanId

if TYPE_CHECKING:
    from aic_backend.application.trade_plan_record import TradePlanRecord
    from aic_backend.domain.trade_plan import TradePlanDirective


class TradePlanRepository(Protocol):
    def pair_fence(
        self, portfolio_id: str, instrument_key: str
    ) -> AbstractAsyncContextManager[None]: ...

    async def save(self, record: "TradePlanRecord") -> None: ...

    async def get(self, plan_id: TradePlanId) -> "TradePlanRecord | None": ...

    async def get_active(
        self, portfolio_id: str, instrument_key: str
    ) -> "TradePlanRecord | None": ...

    async def list_for_pair(
        self, portfolio_id: str, instrument_key: str
    ) -> tuple["TradePlanRecord", ...]: ...

    async def get_by_directive(
        self, directive_id: str
    ) -> "tuple[TradePlanRecord, TradePlanDirective] | None": ...


class NextEligibleOpenCalendar(Protocol):
    async def next_open(
        self, instrument: InstrumentIdentity, decision_at: datetime
    ) -> datetime: ...


@dataclass(frozen=True, slots=True)
class AuthoritativeOutcomeAttribution:
    source_id: str
    portfolio_id: PortfolioId
    instrument: InstrumentIdentity
    as_of: datetime
    provenance: str
    average_entry_price: Decimal | None
    remaining_quantity: Decimal
    realized_pnl: Decimal
    source_order_ids: tuple[str, ...]


class OutcomeAttributionError(RuntimeError):
    """Authoritative ledger evidence cannot produce a verified plan attribution."""


class AuthoritativeExecution(Protocol):
    async def reconcile(
        self,
        state: ExecutionState,
        order_id: OrderId,
        as_of: datetime,
    ) -> ExecutionOutcome | None:
        """Recover a durable result before position checks; unresolved claims fail closed."""
        ...

    async def execute(
        self,
        state: ExecutionState,
        intent: ExecutionOrderIntent,
        order_id: OrderId,
        as_of: datetime,
        price_limit_band: PriceLimitBand | None,
    ) -> ExecutionOutcome: ...

    async def outcome_attribution(
        self,
        portfolio_id: PortfolioId,
        instrument: InstrumentIdentity,
        evidence: tuple[PlanExecutionEvidence, ...],
        as_of: datetime,
    ) -> AuthoritativeOutcomeAttribution:
        """Replay immutable authoritative receipts into a plan-scoped ledger projection."""
        ...
