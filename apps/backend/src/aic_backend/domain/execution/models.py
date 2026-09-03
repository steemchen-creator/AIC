"""Immutable A-share execution, settlement, and risk evidence."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import (
    AuditEvent,
    CashLedgerEntry,
    Fill,
    Money,
    Order,
    OrderId,
    PortfolioId,
)


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")


class RiskDecisionType(StrEnum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"


class RiskReasonCode(StrEnum):
    MARKET_CLOSED = "MARKET_CLOSED"
    INSTRUMENT_NOT_LISTED = "INSTRUMENT_NOT_LISTED"
    INSTRUMENT_DELISTED = "INSTRUMENT_DELISTED"
    INSTRUMENT_SUSPENDED = "INSTRUMENT_SUSPENDED"
    INSTRUMENT_STATUS_UNKNOWN = "INSTRUMENT_STATUS_UNKNOWN"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    INSUFFICIENT_SELLABLE_POSITION = "INSUFFICIENT_SELLABLE_POSITION"
    INVALID_LOT_SIZE = "INVALID_LOT_SIZE"
    PRICE_OUTSIDE_LIMIT = "PRICE_OUTSIDE_LIMIT"
    PRICE_LIMIT_UNKNOWN = "PRICE_LIMIT_UNKNOWN"
    SINGLE_POSITION_LIMIT = "SINGLE_POSITION_LIMIT"
    GROSS_EXPOSURE_LIMIT = "GROSS_EXPOSURE_LIMIT"
    CASH_BUFFER_LIMIT = "CASH_BUFFER_LIMIT"
    TRADE_FREQUENCY_LIMIT = "TRADE_FREQUENCY_LIMIT"
    PIT_DATA_UNAVAILABLE = "PIT_DATA_UNAVAILABLE"
    UNSUPPORTED_RULE = "UNSUPPORTED_RULE"


class PriceLimitClassification(StrEnum):
    UPPER_LIMIT = "UPPER_LIMIT"
    LOWER_LIMIT = "LOWER_LIMIT"
    WITHIN_LIMIT = "WITHIN_LIMIT"
    UNKNOWN_LIMIT = "UNKNOWN_LIMIT"


@dataclass(frozen=True, slots=True)
class PriceLimitBand:
    lower: Decimal
    upper: Decimal
    source_id: str
    available_at: datetime

    def __post_init__(self) -> None:
        if self.lower <= 0 or self.upper <= 0 or self.upper < self.lower:
            raise ValueError("price-limit band must be positive and ordered")
        if not self.source_id.strip():
            raise ValueError("price-limit source_id must not be empty")
        require_aware(self.available_at, "available_at")


@dataclass(frozen=True, slots=True)
class SettlementPosition:
    instrument: InstrumentIdentity
    total_quantity: Decimal
    sellable_quantity: Decimal
    today_bought_quantity: Decimal

    def __post_init__(self) -> None:
        values = (self.total_quantity, self.sellable_quantity, self.today_bought_quantity)
        if any(value < 0 or value != value.to_integral_value() for value in values):
            raise ValueError("settlement quantities must be non-negative whole shares")
        if self.sellable_quantity + self.today_bought_quantity > self.total_quantity:
            raise ValueError("settlement quantities exceed total quantity")


@dataclass(frozen=True, slots=True)
class SettlementRolloverEvent:
    event_id: str
    portfolio_id: PortfolioId
    trading_date: date
    occurred_at: datetime
    released_quantity: Decimal
    policy_version: str

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        require_aware(self.occurred_at, "occurred_at")
        if self.released_quantity < 0:
            raise ValueError("released quantity must not be negative")
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be empty")


@dataclass(frozen=True, slots=True)
class TradingEligibility:
    market_open: bool
    instrument_listed: bool
    instrument_delisted: bool
    instrument_suspended: bool
    instrument_status_known: bool


@dataclass(frozen=True, slots=True)
class ExecutionPolicyVersions:
    execution: str
    lot: str
    price_limit: str
    settlement: str
    risk: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.execution,
                self.lot,
                self.price_limit,
                self.settlement,
                self.risk,
            )
        ):
            raise ValueError("policy versions must not be empty")


@dataclass(frozen=True, slots=True)
class RiskPolicyConfig:
    max_single_position_pct: Decimal
    max_gross_exposure_pct: Decimal
    minimum_cash_buffer_pct: Decimal = Decimal("0")
    minimum_cash_amount: Decimal = Decimal("0")
    max_orders_per_day: int | None = None
    max_filled_orders_per_day: int | None = None
    max_daily_turnover_pct: Decimal | None = None
    version: str = "a-share-pre-trade-risk/v1"

    def __post_init__(self) -> None:
        if not Decimal("0") < self.max_single_position_pct <= Decimal("1"):
            raise ValueError("single-position limit must be within (0, 1]")
        if not Decimal("0") < self.max_gross_exposure_pct <= Decimal("1"):
            raise ValueError("gross exposure cannot permit leverage")
        if not Decimal("0") <= self.minimum_cash_buffer_pct <= Decimal("1"):
            raise ValueError("cash buffer pct must be within [0, 1]")
        if self.minimum_cash_amount < 0:
            raise ValueError("minimum cash amount must not be negative")
        if any(
            value is not None and value <= 0
            for value in (self.max_orders_per_day, self.max_filled_orders_per_day)
        ):
            raise ValueError("daily order limits must be positive")
        if self.max_daily_turnover_pct is not None and self.max_daily_turnover_pct <= 0:
            raise ValueError("daily turnover limit must be positive")
        if not self.version.strip():
            raise ValueError("risk policy version must not be empty")


@dataclass(frozen=True, slots=True)
class RiskInputSummary:
    nav: Money
    cash: Money
    current_gross_exposure: Money
    post_trade_gross_exposure: Money
    post_trade_position_exposure: Money
    post_trade_cash: Money
    orders_today: int
    filled_orders_today: int
    daily_turnover: Money


@dataclass(frozen=True, slots=True)
class RiskDecision:
    risk_decision_id: str
    portfolio_id: PortfolioId
    order_id: OrderId
    as_of: datetime
    decision: RiskDecisionType
    reason_codes: tuple[RiskReasonCode, ...]
    policy_version: str
    input_summary: RiskInputSummary

    def __post_init__(self) -> None:
        if not self.risk_decision_id.strip():
            raise ValueError("risk_decision_id must not be empty")
        require_aware(self.as_of, "as_of")
        normalized = tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
        object.__setattr__(self, "reason_codes", normalized)
        if (self.decision is RiskDecisionType.ALLOW) == bool(normalized):
            raise ValueError("ALLOW has no reasons and REJECT requires reasons")
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be empty")


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    snapshot_id: str
    portfolio_id: PortfolioId
    as_of: datetime
    nav: Money
    cash: Money
    gross_exposure: Money
    cash_pct: Decimal
    largest_position_pct: Decimal
    position_count: int
    daily_turnover: Money
    orders_today: int
    filled_orders_today: int
    policy_version: str

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")
        require_aware(self.as_of, "as_of")
        if self.nav.amount <= 0 or self.cash.amount < 0 or self.gross_exposure.amount < 0:
            raise ValueError("risk snapshot amounts violate cash-account invariants")
        if not Decimal("0") <= self.cash_pct <= Decimal("1"):
            raise ValueError("cash_pct must be within [0, 1]")
        if not Decimal("0") <= self.largest_position_pct <= Decimal("1"):
            raise ValueError("largest_position_pct must be within [0, 1]")
        if self.position_count < 0 or self.orders_today < 0 or self.filled_orders_today < 0:
            raise ValueError("risk snapshot counters must not be negative")
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be empty")


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    order: Order
    eligibility: TradingEligibility
    risk_decision: RiskDecision
    fill: Fill | None
    cash_entries: tuple[CashLedgerEntry, ...]
    settlement_position: SettlementPosition | None
    settlement_event: SettlementRolloverEvent | None
    risk_snapshot: RiskSnapshot | None
    policy_versions: ExecutionPolicyVersions
    audit_events: tuple[AuditEvent, ...]
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.order.status.value not in {"FILLED", "REJECTED"}:
            raise ValueError("execution outcome requires a terminal order")
        if self.risk_decision.decision is RiskDecisionType.REJECT:
            if self.order.status.value != "REJECTED" or self.fill is not None:
                raise ValueError("rejected outcome must contain a rejected order and no fill")
        elif self.order.status.value != "FILLED" or self.fill is None:
            raise ValueError("allowed outcome must contain a filled order and fill")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
