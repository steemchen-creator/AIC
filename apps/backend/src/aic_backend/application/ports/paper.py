"""Application-owned ports for forward paper trading."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from aic_backend.domain.execution import ExecutionOutcome, PriceLimitBand
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.paper import (
    PaperAccount,
    PaperOrderIntent,
    PaperPerformanceSnapshot,
    PaperPortfolioState,
    PaperSession,
    PaperStateEvent,
    TradeEpisode,
)


@dataclass(frozen=True, slots=True)
class PaperTradingRecord:
    account: PaperAccount
    portfolio_state: PaperPortfolioState
    sessions: tuple[PaperSession, ...] = ()
    intents: tuple[PaperOrderIntent, ...] = ()
    outcomes: tuple[ExecutionOutcome, ...] = ()
    performance: tuple[PaperPerformanceSnapshot, ...] = ()
    episodes: tuple[TradeEpisode, ...] = ()
    events: tuple[PaperStateEvent, ...] = ()


class PaperTradingRepository(Protocol):
    async def save(self, record: PaperTradingRecord) -> None: ...

    async def get(self, account_id: str) -> PaperTradingRecord | None: ...


class PaperDecisionSource(Protocol):
    @property
    def source_id(self) -> str: ...

    async def intents_for(
        self, account_id: str, trading_date: date
    ) -> tuple[PaperOrderIntent, ...]: ...


class PaperReadinessGate(Protocol):
    async def check(self, account: PaperAccount, as_of: datetime) -> tuple[str, ...]: ...


class PriceLimitBandSource(Protocol):
    async def get_band(
        self,
        instrument: InstrumentIdentity,
        trading_date: date,
        as_of: datetime,
    ) -> PriceLimitBand | None: ...


class PaperClock(Protocol):
    def now(self) -> datetime: ...
