"""Immutable models for fair Champion and Shadow portfolio experiments."""

import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from aic_backend.domain.paper import PaperPerformanceSnapshot
from aic_backend.domain.portfolio.models import Money, PortfolioId


def _text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value


def _avatar_reference(value: str) -> str:
    normalized = _text(value, "avatar_reference")
    if len(normalized) > 512 or any(ord(character) < 32 for character in normalized):
        raise ValueError("avatar_reference must be a safe reference of at most 512 characters")
    return normalized


def stable_experiment_id(prefix: str, *parts: object) -> str:
    material = "|".join((prefix, *(str(part) for part in parts)))
    return f"{prefix}-{sha256(material.encode('utf-8')).hexdigest()[:32]}"


class PortfolioRole(StrEnum):
    CHAMPION = "CHAMPION"
    SHADOW = "SHADOW"


class RoleIdentity(StrEnum):
    CHAMPION = "CHAMPION"
    ATLAS = "ATLAS"
    SAGE = "SAGE"
    FLUX = "FLUX"
    PULSE = "PULSE"
    AEGIS = "AEGIS"
    HORIZON = "HORIZON"


class DecisionSourceKind(StrEnum):
    SCRIPTED = "SCRIPTED"
    MANUAL = "MANUAL"
    FIXTURE = "FIXTURE"


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


class RoleActivityStatus(StrEnum):
    IDLE = "IDLE"
    READY = "READY"
    PROCESSING = "PROCESSING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class ComparisonSampleStatus(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    PROVISIONAL = "PROVISIONAL"
    QUALIFIED = "QUALIFIED"


class MemberSessionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class GroupSessionStatus(StrEnum):
    FINALIZED = "FINALIZED"
    FINALIZED_WITH_FAILURES = "FINALIZED_WITH_FAILURES"
    SKIPPED = "SKIPPED"


class AssetClass(StrEnum):
    CASH = "CASH"
    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"
    FUTURE = "FUTURE"


class MarketVenue(StrEnum):
    CN_SSE = "CN.SSE"
    CN_SZSE = "CN.SZSE"
    US_NASDAQ = "US.NASDAQ"
    US_NYSE = "US.NYSE"
    GLOBAL = "GLOBAL"


class Currency(StrEnum):
    CNY = "CNY"
    USD = "USD"
    HKD = "HKD"
    EUR = "EUR"
    JPY = "JPY"
    GBP = "GBP"


