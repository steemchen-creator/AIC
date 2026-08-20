"""Application-owned backtest persistence contracts."""

from dataclasses import dataclass
from typing import Protocol

from aic_backend.domain.portfolio.models import (
    AuditEvent,
    BacktestResult,
    BacktestRun,
    CashLedgerEntry,
    Fill,
    Order,
    PortfolioSnapshot,
)


@dataclass(frozen=True, slots=True)
class BacktestRecord:
    run: BacktestRun
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    cash_ledger: tuple[CashLedgerEntry, ...]
    nav_snapshots: tuple[PortfolioSnapshot, ...]
    audit_events: tuple[AuditEvent, ...]
    result: BacktestResult


class BacktestRepository(Protocol):
    async def save(self, record: BacktestRecord) -> None: ...
    async def get_result(self, run_id: str) -> BacktestResult | None: ...
