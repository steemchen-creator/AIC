"""Pure domain model for governed, point-in-time Trade Plans."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.models import PortfolioId, Quantity


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, f"{field} must not be empty")
    return normalized


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TradePlanError(
            TradePlanErrorCode.INVALID_TIMESTAMP,
            f"{field} must include timezone information",
        )
    return value.astimezone(UTC)


class InvestmentHorizon(StrEnum):
    T = "T"
    SHORT = "SHORT"
    MEDIUM_SHORT = "MEDIUM_SHORT"
    MEDIUM = "MEDIUM"
    MEDIUM_LONG = "MEDIUM_LONG"
    LONG = "LONG"


class TradingStyle(StrEnum):
    SWING = "SWING"
    TREND = "TREND"
    VALUE = "VALUE"
    EVENT = "EVENT"
    INDEX = "INDEX"
    MEAN_REVERSION = "MEAN_REVERSION"
    OTHER = "OTHER"


class TradePlanStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class DirectiveType(StrEnum):
    ENTRY = "ENTRY"
    SCALE_IN = "SCALE_IN"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class TriggerType(StrEnum):
    MANUAL = "MANUAL"
    HARD_STOP = "HARD_STOP"
    PROFIT_TARGET = "PROFIT_TARGET"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"
    THESIS_INVALIDATION = "THESIS_INVALIDATION"
    EXPIRY = "EXPIRY"
    NO_TRIGGER = "NO_TRIGGER"


class TradePlanErrorCode(StrEnum):
    INVALID_FIELD = "TRADE_PLAN_INVALID_FIELD"
    INVALID_TIMESTAMP = "TRADE_PLAN_INVALID_TIMESTAMP"
    INVALID_TRANSITION = "TRADE_PLAN_INVALID_TRANSITION"
    PLAN_NOT_FOUND = "TRADE_PLAN_NOT_FOUND"
    DUPLICATE_ACTIVE_PLAN = "TRADE_PLAN_DUPLICATE_ACTIVE"
    PROTECTED_FIELD_MUTATION = "TRADE_PLAN_PROTECTED_FIELD_MUTATION"
    STALE_VERSION = "TRADE_PLAN_STALE_VERSION"
    TERMINAL_IMMUTABLE = "TRADE_PLAN_TERMINAL_IMMUTABLE"
    NON_TRADABLE_INDEX = "TRADE_PLAN_NON_TRADABLE_INDEX"
    UNSUPPORTED_INSTRUMENT = "TRADE_PLAN_UNSUPPORTED_INSTRUMENT"
    FUTURE_EVIDENCE = "TRADE_PLAN_FUTURE_EVIDENCE"
    EXECUTION_TOO_EARLY = "TRADE_PLAN_EXECUTION_TOO_EARLY"
    DIRECTIVE_NOT_EXECUTABLE = "TRADE_PLAN_DIRECTIVE_NOT_EXECUTABLE"
    DIRECTIVE_CONFLICT = "TRADE_PLAN_DIRECTIVE_CONFLICT"
    EXECUTION_REJECTED = "TRADE_PLAN_EXECUTION_REJECTED"
    POSITION_SEMANTICS = "TRADE_PLAN_POSITION_SEMANTICS"
    OUTCOME_PENDING = "TRADE_PLAN_OUTCOME_PENDING"


class TradePlanError(ValueError):
    def __init__(self, code: TradePlanErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_investment_horizon(value: str) -> InvestmentHorizon:
    try:
        return InvestmentHorizon(value)
    except ValueError as error:
        raise TradePlanError(
            TradePlanErrorCode.INVALID_FIELD, f"unknown investment horizon: {value}"
        ) from error


def parse_trading_style(value: str) -> TradingStyle:
    try:
        return TradingStyle(value)
    except ValueError as error:
        raise TradePlanError(
            TradePlanErrorCode.INVALID_FIELD, f"unknown trading style: {value}"
        ) from error


@dataclass(frozen=True, slots=True)
class TradePlanId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _text(self.value, "plan_id"))


@dataclass(frozen=True, slots=True)
class HardStopPolicy:
    price: Decimal
    action: DirectiveType = DirectiveType.EXIT
    quantity: Quantity | None = None

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "hard stop must be positive")
        if self.action not in (DirectiveType.REDUCE, DirectiveType.EXIT):
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "invalid hard-stop action")
        if self.action is DirectiveType.REDUCE and self.quantity is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "REDUCE hard stop requires quantity"
            )
        if self.action is DirectiveType.EXIT and self.quantity is not None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "EXIT hard stop must not specify quantity"
            )


@dataclass(frozen=True, slots=True)
class ProfitTarget:
    price: Decimal
    action: DirectiveType
    quantity: Quantity | None = None

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "profit target must be positive")
        if self.action not in (DirectiveType.REDUCE, DirectiveType.EXIT):
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "invalid profit-target action")
        if self.action is DirectiveType.REDUCE and self.quantity is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "REDUCE target requires quantity"
            )
        if self.action is DirectiveType.EXIT and self.quantity is not None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "EXIT target must not specify quantity"
            )


@dataclass(frozen=True, slots=True)
class TrailingStopPolicy:
    distance_pct: Decimal
    action: DirectiveType = DirectiveType.EXIT
    quantity: Quantity | None = None

    def __post_init__(self) -> None:
        if not Decimal("0") < self.distance_pct < Decimal("1"):
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD,
                "trailing distance must be within (0, 1)",
            )
        if self.action not in (DirectiveType.REDUCE, DirectiveType.EXIT):
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "invalid trailing-stop action")
        if self.action is DirectiveType.REDUCE and self.quantity is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "REDUCE trailing stop requires quantity"
            )
        if self.action is DirectiveType.EXIT and self.quantity is not None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD,
                "EXIT trailing stop must not specify quantity",
            )


@dataclass(frozen=True, slots=True)
class TimeStopPolicy:
    deadline: datetime
    action: DirectiveType = DirectiveType.EXIT
    quantity: Quantity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "deadline", _aware(self.deadline, "time_stop.deadline"))
        if self.action not in (DirectiveType.REDUCE, DirectiveType.EXIT):
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "invalid time-stop action")
        if self.action is DirectiveType.REDUCE and self.quantity is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "REDUCE time stop requires quantity"
            )
        if self.action is DirectiveType.EXIT and self.quantity is not None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD,
                "EXIT time stop must not specify quantity",
            )


@dataclass(frozen=True, slots=True)
class TradePlan:
    plan_id: TradePlanId
    portfolio_id: PortfolioId
    instrument: InstrumentIdentity
    horizon: InvestmentHorizon
    style: TradingStyle
    thesis: str
    target_quantity: Quantity
    created_at: datetime
    updated_at: datetime
    status: TradePlanStatus = TradePlanStatus.DRAFT
    activated_at: datetime | None = None
    terminal_at: datetime | None = None
    expiry_at: datetime | None = None
    thesis_invalidation_reference: str | None = None
    hard_stop: HardStopPolicy | None = None
    profit_targets: tuple[ProfitTarget, ...] = ()
    trailing_stop: TrailingStopPolicy | None = None
    time_stop: TimeStopPolicy | None = None
    version: int = 0
    policy_version: str = "trade-plan/v1"
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "thesis", _text(self.thesis, "thesis"))
        object.__setattr__(self, "policy_version", _text(self.policy_version, "policy_version"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _aware(self.updated_at, "updated_at"))
        if self.expiry_at is not None:
            object.__setattr__(self, "expiry_at", _aware(self.expiry_at, "expiry_at"))
        if self.activated_at is not None:
            object.__setattr__(self, "activated_at", _aware(self.activated_at, "activated_at"))
        if self.terminal_at is not None:
            object.__setattr__(self, "terminal_at", _aware(self.terminal_at, "terminal_at"))
        if self.thesis_invalidation_reference is not None:
            object.__setattr__(
                self,
                "thesis_invalidation_reference",
                _text(self.thesis_invalidation_reference, "thesis_invalidation_reference"),
            )
        if self.instrument.instrument_type is InstrumentType.INDEX:
            raise TradePlanError(
                TradePlanErrorCode.NON_TRADABLE_INDEX, "Index references are not executable"
            )
        if self.instrument.instrument_type not in (InstrumentType.EQUITY, InstrumentType.ETF):
            raise TradePlanError(
                TradePlanErrorCode.UNSUPPORTED_INSTRUMENT, "unsupported Trade Plan instrument"
            )
        if self.instrument.market not in (Market.CN_SSE, Market.CN_SZSE):
            raise TradePlanError(
                TradePlanErrorCode.UNSUPPORTED_INSTRUMENT,
                "V1 Trade Plans support CN-listed instruments only",
            )
        if tuple(sorted(self.profit_targets, key=lambda item: item.price)) != self.profit_targets:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "profit targets must be ordered by price"
            )
        if self.expiry_at is not None and self.expiry_at <= self.created_at:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "expiry must follow creation")
        if self.updated_at < self.created_at:
            raise TradePlanError(TradePlanErrorCode.INVALID_TIMESTAMP, "updated_at is stale")
        if self.time_stop is not None and self.time_stop.deadline <= self.created_at:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "time stop must follow creation")
        if self.status is TradePlanStatus.DRAFT and self.version != 0:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "draft version must be zero")
        if self.status is not TradePlanStatus.DRAFT and self.version < 1:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "activated plan needs a version")

    def activate(self, at: datetime) -> "TradePlan":
        if self.status is not TradePlanStatus.DRAFT:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_TRANSITION, "only a draft plan can activate"
            )
        at = _aware(at, "activated_at")
        if at < self.created_at or (self.expiry_at is not None and at >= self.expiry_at):
            raise TradePlanError(TradePlanErrorCode.INVALID_TIMESTAMP, "invalid activation time")
        return replace(
            self,
            status=TradePlanStatus.ACTIVE,
            activated_at=at,
            updated_at=at,
            version=1,
        )

    def transition(self, status: TradePlanStatus, at: datetime, reason: str) -> "TradePlan":
        allowed = {
            TradePlanStatus.DRAFT: {TradePlanStatus.CANCELLED},
            TradePlanStatus.ACTIVE: {
                TradePlanStatus.COMPLETED,
                TradePlanStatus.CANCELLED,
                TradePlanStatus.EXPIRED,
                TradePlanStatus.INVALIDATED,
            },
        }
        if status not in allowed.get(self.status, set()):
            raise TradePlanError(
                TradePlanErrorCode.INVALID_TRANSITION,
                f"invalid plan transition: {self.status.value} -> {status.value}",
            )
        at = _aware(at, "terminal_at")
        if at < self.updated_at:
            raise TradePlanError(TradePlanErrorCode.INVALID_TIMESTAMP, "terminal time is stale")
        return replace(
            self,
            status=status,
            updated_at=at,
            terminal_at=at,
            terminal_reason=_text(reason, "terminal_reason"),
        )


@dataclass(frozen=True, slots=True)
class TradePlanRevision:
    plan_id: TradePlanId
    version: int
    effective_at: datetime
    recorded_at: datetime
    reason: str
    actor: str
    source: str
    thesis: str
    target_quantity: Quantity
    expiry_at: datetime | None
    policy_version: str
    horizon: InvestmentHorizon
    style: TradingStyle
    hard_stop: HardStopPolicy | None
    profit_targets: tuple[ProfitTarget, ...]
    trailing_stop: TrailingStopPolicy | None
    time_stop: TimeStopPolicy | None
    thesis_invalidation_reference: str | None
    trailing_high_water: Decimal | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "revision version must be positive"
            )
        object.__setattr__(self, "effective_at", _aware(self.effective_at, "effective_at"))
        object.__setattr__(self, "recorded_at", _aware(self.recorded_at, "recorded_at"))
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "actor", _text(self.actor, "actor"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "thesis", _text(self.thesis, "thesis"))
        object.__setattr__(self, "policy_version", _text(self.policy_version, "policy_version"))
        if self.expiry_at is not None:
            object.__setattr__(self, "expiry_at", _aware(self.expiry_at, "expiry_at"))
        if self.effective_at > self.recorded_at:
            raise TradePlanError(TradePlanErrorCode.FUTURE_EVIDENCE, "future revision is invalid")
        if self.trailing_high_water is not None and self.trailing_high_water <= 0:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "high-water must be positive")


@dataclass(frozen=True, slots=True)
class PlanObservation:
    observation_id: str
    event_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _text(self.observation_id, "observation_id"))
        object.__setattr__(self, "event_at", _aware(self.event_at, "event_at"))
        object.__setattr__(self, "available_at", _aware(self.available_at, "available_at"))
        if any(value <= 0 for value in (self.open, self.high, self.low, self.close)):
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "prices must be positive")
        if self.low > min(self.open, self.close, self.high) or self.high < max(
            self.open, self.close, self.low
        ):
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "OHLC ordering is invalid")


@dataclass(frozen=True, slots=True)
class TradePlanDirective:
    directive_id: str
    plan_id: TradePlanId
    plan_version: int
    directive_type: DirectiveType
    quantity: Quantity | None
    trigger: TriggerType
    decision_as_of: datetime
    not_before: datetime | None
    observation_id: str | None
    created_at: datetime
    trigger_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "directive_id", _text(self.directive_id, "directive_id"))
        object.__setattr__(self, "decision_as_of", _aware(self.decision_as_of, "decision_as_of"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if self.plan_version < 1:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "directive needs a revision")
        if self.directive_type is DirectiveType.HOLD:
            if self.quantity is not None or self.not_before is not None:
                raise TradePlanError(
                    TradePlanErrorCode.INVALID_FIELD, "HOLD must not create executable quantity"
                )
        elif self.directive_type is DirectiveType.EXIT:
            if self.quantity is not None:
                raise TradePlanError(
                    TradePlanErrorCode.INVALID_FIELD, "EXIT resolves quantity at execution"
                )
            if self.not_before is None:
                raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "execution time is required")
        elif self.quantity is None or self.not_before is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "executable directive requires quantity and time"
            )
        if self.not_before is not None:
            object.__setattr__(self, "not_before", _aware(self.not_before, "not_before"))
            if self.not_before <= self.decision_as_of:
                raise TradePlanError(
                    TradePlanErrorCode.EXECUTION_TOO_EARLY,
                    "daily decision must execute after its decision time",
                )


@dataclass(frozen=True, slots=True)
class PlanExecutionEvidence:
    evidence_id: str
    plan_id: TradePlanId
    plan_version: int
    directive_id: str
    directive_type: DirectiveType
    order_id: str
    fill_id: str | None
    executed_at: datetime
    rejected_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("evidence_id", "directive_id", "order_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "executed_at", _aware(self.executed_at, "executed_at"))
        if (self.fill_id is None) == (not self.rejected_reason_codes):
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD,
                "execution evidence must contain either fill or rejection",
            )


@dataclass(frozen=True, slots=True)
class TradePlanOutcome:
    outcome_id: str
    plan_id: TradePlanId
    portfolio_id: PortfolioId
    instrument: InstrumentIdentity
    horizon: InvestmentHorizon
    style: TradingStyle
    activated_at: datetime
    terminal_at: datetime
    terminal_reason: str
    average_entry_price: Decimal | None
    remaining_quantity: Decimal
    realized_pnl: Decimal
    holding_seconds: int
    stop_triggered: bool
    target_triggered: bool
    expired: bool
    thesis_invalidated: bool
    scale_in_count: int
    reduction_count: int
    rejected_count: int
    adhered: bool
    revision_count: int
    source_execution_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome_id", _text(self.outcome_id, "outcome_id"))
        object.__setattr__(self, "activated_at", _aware(self.activated_at, "activated_at"))
        object.__setattr__(self, "terminal_at", _aware(self.terminal_at, "terminal_at"))
        object.__setattr__(self, "terminal_reason", _text(self.terminal_reason, "terminal_reason"))
        if self.terminal_at < self.activated_at or self.remaining_quantity < 0:
            raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "invalid outcome values")
        if self.average_entry_price is not None and self.average_entry_price <= 0:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "average entry price must be positive"
            )


def stable_plan_id(*parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return sha256(value.encode("utf-8")).hexdigest()
