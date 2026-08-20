"""Deterministic, injectable transaction-cost policies."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from aic_backend.domain.portfolio.models import Money, OrderSide, Price, Quantity


class FeePolicy(Protocol):
    version: str

    def calculate(
        self, side: OrderSide, quantity: Quantity, price: Price
    ) -> tuple[Money, Money]: ...


class SlippagePolicy(Protocol):
    version: str

    def apply(
        self, side: OrderSide, reference_price: Price, quantity: Quantity
    ) -> tuple[Price, Money]: ...


@dataclass(frozen=True, slots=True)
class ConfigurableFeePolicy:
    commission_rate: Decimal = Decimal("0")
    minimum_commission: Decimal = Decimal("0")
    sell_stamp_tax_rate: Decimal = Decimal("0")
    version: str = "configurable-fee/v1"

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (self.commission_rate, self.minimum_commission, self.sell_stamp_tax_rate)
        ):
            raise ValueError("fee rates must not be negative")

    def calculate(self, side: OrderSide, quantity: Quantity, price: Price) -> tuple[Money, Money]:
        notional = quantity.value * price.value
        commission = max(notional * self.commission_rate, self.minimum_commission)
        tax = notional * self.sell_stamp_tax_rate if side is OrderSide.SELL else Decimal("0")
        return Money(commission), Money(tax)


@dataclass(frozen=True, slots=True)
class FixedBpsSlippagePolicy:
    basis_points: Decimal = Decimal("0")
    version: str = "fixed-bps-slippage/v1"

    def __post_init__(self) -> None:
        if self.basis_points < 0:
            raise ValueError("basis points must not be negative")

    def apply(
        self, side: OrderSide, reference_price: Price, quantity: Quantity
    ) -> tuple[Price, Money]:
        rate = self.basis_points / Decimal("10000")
        direction = Decimal("1") if side is OrderSide.BUY else Decimal("-1")
        fill = Price(reference_price.value * (Decimal("1") + direction * rate))
        cost = abs(fill.value - reference_price.value) * quantity.value
        return fill, Money(cost)
