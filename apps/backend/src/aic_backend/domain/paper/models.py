"""Immutable forward paper-trading domain models and state transitions."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from aic_backend.domain.execution import ExecutionOutcome, SettlementPosition
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import (
    CashLedgerEntry,
    Fill,
    Money,
    OrderSide,
    PortfolioId,
    PortfolioSnapshot,
    Position,
    PositionSnapshot,
    Price,
    Quantity,
)


def require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value


class PaperMode(StrEnum):
    FORWARD_PAPER = "FORWARD_PAPER"


class CapitalMode(StrEnum):
    CONTINUOUS_COMPOUNDING = "CONTINUOUS_COMPOUNDING"


class PaperAccountStatus(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class PaperSessionStatus(StrEnum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    PROCESSING = "PROCESSING"
    MARKING = "MARKING"
    BLOCKED = "BLOCKED"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"


class ExecutionTiming(StrEnum):
    NEXT_OPEN = "NEXT_OPEN"


class OperationalStatus(StrEnum):
    IDLE = "IDLE"
    READY = "READY"
    WAITING_FOR_MARKET_DATA = "WAITING_FOR_MARKET_DATA"
    PROCESSING_ORDERS = "PROCESSING_ORDERS"
    RISK_CHECKING = "RISK_CHECKING"
    MARKING_TO_MARKET = "MARKING_TO_MARKET"
    FINALIZING = "FINALIZING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class MetricSampleStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


class PaperProcessingCheckpoint(StrEnum):
    AFTER_RISK_BEFORE_FILL = "AFTER_RISK_BEFORE_FILL"
    AFTER_FILL_BEFORE_ACCOUNTING = "AFTER_FILL_BEFORE_ACCOUNTING"
    AFTER_ACCOUNTING_BEFORE_SNAPSHOT = "AFTER_ACCOUNTING_BEFORE_SNAPSHOT"
    AFTER_SNAPSHOT_BEFORE_FINALIZATION = "AFTER_SNAPSHOT_BEFORE_FINALIZATION"


class PaperErrorCode(StrEnum):
    ACCOUNT_NOT_FOUND = "PAPER_ACCOUNT_NOT_FOUND"
    INVALID_ACCOUNT_STATE = "INVALID_ACCOUNT_STATE"
    INVALID_SESSION_STATE = "INVALID_SESSION_STATE"
    INVALID_ORDER_TIMING = "INVALID_ORDER_TIMING"
    FORWARD_ONLY_VIOLATION = "FORWARD_ONLY_VIOLATION"
    PIT_DATA_UNAVAILABLE = "PIT_DATA_UNAVAILABLE"
    MARK_DATA_UNAVAILABLE = "MARK_DATA_UNAVAILABLE"
    SESSION_FINALIZATION_BLOCKED = "SESSION_FINALIZATION_BLOCKED"
    UNSUPPORTED_CORPORATE_ACTION = "UNSUPPORTED_CORPORATE_ACTION"
    READINESS_FAILED = "READINESS_FAILED"
    STATE_INCONSISTENCY = "STATE_INCONSISTENCY"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    INJECTED_CRASH = "INJECTED_CRASH"


class PaperRuntimeError(RuntimeError):
    def __init__(self, code: PaperErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


_ACCOUNT_TRANSITIONS = {
    PaperAccountStatus.CREATED: frozenset({PaperAccountStatus.READY}),
    PaperAccountStatus.READY: frozenset({PaperAccountStatus.RUNNING, PaperAccountStatus.CLOSED}),
    PaperAccountStatus.RUNNING: frozenset(
        {PaperAccountStatus.PAUSED, PaperAccountStatus.STOPPED, PaperAccountStatus.ERROR}
    ),
    PaperAccountStatus.PAUSED: frozenset(
        {
            PaperAccountStatus.RUNNING,
            PaperAccountStatus.STOPPED,
            PaperAccountStatus.CLOSED,
            PaperAccountStatus.ERROR,
        }
    ),
    PaperAccountStatus.STOPPED: frozenset({PaperAccountStatus.CLOSED}),
    PaperAccountStatus.ERROR: frozenset(
        {PaperAccountStatus.PAUSED, PaperAccountStatus.STOPPED, PaperAccountStatus.CLOSED}
    ),
    PaperAccountStatus.CLOSED: frozenset(),
}

_SESSION_TRANSITIONS = {
    PaperSessionStatus.PLANNED: frozenset(
        {PaperSessionStatus.OPEN, PaperSessionStatus.BLOCKED, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.OPEN: frozenset(
        {PaperSessionStatus.PROCESSING, PaperSessionStatus.BLOCKED, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.PROCESSING: frozenset(
        {PaperSessionStatus.MARKING, PaperSessionStatus.BLOCKED, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.MARKING: frozenset(
        {PaperSessionStatus.FINALIZED, PaperSessionStatus.BLOCKED, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.BLOCKED: frozenset(
        {PaperSessionStatus.PROCESSING, PaperSessionStatus.FAILED}
    ),
    PaperSessionStatus.FINALIZED: frozenset(),
    PaperSessionStatus.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class PaperAccount:
    account_id: str
    portfolio_id: PortfolioId
    display_name: str
    initial_capital: Money
    mode: PaperMode
    capital_mode: CapitalMode
    status: PaperAccountStatus
    created_at: datetime
    updated_at: datetime
    last_finalized_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", require_text(self.account_id, "account_id"))
        object.__setattr__(self, "display_name", require_text(self.display_name, "display_name"))
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.initial_capital.amount <= 0:
            raise ValueError("initial_capital must be positive")

    def transition(self, status: PaperAccountStatus, occurred_at: datetime) -> "PaperAccount":
        require_aware(occurred_at, "occurred_at")
        if status not in _ACCOUNT_TRANSITIONS[self.status]:
            raise PaperRuntimeError(
                PaperErrorCode.INVALID_ACCOUNT_STATE,
                f"invalid account transition: {self.status.value} -> {status.value}",
            )
        return replace(self, status=status, updated_at=occurred_at)

    def finalize(self, trading_date: date, occurred_at: datetime) -> "PaperAccount":
        if self.last_finalized_date is not None and trading_date <= self.last_finalized_date:
            raise PaperRuntimeError(
                PaperErrorCode.FORWARD_ONLY_VIOLATION,
                "paper account cannot move backward or rewrite finalized history",
            )
        return replace(self, last_finalized_date=trading_date, updated_at=occurred_at)


@dataclass(frozen=True, slots=True)
class PaperSession:
    session_id: str
    account_id: str
    trading_date: date
    status: PaperSessionStatus
    planned_at: datetime
    started_at: datetime | None
    finalized_at: datetime | None
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", require_text(self.session_id, "session_id"))
        object.__setattr__(self, "account_id", require_text(self.account_id, "account_id"))
        object.__setattr__(
            self, "policy_version", require_text(self.policy_version, "policy_version")
        )
        require_aware(self.planned_at, "planned_at")
        if self.started_at is not None:
            require_aware(self.started_at, "started_at")
        if self.finalized_at is not None:
            require_aware(self.finalized_at, "finalized_at")
        if self.status is PaperSessionStatus.FINALIZED and self.finalized_at is None:
            raise ValueError("finalized session requires finalized_at")

    def transition(self, status: PaperSessionStatus, occurred_at: datetime) -> "PaperSession":
        require_aware(occurred_at, "occurred_at")
        if status not in _SESSION_TRANSITIONS[self.status]:
            raise PaperRuntimeError(
                PaperErrorCode.INVALID_SESSION_STATE,
                f"invalid session transition: {self.status.value} -> {status.value}",
            )
        return replace(
            self,
            status=status,
            started_at=occurred_at if status is PaperSessionStatus.OPEN else self.started_at,
            finalized_at=(
                occurred_at if status is PaperSessionStatus.FINALIZED else self.finalized_at
            ),
        )


@dataclass(frozen=True, slots=True)
class PaperOrderIntent:
    intent_id: str
    account_id: str
    submitted_at: datetime
    effective_trading_date: date
    instrument: InstrumentIdentity
    side: OrderSide
    quantity: Quantity
    source_reference: str
    timing: ExecutionTiming = ExecutionTiming.NEXT_OPEN
    requested_price: Price | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_id", require_text(self.intent_id, "intent_id"))
        object.__setattr__(self, "account_id", require_text(self.account_id, "account_id"))
        object.__setattr__(
            self,
            "source_reference",
            require_text(self.source_reference, "source_reference"),
        )
        require_aware(self.submitted_at, "submitted_at")


@dataclass(frozen=True, slots=True)
class PaperStateEvent:
    event_id: str
    account_id: str
    occurred_at: datetime
    event_type: str
    source_id: str
    operational_status: OperationalStatus
    session_id: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    payload: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", require_text(self.event_id, "event_id"))
        object.__setattr__(self, "account_id", require_text(self.account_id, "account_id"))
        object.__setattr__(self, "event_type", require_text(self.event_type, "event_type"))
        object.__setattr__(self, "source_id", require_text(self.source_id, "source_id"))
        require_aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class PaperPortfolioState:
    cash: Money
    positions: tuple[Position, ...]
    cash_ledger: tuple[CashLedgerEntry, ...]
    settlement_positions: tuple[SettlementPosition, ...]
    last_snapshot: PortfolioSnapshot
    last_trading_date: date | None
    activity_date: date | None = None
    orders_today: int = 0
    filled_orders_today: int = 0
    daily_turnover: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.cash.amount < 0:
            raise ValueError("cash must not be negative")
        if self.last_snapshot.cash != self.cash:
            raise ValueError("portfolio state cash must match the last snapshot")
        if min(self.orders_today, self.filled_orders_today) < 0 or self.daily_turnover < 0:
            raise ValueError("portfolio activity counters must not be negative")


@dataclass(frozen=True, slots=True)
class PaperPerformanceConfig:
    annualization_days: int = 252
    risk_free_rate: Decimal = Decimal("0")
    minimum_ratio_samples: int = 20
    minimum_cagr_days: int = 365
    version: str = "paper-performance/v1"

    def __post_init__(self) -> None:
        if self.annualization_days <= 0 or self.minimum_ratio_samples <= 1:
            raise ValueError("performance sample conventions must be positive")
        if self.minimum_cagr_days <= 0:
            raise ValueError("minimum_cagr_days must be positive")
        require_text(self.version, "performance version")


@dataclass(frozen=True, slots=True)
class PaperPerformanceSnapshot:
    snapshot_id: str
    account_id: str
    session_id: str
    trading_date: date
    as_of: datetime
    cash: Money
    market_value: Money
    realized_pnl: Money
    unrealized_pnl: Money
    nav: Money
    gross_pnl: Money
    net_pnl: Money
    gross_exposure: Money
    cash_pct: Decimal
    largest_position_pct: Decimal
    position_count: int
    benchmark_value: Decimal
    daily_return: Decimal
    cumulative_return: Decimal
    peak_nav: Money
    current_drawdown: Decimal
    max_drawdown: Decimal
    total_return: Decimal
    cagr: Decimal | None
    annualized_volatility: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    calmar: Decimal | None
    benchmark_return: Decimal
    excess_return: Decimal
    turnover: Decimal
    fee_total: Money
    tax_total: Money
    slippage_total: Money
    fill_count: int
    sample_status: MetricSampleStatus
    policy_version: str
    positions: tuple[PositionSnapshot, ...]

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "account_id", "session_id", "policy_version"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        require_aware(self.as_of, "as_of")
        if self.nav.amount <= 0 or self.cash.amount < 0 or self.market_value.amount < 0:
            raise ValueError("performance amounts violate cash-account invariants")
        if not Decimal("0") <= self.cash_pct <= Decimal("1"):
            raise ValueError("cash_pct must be within [0, 1]")
        if not Decimal("0") <= self.largest_position_pct <= Decimal("1"):
            raise ValueError("largest_position_pct must be within [0, 1]")
        if self.position_count < 0 or self.fill_count < 0:
            raise ValueError("performance counters must not be negative")


@dataclass(frozen=True, slots=True)
class TradeEpisode:
    episode_id: str
    account_id: str
    instrument: InstrumentIdentity
    opened_at: datetime
    closed_at: datetime
    entry_cost: Money
    exit_proceeds: Money
    net_pnl: Money
    return_value: Decimal
    holding_trading_days: int
    source_fill_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "episode_id", require_text(self.episode_id, "episode_id"))
        object.__setattr__(self, "account_id", require_text(self.account_id, "account_id"))
        require_aware(self.opened_at, "opened_at")
        require_aware(self.closed_at, "closed_at")
        if self.closed_at < self.opened_at or self.holding_trading_days < 0:
            raise ValueError("trade episode timestamps are invalid")
        if not self.source_fill_ids:
            raise ValueError("trade episode requires source fills")


@dataclass(frozen=True, slots=True)
class PaperSessionResult:
    session: PaperSession
    intents: tuple[PaperOrderIntent, ...]
    outcomes: tuple[ExecutionOutcome, ...]
    performance: PaperPerformanceSnapshot
    new_episodes: tuple[TradeEpisode, ...]
    events: tuple[PaperStateEvent, ...]


@dataclass(frozen=True, slots=True)
class ActivatePaperAccount:
    account_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", require_text(self.account_id, "account_id"))
        require_aware(self.requested_at, "requested_at")


def filled_values(outcomes: tuple[ExecutionOutcome, ...]) -> tuple[Fill, ...]:
    return tuple(outcome.fill for outcome in outcomes if outcome.fill is not None)
