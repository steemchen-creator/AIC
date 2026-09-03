"""Deterministic A-share T+1 settlement book."""

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from aic_backend.domain.execution.models import SettlementPosition, SettlementRolloverEvent
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import Fill, OrderSide, PortfolioId


class SettlementBook:
    VERSION = "a-share-t1-settlement/v1"

    def __init__(self, portfolio_id: PortfolioId) -> None:
        self.portfolio_id = portfolio_id
        self.positions: dict[str, SettlementPosition] = {}
        self.last_trading_date: date | None = None

    def seed(self, position: SettlementPosition) -> None:
        if position.instrument.canonical_key in self.positions:
            raise ValueError("settlement position already exists")
        self.positions[position.instrument.canonical_key] = position

    def rollover(self, trading_date: date, occurred_at: datetime) -> SettlementRolloverEvent | None:
        if self.last_trading_date is not None and trading_date <= self.last_trading_date:
            return None
        released = Decimal("0")
        if self.last_trading_date is not None:
            for key, position in tuple(self.positions.items()):
                released += position.today_bought_quantity
                self.positions[key] = SettlementPosition(
                    position.instrument,
                    position.total_quantity,
                    position.sellable_quantity + position.today_bought_quantity,
                    Decimal("0"),
                )
        self.last_trading_date = trading_date
        material = f"{self.portfolio_id.value}|{trading_date}|{released}|{self.VERSION}"
        return SettlementRolloverEvent(
            f"settlement-{sha256(material.encode()).hexdigest()[:32]}",
            self.portfolio_id,
            trading_date,
            occurred_at,
            released,
            self.VERSION,
        )

    def apply_fill(self, fill: Fill) -> SettlementPosition:
        key = fill.instrument.canonical_key
        current = self.positions.get(
            key, SettlementPosition(fill.instrument, Decimal("0"), Decimal("0"), Decimal("0"))
        )
        quantity = fill.quantity.value
        if fill.side is OrderSide.BUY:
            updated = SettlementPosition(
                fill.instrument,
                current.total_quantity + quantity,
                current.sellable_quantity,
                current.today_bought_quantity + quantity,
            )
        else:
            if quantity > current.sellable_quantity:
                raise ValueError("fill exceeds sellable quantity")
            updated = SettlementPosition(
                fill.instrument,
                current.total_quantity - quantity,
                current.sellable_quantity - quantity,
                current.today_bought_quantity,
            )
        self.positions[key] = updated
        return updated

    def get(self, instrument: InstrumentIdentity) -> SettlementPosition:
        return self.positions.get(
            instrument.canonical_key,
            SettlementPosition(instrument, Decimal("0"), Decimal("0"), Decimal("0")),
        )