@dataclass(frozen=True, slots=True)
class AssetUniverse:
    asset_classes: tuple[AssetClass, ...]
    market_venues: tuple[MarketVenue, ...]
    currencies: tuple[Currency, ...]
    base_currency: Currency

    def __post_init__(self) -> None:
        if not self.asset_classes or not self.market_venues or not self.currencies:
            raise ValueError("asset universe dimensions must not be empty")
        if self.base_currency not in self.currencies:
            raise ValueError("base currency must be part of the asset universe")
        for field_name in ("asset_classes", "market_venues", "currencies"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ExperimentPolicyBundle:
    pit_policy_version: str
    calendar_policy_version: str
    execution_policy_version: str
    risk_policy_version: str
    fee_policy_version: str
    slippage_policy_version: str
    benchmark_key: str
    initial_capital: Money
    start_date: date
    experiment_policy_version: str
    comparison_policy_version: str
    asset_universe: AssetUniverse

    def __post_init__(self) -> None:
        for field_name in (
            "pit_policy_version",
            "calendar_policy_version",
            "execution_policy_version",
            "risk_policy_version",
            "fee_policy_version",
            "slippage_policy_version",
            "benchmark_key",
            "experiment_policy_version",
            "comparison_policy_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.initial_capital.amount <= 0:
            raise ValueError("initial_capital must be positive")
        if self.initial_capital.currency != self.asset_universe.base_currency.value:
            raise ValueError("initial capital currency must equal the universe base currency")

    @property
    def identity(self) -> str:
        payload = {
            "asset_classes": sorted(item.value for item in self.asset_universe.asset_classes),
            "base_currency": self.asset_universe.base_currency.value,
            "benchmark_key": self.benchmark_key,
            "calendar_policy_version": self.calendar_policy_version,
            "comparison_policy_version": self.comparison_policy_version,
            "currencies": sorted(item.value for item in self.asset_universe.currencies),
            "execution_policy_version": self.execution_policy_version,
            "experiment_policy_version": self.experiment_policy_version,
            "fee_policy_version": self.fee_policy_version,
            "initial_capital": str(self.initial_capital.amount),
            "market_venues": sorted(item.value for item in self.asset_universe.market_venues),
            "pit_policy_version": self.pit_policy_version,
            "risk_policy_version": self.risk_policy_version,
            "slippage_policy_version": self.slippage_policy_version,
            "start_date": self.start_date.isoformat(),
        }
        canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return f"policy-{sha256(canonical.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ManagerProfile:
    manager_id: str
    display_name: str
    role_title: str
    mandate: str
    avatar_reference: str
    role_identity: RoleIdentity
    active: bool
    horizons: tuple[InvestmentHorizon, ...]
    trading_styles: tuple[TradingStyle, ...]

    def __post_init__(self) -> None:
        for field_name in ("manager_id", "display_name", "role_title", "mandate"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        object.__setattr__(self, "avatar_reference", _avatar_reference(self.avatar_reference))
        if not self.horizons or not self.trading_styles:
            raise ValueError("manager profile requires horizon and trading-style metadata")


@dataclass(frozen=True, slots=True)
class DecisionSourceAssignment:
    source_id: str
    kind: DecisionSourceKind
    version: str
    configuration_reference: str

    def __post_init__(self) -> None:
        for field_name in ("source_id", "version", "configuration_reference"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))


@dataclass(frozen=True, slots=True)
class ExperimentMemberDefinition:
    portfolio_role: PortfolioRole
    profile: ManagerProfile
    decision_source: DecisionSourceAssignment

    def __post_init__(self) -> None:
        is_champion_profile = self.profile.role_identity is RoleIdentity.CHAMPION
        if (self.portfolio_role is PortfolioRole.CHAMPION) != is_champion_profile:
            raise ValueError("Champion role and profile identity must match")


@dataclass(frozen=True, slots=True)
class ExperimentMember:
    account_id: str
    portfolio_id: PortfolioId
    definition: ExperimentMemberDefinition
    policy_bundle_id: str
    initial_capital: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _text(self.account_id, "account_id"))
        object.__setattr__(
            self, "policy_bundle_id", _text(self.policy_bundle_id, "policy_bundle_id")
        )


@dataclass(frozen=True, slots=True)
class FairnessContract:
    contract_id: str
    policy_bundle_id: str
    initial_capital: Money
    member_account_ids: tuple[str, ...]
    shared_dimensions: tuple[str, ...]
    created_at: datetime

    REQUIRED_DIMENSIONS = frozenset(
        {
            "PIT_POLICY",
            "TRADING_CALENDAR",
            "EXECUTION_POLICY",
            "RISK_POLICY",
            "FEE_POLICY",
            "SLIPPAGE_POLICY",
            "BENCHMARK",
            "INITIAL_CAPITAL",
            "START_DATE",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _text(self.contract_id, "contract_id"))
        object.__setattr__(
            self, "policy_bundle_id", _text(self.policy_bundle_id, "policy_bundle_id")
        )
        _aware(self.created_at, "created_at")
        if len(self.member_account_ids) != len(set(self.member_account_ids)):
            raise ValueError("fairness contract account identities must be unique")
        if not self.member_account_ids:
            raise ValueError("fairness contract requires members")
        if not self.REQUIRED_DIMENSIONS <= set(self.shared_dimensions):
            raise ValueError("fairness contract is missing required shared dimensions")


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    group_id: str
    display_name: str
    policy_bundle: ExperimentPolicyBundle
    members: tuple[ExperimentMember, ...]
    fairness_contract: FairnessContract
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_id", _text(self.group_id, "group_id"))
        object.__setattr__(self, "display_name", _text(self.display_name, "display_name"))
        _aware(self.created_at, "created_at")
        champions = tuple(
            item
            for item in self.members
            if item.definition.portfolio_role is PortfolioRole.CHAMPION
        )
        shadows = tuple(
            item for item in self.members if item.definition.portfolio_role is PortfolioRole.SHADOW
        )
        if len(champions) != 1 or len(shadows) < 3:
            raise ValueError("experiment requires exactly one Champion and at least three Shadows")
        for field_name, values in (
            ("account_id", tuple(item.account_id for item in self.members)),
            ("portfolio_id", tuple(item.portfolio_id.value for item in self.members)),
            (
                "manager_id",
                tuple(item.definition.profile.manager_id for item in self.members),
            ),
            (
                "role_identity",
                tuple(item.definition.profile.role_identity for item in self.members),
            ),
            (
                "decision_source",
                tuple(item.definition.decision_source.source_id for item in self.members),
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"experiment member {field_name} values must be unique")
        if any(item.policy_bundle_id != self.policy_bundle.identity for item in self.members):
            raise ValueError("all members must share the frozen policy bundle")
        if any(item.initial_capital != self.policy_bundle.initial_capital for item in self.members):
            raise ValueError("all members must share equal initial capital")
        if self.fairness_contract.policy_bundle_id != self.policy_bundle.identity:
            raise ValueError("fairness contract must bind the manifest policy bundle")
        if self.fairness_contract.initial_capital != self.policy_bundle.initial_capital:
            raise ValueError("fairness contract must bind equal initial capital")
        if set(self.fairness_contract.member_account_ids) != {
            item.account_id for item in self.members
        }:
            raise ValueError("fairness contract must bind every experiment member")


@dataclass(frozen=True, slots=True)
class MemberSessionResult:
    account_id: str
    source_id: str
    status: MemberSessionStatus
    paper_session_id: str | None
    performance_snapshot_id: str | None
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _text(self.account_id, "account_id"))
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        if self.status is MemberSessionStatus.FAILED and not self.error_code:
            raise ValueError("failed member session requires error_code")
        if self.status is not MemberSessionStatus.FAILED and self.error_code is not None:
            raise ValueError("non-failed member session cannot contain error_code")


@dataclass(frozen=True, slots=True)
class GroupTradingSession:
    group_session_id: str
    group_id: str
    trading_date: date
    pit_cutoff: datetime
    started_at: datetime
    finalized_at: datetime
    status: GroupSessionStatus
    member_results: tuple[MemberSessionResult, ...]
    policy_bundle_id: str

    def __post_init__(self) -> None:
        for field_name in ("group_session_id", "group_id", "policy_bundle_id"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        _aware(self.pit_cutoff, "pit_cutoff")
        _aware(self.started_at, "started_at")
        _aware(self.finalized_at, "finalized_at")
        if self.finalized_at < self.started_at:
            raise ValueError("group session cannot finalize before it starts")
        if len(self.member_results) != len({item.account_id for item in self.member_results}):
            raise ValueError("group session contains duplicate account results")


@dataclass(frozen=True, slots=True)
class ComparisonPolicy:
    minimum_provisional_sessions: int = 5
    minimum_qualified_sessions: int = 20
    version: str = "shadow-comparison/v1"

    def __post_init__(self) -> None:
        if self.minimum_provisional_sessions <= 0:
            raise ValueError("minimum provisional sessions must be positive")
        if self.minimum_qualified_sessions < self.minimum_provisional_sessions:
            raise ValueError("qualified threshold must not precede provisional threshold")
        object.__setattr__(self, "version", _text(self.version, "comparison policy version"))

    def sample_status(self, session_count: int) -> ComparisonSampleStatus:
        if session_count < self.minimum_provisional_sessions:
            return ComparisonSampleStatus.INSUFFICIENT_SAMPLE
        if session_count < self.minimum_qualified_sessions:
            return ComparisonSampleStatus.PROVISIONAL
        return ComparisonSampleStatus.QUALIFIED


@dataclass(frozen=True, slots=True)
class ComparisonMetrics:
    account_id: str
    nav: Money
    total_return: Decimal
    max_drawdown: Decimal
    sharpe: Decimal | None
    sortino: Decimal | None
    calmar: Decimal | None
    benchmark_return: Decimal
    excess_return: Decimal
    turnover: Decimal
    total_costs: Money
    gross_exposure: Money
    cash: Money
    position_count: int
    sample_status: ComparisonSampleStatus


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    account_id: str
    composite_rank: int
    return_rank: int
    risk_adjusted_rank: int
    drawdown_rank: int
    cost_rank: int
    sample_status: ComparisonSampleStatus


@dataclass(frozen=True, slots=True)
class PerformanceComparisonSnapshot:
    comparison_id: str
    group_id: str
    group_session_id: str
    trading_date: date
    as_of: datetime
    policy_bundle_id: str
    metrics: tuple[ComparisonMetrics, ...]
    leaderboard: tuple[LeaderboardEntry, ...]
    qualified_winner_account_id: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "comparison_id",
            "group_id",
            "group_session_id",
            "policy_bundle_id",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class RoleAvatarReferenceUpdated:
    event_id: str
    group_id: str
    account_id: str
    manager_id: str
    previous_avatar_reference: str
    new_avatar_reference: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("event_id", "group_id", "account_id", "manager_id"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "previous_avatar_reference",
            _avatar_reference(self.previous_avatar_reference),
        )
        object.__setattr__(
            self,
            "new_avatar_reference",
            _avatar_reference(self.new_avatar_reference),
        )
        _aware(self.occurred_at, "occurred_at")
        if self.previous_avatar_reference == self.new_avatar_reference:
            raise ValueError("avatar_reference update must change the effective reference")


@dataclass(frozen=True, slots=True)
class RoleActivity:
    activity_id: str
    group_id: str
    group_session_id: str | None
    account_id: str
    manager_id: str
    occurred_at: datetime
    status: RoleActivityStatus
    reason_code: str | None = None
    task_reference: str | None = None
    output_reference: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("activity_id", "group_id", "account_id", "manager_id"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        for field_name in (
            "group_session_id",
            "reason_code",
            "task_reference",
            "output_reference",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _text(value, field_name))
        _aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class RoleActivityView:
    manager_id: str
    display_name: str
    avatar_reference: str
    paper_account_id: str
    current_status: RoleActivityStatus
    current_task_reference: str | None
    latest_session_reference: str | None
    latest_output_reference: str | None
    latest_event_at: datetime


def latest_role_activity(activities: tuple[RoleActivity, ...]) -> tuple[RoleActivity, ...]:
    latest: dict[str, RoleActivity] = {}
    for activity in activities:
        latest[activity.account_id] = activity
    return tuple(latest[key] for key in sorted(latest))


def current_manager_profile(
    member: ExperimentMember,
    avatar_events: tuple[RoleAvatarReferenceUpdated, ...],
) -> ManagerProfile:
    profile = member.definition.profile
    for event in avatar_events:
        if event.account_id == member.account_id:
            profile = replace(profile, avatar_reference=event.new_avatar_reference)
    return profile


def build_role_activity_board(
    manifest: ExperimentManifest,
    activities: tuple[RoleActivity, ...],
    avatar_events: tuple[RoleAvatarReferenceUpdated, ...],
) -> tuple[RoleActivityView, ...]:
    latest_by_account = {item.account_id: item for item in activities}
    views: list[RoleActivityView] = []
    for member in sorted(manifest.members, key=lambda item: item.account_id):
        profile = current_manager_profile(member, avatar_events)
        activity = latest_by_account.get(member.account_id)
        views.append(
            RoleActivityView(
                profile.manager_id,
                profile.display_name,
                profile.avatar_reference,
                member.account_id,
                activity.status if activity is not None else RoleActivityStatus.IDLE,
                activity.task_reference if activity is not None else None,
                activity.group_session_id if activity is not None else None,
                activity.output_reference if activity is not None else None,
                activity.occurred_at if activity is not None else manifest.created_at,
            )
        )
    return tuple(views)


def validate_experiment_evidence(
    manifest: ExperimentManifest,
    sessions: tuple[GroupTradingSession, ...],
    activities: tuple[RoleActivity, ...],
    avatar_events: tuple[RoleAvatarReferenceUpdated, ...],
) -> None:
    members = {item.account_id: item for item in manifest.members}
    session_ids = {item.group_session_id for item in sessions}
    for activity in activities:
        member = members.get(activity.account_id)
        if member is None:
            raise ValueError("role activity account must belong to the experiment")
        if activity.group_id != manifest.group_id:
            raise ValueError("role activity group must match the experiment")
        if activity.manager_id != member.definition.profile.manager_id:
            raise ValueError("role activity manager must match the experiment member")
        if (
            activity.group_session_id is not None
            and activity.group_session_id not in session_ids
        ):
            raise ValueError("role activity session must belong to the experiment")

    references = {
        item.account_id: item.definition.profile.avatar_reference for item in manifest.members
    }
    event_ids: set[str] = set()
    for event in avatar_events:
        if event.event_id in event_ids:
            raise ValueError("role profile audit event identities must be unique")
        event_ids.add(event.event_id)
        member = members.get(event.account_id)
        if member is None:
            raise ValueError("role profile event account must belong to the experiment")
        if event.group_id != manifest.group_id:
            raise ValueError("role profile event group must match the experiment")
        if event.manager_id != member.definition.profile.manager_id:
            raise ValueError("role profile event manager must match the experiment member")
        if event.previous_avatar_reference != references[event.account_id]:
            raise ValueError("role profile event must continue the avatar audit chain")
        references[event.account_id] = event.new_avatar_reference


def _rank(
    metrics: tuple[ComparisonMetrics, ...],
    key: str,
    *,
    lower_is_better: bool = False,
) -> dict[str, int]:
    def value(item: ComparisonMetrics) -> Decimal:
        candidate = getattr(item, key)
        if isinstance(candidate, Money):
            return candidate.amount
        if candidate is None:
            return Decimal("Infinity") if lower_is_better else Decimal("-Infinity")
        if not isinstance(candidate, Decimal):
            raise TypeError(f"comparison metric {key} must be Decimal or Money")
        return candidate

    ordered = sorted(
        metrics,
        key=lambda item: (
            value(item) if lower_is_better else -value(item),
            item.account_id,
        ),
    )
    return {item.account_id: index for index, item in enumerate(ordered, start=1)}


def build_comparison_snapshot(
    manifest: ExperimentManifest,
    session: GroupTradingSession,
    performance: tuple[PaperPerformanceSnapshot, ...],
    history_counts: dict[str, int],
    policy: ComparisonPolicy,
) -> PerformanceComparisonSnapshot:
    metrics = tuple(
        ComparisonMetrics(
            item.account_id,
            item.nav,
            item.total_return,
            item.max_drawdown,
            item.sharpe,
            item.sortino,
            item.calmar,
            item.benchmark_return,
            item.excess_return,
            item.turnover,
            Money(
                item.fee_total.amount + item.tax_total.amount + item.slippage_total.amount,
                item.nav.currency,
            ),
            item.gross_exposure,
            item.cash,
            item.position_count,
            policy.sample_status(history_counts[item.account_id]),
        )
        for item in sorted(performance, key=lambda value: value.account_id)
    )
    return_ranks = _rank(metrics, "total_return")
    sharpe_ranks = _rank(metrics, "sharpe")
    sortino_ranks = _rank(metrics, "sortino")
    calmar_ranks = _rank(metrics, "calmar")
    drawdown_ranks = _rank(metrics, "max_drawdown")
    cost_ranks = _rank(metrics, "total_costs", lower_is_better=True)
    risk_adjusted_order = sorted(
        metrics,
        key=lambda item: (
            sharpe_ranks[item.account_id]
            + sortino_ranks[item.account_id]
            + calmar_ranks[item.account_id],
            item.account_id,
        ),
    )
    risk_adjusted_ranks = {
        item.account_id: index
        for index, item in enumerate(risk_adjusted_order, start=1)
    }
    composites = sorted(
        metrics,
        key=lambda item: (
            return_ranks[item.account_id]
            + risk_adjusted_ranks[item.account_id]
            + drawdown_ranks[item.account_id]
            + cost_ranks[item.account_id],
            item.account_id,
        ),
    )
    leaderboard = tuple(
        LeaderboardEntry(
            item.account_id,
            index,
            return_ranks[item.account_id],
            risk_adjusted_ranks[item.account_id],
            drawdown_ranks[item.account_id],
            cost_ranks[item.account_id],
            item.sample_status,
        )
        for index, item in enumerate(composites, start=1)
    )
    qualified = tuple(
        item
        for item in leaderboard
        if item.sample_status is ComparisonSampleStatus.QUALIFIED
    )
    return PerformanceComparisonSnapshot(
        stable_experiment_id("comparison", manifest.group_id, session.trading_date),
        manifest.group_id,
        session.group_session_id,
        session.trading_date,
        session.finalized_at,
        manifest.policy_bundle.identity,
        metrics,
        leaderboard,
        qualified[0].account_id if qualified else None,
    )
