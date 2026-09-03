"""Deterministic portfolio accounting aggregate."""

from datetime import datetime
from decimal import Decimal

from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import (
    BacktestErrorCode,
    CashEntryType,
    CashLedgerEntry,
    Fill,
    Money,
    OrderSide,
    PortfolioError,
    PortfolioId,
    PortfolioSnapshot,
    Position,
    PositionKey,
    PositionSnapshot,
)


class PortfolioAccount:
    def __init__(self, portfolio_id: PortfolioId, initial_capital: Money) -> None:
        if initial_capital.amount <= 0:
            raise ValueError("initial capital must be positive")
        self.portfolio_id = portfolio_id
        self.initial_capital = initial_capital
        self.cash = initial_capital.amount
        self.positions: dict[str, Position] = {}
        self.cash_ledger: list[CashLedgerEntry] = []

    def record_initial_capital(self, entry: CashLedgerEntry) -> None:
        if entry.entry_type is not CashEntryType.INITIAL_CAPITAL:
            raise ValueError("initial entry type required")
        if self.cash_ledger:
            raise ValueError("initial capital already recorded")
        self.cash_ledger.append(entry)

    def apply_fill(self, fill: Fill, entry_ids: tuple[str, ...]) -> tuple[CashLedgerEntry, ...]:
        if fill.portfolio_id != self.portfolio_id:
            raise PortfolioError(
                BacktestErrorCode.INVALID_ORDER, "fill belongs to another portfolio"
            )
        key = fill.instrument.canonical_key
        existing = self.positions.get(
            key,
            Position(PositionKey(self.portfolio_id, fill.instrument), Decimal("0"), Decimal("0")),
        )
        notional = fill.quantity.value * fill.fill_price.value
        costs = fill.fee.amount + fill.tax.amount
        if fill.side is OrderSide.BUY:
            debit = notional + costs
            if debit > self.cash:
                raise PortfolioError(
                    BacktestErrorCode.INSUFFICIENT_CASH, "buy exceeds available cash"
                )
            new_quantity = existing.quantity + fill.quantity.value
            average = (
                (existing.quantity * existing.average_cost) + notional + costs
            ) / new_quantity
            self.positions[key] = Position(
                existing.key, new_quantity, average, existing.realized_pnl
            )
            changes: list[tuple[CashEntryType, Decimal]] = [
                (CashEntryType.BUY_SETTLEMENT, -notional)
            ]
        else:
            if fill.quantity.value > existing.quantity:
                raise PortfolioError(
                    BacktestErrorCode.INSUFFICIENT_POSITION, "sell exceeds position"
                )
            proceeds = notional
            realized = (fill.fill_price.value - existing.average_cost) * fill.quantity.value - costs
            remaining = existing.quantity - fill.quantity.value
            self.positions[key] = Position(
                existing.key,
                remaining,
                existing.average_cost if remaining else Decimal("0"),
                existing.realized_pnl + realized,
            )
            changes = [(CashEntryType.SELL_SETTLEMENT, proceeds)]
        if fill.fee.amount:
            changes.append((CashEntryType.FEE, -fill.fee.amount))
        if fill.tax.amount:
            changes.append((CashEntryType.TAX, -fill.tax.amount))
        if len(entry_ids) != len(changes):
            raise ValueError("entry ids must match cash changes")
        entries: list[CashLedgerEntry] = []
        for entry_id, (entry_type, amount) in zip(entry_ids, changes, strict=True):
            self.cash += amount
            if self.cash < 0:
                raise PortfolioError(
                    BacktestErrorCode.INSUFFICIENT_CASH, "cash must not be negative"
                )
            entry = CashLedgerEntry(
                entry_id,
                self.portfolio_id,
                fill.executed_at,
                entry_type,
                Money(amount),
                Money(self.cash),
                fill.fill_id.value,
            )
            entries.append(entry)
            self.cash_ledger.append(entry)
        return tuple(entries)

    def snapshot(
        self, as_of: datetime, marks: dict[InstrumentIdentity, Decimal]
    ) -> PortfolioSnapshot:
        values: list[PositionSnapshot] = []
        for position in sorted(
            self.positions.values(), key=lambda item: item.key.instrument.canonical_key
        ):
            if position.quantity == 0:
                continue
            try:
                mark = marks[position.key.instrument]
            except KeyError as error:
                raise PortfolioError(
                    BacktestErrorCode.PIT_DATA_UNAVAILABLE,
                    f"missing PIT mark for {position.key.instrument.canonical_key}",
                ) from error
            market_value = position.quantity * mark
            unrealized = market_value - position.quantity * position.average_cost
            values.append(
                PositionSnapshot(
                    position.key.instrument,
                    position.quantity,
                    position.average_cost,
                    mark,
                    market_value,
                    unrealized,
                    position.realized_pnl,
                )
            )
        market_value = sum((item.market_value for item in values), Decimal("0"))
        realized = sum((item.realized_pnl for item in self.positions.values()), Decimal("0"))
        unrealized = sum((item.unrealized_pnl for item in values), Decimal("0"))
        return PortfolioSnapshot(
            self.portfolio_id,
            as_of,
            Money(self.cash),
            tuple(values),
            Money(market_value),
            Money(realized),
            Money(unrealized),
            Money(self.cash + market_value),
        )
