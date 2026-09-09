"""Application-owned persistence and execution ports for Trade Plans."""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from aic_backend.application.execution import ExecutionOrderIntent, ExecutionState
from aic_backend.domain.execution import ExecutionOutcome, PriceLimitBand
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import OrderId
from aic_backend.domain.trade_plan import TradePlanId

if TYPE_CHECKING:
    from aic_backend.application.trade_plan_record import TradePlanRecord
    from aic_backend.domain.trade_plan import TradePlanDirective


class TradePlanRepository(Protocol):
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
