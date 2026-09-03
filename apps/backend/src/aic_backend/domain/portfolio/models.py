"""Provider- and infrastructure-neutral portfolio accounting models."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from aic_backend.domain.market_data import InstrumentIdentity


def _text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value


@dataclass(frozen=True, slots=True)
class PortfolioId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _text(self.value, "portfolio_id"))


@dataclass(frozen=True, slots=True)
class BacktestRunId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _text(self.value, "run_id"))


@dataclass(frozen=True, slots=True)
class OrderId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _text(self.value, "order_id"))


@dataclass(frozen=True, slots=True)
class FillId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _text(self.value, "fill_id"))


@dataclass(frozen=True, slots=True)
class PositionKey:
    portfolio_id: PortfolioId
    instrument: InstrumentIdentity

    @property
    def value(self) -> str:
        return f"{self.portfolio_id.value}:{self.instrument.canonical_key}"


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "CNY"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("money amount must be Decimal")
        object.__setattr__(self, "currency", _text(self.currency, "currency").upper())
        if self.currency != "CNY":
            raise ValueError("V1 supports CNY only")


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("quantity must be Decimal")
        if self.value <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class Price:
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("price must be Decimal")
        if self.value <= 0:
            raise ValueError("price must be positive")


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class CashEntryType(StrEnum):
    INITIAL_CAPITAL = "INITIAL_CAPITAL"
    BUY_SETTLEMENT = "BUY_SETTLEMENT"
    SELL_SETTLEMENT = "SELL_SETTLEMENT"
    FEE = "FEE"
    TAX = "TAX"
    ADJUSTMENT = "ADJUSTMENT"


class BacktestStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BacktestErrorCode(StrEnum):
    INVALID_ORDER = "INVALID_ORDER"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
    PIT_DATA_UNAVAILABLE = "PIT_DATA_UNAVAILABLE"
    UNSUPPORTED_INSTRUMENT = "UNSUPPORTED_INSTRUMENT"
    INVALID_PRICE = "INVALID_PRICE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    REPLAY_FAILURE = "REPLAY_FAILURE"
    POLICY_FAILURE = "POLICY_FAILURE"


class PortfolioError(ValueError):
    def __init__(self, code: BacktestErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


_TRANSITIONS = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.ACCEPTED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    ),
    OrderStatus.ACCEPTED: frozenset(
        {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Order:
    order_id: OrderId
    portfolio_id: PortfolioId
    instrument: InstrumentIdentity
    side: OrderSide
    quantity: Quantity
    order_type: OrderType
    requested_price: Price | None
    created_at: datetime
    status: OrderStatus = OrderStatus.CREATED

    def __post_init__(self) -> None:
        _aware(self.created_at, "created_at")
        if self.order_type is OrderType.LIMIT and self.requested_price is None:
            raise PortfolioError(BacktestErrorCode.INVALID_PRICE, "limit order requires price")

    def transition(self, status: OrderStatus) -> "Order":
        if status not in _TRANSITIONS[self.status]:
            raise PortfolioError(
                BacktestErrorCode.INVALID_ORDER,
                f"invalid order transition: {self.status.value} -> {status.value}",
            )
        return replace(self, status=status)


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: FillId
    order_id: OrderId
    portfolio_id: PortfolioId
    instrument: InstrumentIdentity
    side: OrderSide
    quantity: Quantity
    fill_price: Price
    executed_at: datetime
    fee: Money
    tax: Money
    slippage: Money
    policy_version: str

    def __post_init__(self) -> None:
        _aware(self.executed_at, "executed_at")
        object.__setattr__(self, "policy_version", _text(self.policy_version, "policy_version"))
        if any(value.amount < 0 for value in (self.fee, self.tax, self.slippage)):
            raise ValueError("fill costs must not be negative")


@dataclass(frozen=True, slots=True)
class CashLedgerEntry:
    entry_id: str
    portfolio_id: PortfolioId
    occurred_at: datetime
    entry_type: CashEntryType
    amount: Money
    balance_after: Money
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _text(self.entry_id, "entry_id"))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        _aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class Position:
    key: PositionKey
    quantity: Decimal
    average_cost: Decimal
    realized_pnl: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.quantity < 0 or self.average_cost < 0:
            raise ValueError("position quantity and average cost must not be negative")


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    instrument: InstrumentIdentity
    quantity: Decimal
    average_cost: Decimal
    mark_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    portfolio_id: PortfolioId
    as_of: datetime
    cash: Money
    positions: tuple[PositionSnapshot, ...]
    market_value: Money
    realized_pnl: Money
    unrealized_pnl: Money
    nav: Money

    def __post_init__(self) -> None:
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    timestamp: datetime
    event_type: str
    source_id: str
    portfolio_id: PortfolioId
    payload: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _text(self.event_id, "event_id"))
        object.__setattr__(self, "event_type", _text(self.event_type, "event_type"))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        _aware(self.timestamp, "timestamp")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class BacktestRun:
    run_id: BacktestRunId
    portfolio_id: PortfolioId
    start: datetime
    end: datetime
    initial_capital: Money
    data_policy_version: str
    fee_policy_version: str
    slippage_policy_version: str
    execution_policy_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("start", "end", "created_at"):
            _aware(getattr(self, name), name)
        if self.end < self.start:
            raise ValueError("backtest end must not precede start")
        if self.initial_capital.amount <= 0:
            raise ValueError("initial capital must be positive")


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    instrument: InstrumentIdentity
    start_value: Decimal
    end_value: Decimal
    benchmark_return: Decimal


@dataclass(frozen=True, slots=True)
class BacktestResult:
    run_id: BacktestRunId
    initial_capital: Money
    final_nav: Money
    gross_result: Money
    fee_total: Money
    tax_total: Money
    slippage_total: Money
    net_result: Money
    total_return: Decimal
    realized_pnl: Money
    unrealized_pnl: Money
    trade_count: int
    benchmark_return: Decimal
    excess_return: Decimal
    status: BacktestStatus
    warnings: tuple[str, ...] = field(default_factory=tuple)
