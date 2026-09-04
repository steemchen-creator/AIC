"""Replaceable A-share lot, price-limit, and pre-trade risk policies."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from aic_backend.domain.execution.models import (
    PriceLimitBand,
    PriceLimitClassification,
    RiskInputSummary,
    RiskPolicyConfig,
    RiskReasonCode,
    TradingEligibility,
)
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import Money, OrderSide, PortfolioSnapshot, Price, Quantity


class LotPolicy(Protocol):
    version: str

    def validate(self, side: OrderSide, quantity: Quantity) -> bool: ...


@dataclass(frozen=True, slots=True)
class AShareBoardLotPolicy:
    buy_lot_size: int = 100
    version: str = "a-share-board-lot/v1"

    def __post_init__(self) -> None:
        if self.buy_lot_size <= 0:
            raise ValueError("buy lot size must be positive")

    def validate(self, side: OrderSide, quantity: Quantity) -> bool:
        if quantity.value != quantity.value.to_integral_value():
            return False
        return side is OrderSide.SELL or int(quantity.value) % self.buy_lot_size == 0


class PriceLimitPolicy(Protocol):
    version: str

    def classify(self, price: Price, band: PriceLimitBand | None) -> PriceLimitClassification: ...


@dataclass(frozen=True, slots=True)
class ExplicitPriceLimitPolicy:
    version: str = "explicit-price-limit/v1"

    def classify(self, price: Price, band: PriceLimitBand | None) -> PriceLimitClassification:
        if band is None:
            return PriceLimitClassification.UNKNOWN_LIMIT
        if price.value > band.upper:
            return PriceLimitClassification.UPPER_LIMIT
        if price.value < band.lower:
            return PriceLimitClassification.LOWER_LIMIT
        return PriceLimitClassification.WITHIN_LIMIT


@dataclass(frozen=True, slots=True)
class PreTradeRiskInput:
    snapshot: PortfolioSnapshot
    instrument: InstrumentIdentity
    side: OrderSide
    quantity: Quantity
    price: Price
    eligibility: TradingEligibility
    as_of: datetime
    transaction_cost: Decimal
    sellable_quantity: Decimal
    orders_today: int
    filled_orders_today: int
    daily_turnover: Decimal

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")


class PreTradeRiskPolicy:
    def __init__(self, config: RiskPolicyConfig) -> None:
        self.config = config
        self.version = config.version

    def evaluate(self, value: PreTradeRiskInput) -> tuple[RiskReasonCode, ...]:
        summary = self.summarize(value)
        nav = value.snapshot.nav.amount
        eligibility = value.eligibility
        eligibility_reasons: set[RiskReasonCode] = set()
        if not eligibility.market_open:
            eligibility_reasons.add(RiskReasonCode.MARKET_CLOSED)
        if not eligibility.instrument_listed:
            eligibility_reasons.add(RiskReasonCode.INSTRUMENT_NOT_LISTED)
        if eligibility.instrument_delisted:
            eligibility_reasons.add(RiskReasonCode.INSTRUMENT_DELISTED)
        if eligibility.instrument_suspended:
            eligibility_reasons.add(RiskReasonCode.INSTRUMENT_SUSPENDED)
        if not eligibility.instrument_status_known:
            eligibility_reasons.add(RiskReasonCode.INSTRUMENT_STATUS_UNKNOWN)
        if nav <= 0:
            eligibility_reasons.add(RiskReasonCode.UNSUPPORTED_RULE)
            return tuple(sorted(eligibility_reasons, key=lambda item: item.value))
        notional = value.quantity.value * value.price.value
        post_position = summary.post_trade_position_exposure.amount
        post_gross = summary.post_trade_gross_exposure.amount
        post_cash = summary.post_trade_cash.amount
        post_nav = nav - value.transaction_cost
        reasons = eligibility_reasons
        if value.side is OrderSide.BUY and post_cash < 0:
            reasons.add(RiskReasonCode.INSUFFICIENT_CASH)
        if value.side is OrderSide.SELL and value.quantity.value > value.sellable_quantity:
            reasons.add(RiskReasonCode.INSUFFICIENT_SELLABLE_POSITION)
        if post_nav <= 0:
            reasons.add(RiskReasonCode.GROSS_EXPOSURE_LIMIT)
        else:
            if post_position / post_nav > self.config.max_single_position_pct:
                reasons.add(RiskReasonCode.SINGLE_POSITION_LIMIT)
            if post_gross / post_nav > self.config.max_gross_exposure_pct:
                reasons.add(RiskReasonCode.GROSS_EXPOSURE_LIMIT)
            minimum_cash = max(
                self.config.minimum_cash_amount,
                post_nav * self.config.minimum_cash_buffer_pct,
            )
            if post_cash < minimum_cash:
                reasons.add(RiskReasonCode.CASH_BUFFER_LIMIT)
            turnover = value.daily_turnover + notional
            if (
                self.config.max_daily_turnover_pct is not None
                and turnover / nav > self.config.max_daily_turnover_pct
            ):
                reasons.add(RiskReasonCode.TRADE_FREQUENCY_LIMIT)
        if (
            self.config.max_orders_per_day is not None
            and value.orders_today >= self.config.max_orders_per_day
        ) or (
            self.config.max_filled_orders_per_day is not None
            and value.filled_orders_today >= self.config.max_filled_orders_per_day
        ):
            reasons.add(RiskReasonCode.TRADE_FREQUENCY_LIMIT)
        return tuple(sorted(reasons, key=lambda item: item.value))

    @staticmethod
    def summarize(value: PreTradeRiskInput) -> RiskInputSummary:
        notional = value.quantity.value * value.price.value
        current_values = {
            item.instrument.canonical_key: item.market_value for item in value.snapshot.positions
        }
        current_position = current_values.get(value.instrument.canonical_key, Decimal("0"))
        direction = Decimal("1") if value.side is OrderSide.BUY else Decimal("-1")
        return RiskInputSummary(
            value.snapshot.nav,
            value.snapshot.cash,
            Money(sum(current_values.values(), Decimal("0"))),
            Money(sum(current_values.values(), Decimal("0")) + direction * notional),
            Money(current_position + direction * notional),
            Money(value.snapshot.cash.amount - direction * notional - value.transaction_cost),
            value.orders_today,
            value.filled_orders_today,
            Money(value.daily_turnover),
        )
