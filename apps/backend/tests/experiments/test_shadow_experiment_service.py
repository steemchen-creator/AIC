from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.application.execution import AShareExecutionService
from aic_backend.application.experiments import CreateShadowExperiment, ShadowExperimentService
from aic_backend.application.paper import ScriptedPaperDecisionSource
from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityDecision,
    AvailabilityMode,
    PointInTimeDataResult,
)
from aic_backend.domain.execution import PreTradeRiskPolicy, PriceLimitBand, RiskPolicyConfig
from aic_backend.domain.experiments import (
    AssetClass,
    AssetUniverse,
    ComparisonSampleStatus,
    Currency,
    DecisionSourceAssignment,
    DecisionSourceKind,
    ExperimentMemberDefinition,
    ExperimentPolicyBundle,
    GroupSessionStatus,
    InvestmentHorizon,
    ManagerProfile,
    MarketVenue,
    MemberSessionStatus,
    PortfolioRole,
    RoleActivityStatus,
    RoleIdentity,
    TradingStyle,
)
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentTradingState,
    InstrumentType,
    Market,
    standard_a_share_session,
)
from aic_backend.domain.paper import PaperOrderIntent
from aic_backend.domain.portfolio.models import Money, OrderSide, Quantity
from aic_backend.domain.portfolio.policies import ConfigurableFeePolicy, FixedBpsSlippagePolicy
from aic_backend.infrastructure.experiment_persistence import (
    InMemoryShadowExperimentRepository,
)
from aic_backend.infrastructure.paper_persistence import InMemoryPaperTradingRepository

DAYS = (date(2026, 9, 7), date(2026, 9, 8))


@dataclass(frozen=True)
class CalendarDay:
    trading_date: date
    is_open: bool
    session: object | None


@dataclass(frozen=True)
class TradingStatus:
    trading_date: date
    state: InstrumentTradingState


@dataclass(frozen=True)
class DailyBar:
    trading_date: date
    open: Decimal
    close: Decimal


@dataclass(frozen=True)
class PersistedBar:
    record: DailyBar


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class Readiness:
    async def check(self, account, as_of):
        return ()


class Bands:
    async def get_band(self, instrument, trading_date, as_of):
        return PriceLimitBand(
            Decimal("1"), Decimal("1000"), f"band:{instrument.canonical_key}", as_of
        )


class PitFixture:
    def __init__(self) -> None:
        self.instruments: set[InstrumentIdentity] = set()
        self.bars: dict[tuple[str, date], tuple[Decimal, Decimal, datetime]] = {}
        self.contexts = []

    async def list_calendar_as_of(self, market, start, end, context):
        self.contexts.append(context)
        is_open = start in DAYS
        return PointInTimeDataResult(
            (CalendarDay(start, is_open, standard_a_share_session(start) if is_open else None),),
            (),
            (),
            context.policy_version,
        )

    async def list_instruments_as_of(self, lifecycle_date, context, market=None):
        self.contexts.append(context)
        records = tuple(
            item
            for item in sorted(self.instruments, key=lambda value: value.canonical_key)
            if market is None or item.market is market
        )
        return PointInTimeDataResult(
            records,
            tuple(
                AvailabilityDecision(
                    item.canonical_key,
                    AvailabilityClassification.AVAILABLE,
                    None,
                    "listing_lifecycle",
                    context.policy_version,
                )
                for item in records
            ),
            (),
            context.policy_version,
        )

    async def list_trading_status_as_of(self, instrument, start, end, context):
        self.contexts.append(context)
        return PointInTimeDataResult(
            (TradingStatus(start, InstrumentTradingState.TRADING),),
            (
                AvailabilityDecision(
                    f"{instrument.canonical_key}:{start}",
                    AvailabilityClassification.AVAILABLE,
                    context.as_of,
                    "retrieved_at",
                    context.policy_version,
                ),
            ),
            (),
            context.policy_version,
        )

    async def get_daily_bars_as_of(self, instrument, start, end, context):
        self.contexts.append(context)
        value = self.bars.get((instrument.canonical_key, start))
        if value is None:
            return PointInTimeDataResult((), (), (), context.policy_version)
        open_price, close_price, available_at = value
        if available_at > context.as_of:
            return PointInTimeDataResult(
                (),
                (
                    AvailabilityDecision(
                        f"{instrument.canonical_key}:{start}",
                        AvailabilityClassification.NOT_YET_AVAILABLE,
                        available_at,
                        "ingested_at",
                        context.policy_version,
                    ),
                ),
                (),
                context.policy_version,
            )
        return PointInTimeDataResult(
            (PersistedBar(DailyBar(start, open_price, close_price)),),
            (
                AvailabilityDecision(
                    f"{instrument.canonical_key}:{start}",
                    AvailabilityClassification.AVAILABLE,
                    available_at,
                    "ingested_at",
                    context.policy_version,
                ),
            ),
            (),
            context.policy_version,
        )

    async def list_corporate_actions_as_of(self, instrument, start, end, context):
        self.contexts.append(context)
        return PointInTimeDataResult((), (), (), context.policy_version)


class FailingDecisionSource:
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    async def intents_for(self, account_id, trading_date):
        raise RuntimeError("isolated fixture failure")


def instrument(symbol: str, kind: InstrumentType = InstrumentType.EQUITY) -> InstrumentIdentity:
    return InstrumentIdentity(Market.CN_SSE, symbol, kind)


BENCHMARK = instrument("000001", InstrumentType.INDEX)


def populated_pit() -> PitFixture:
    pit = PitFixture()
    prices = {
        "600001": (("10", "11"), ("11", "12")),
        "600002": (("20", "19"), ("19", "18")),
        "600003": (("30", "30.5"), ("30.5", "31")),
        "000001": (("3000", "3030"), ("3030", "3060")),
    }
    for symbol, daily_values in prices.items():
        value = BENCHMARK if symbol == "000001" else instrument(symbol)
        pit.instruments.add(value)
        for trading_date, (open_price, close_price) in zip(DAYS, daily_values, strict=True):
            pit.bars[(value.canonical_key, trading_date)] = (
                Decimal(open_price),
                Decimal(close_price),
                datetime.combine(trading_date, datetime.min.time(), UTC)
                + timedelta(hours=7, minutes=30),
            )
    return pit


def paper_runtime(pit, clock, repository):
    execution = AShareExecutionService(
        pit,
        ConfigurableFeePolicy(Decimal("0.0003"), Decimal("5"), Decimal("0.001")),
        FixedBpsSlippagePolicy(Decimal("0")),
        PreTradeRiskPolicy(RiskPolicyConfig(Decimal("0.4"), Decimal("1"))),
        availability_mode=AvailabilityMode.OPERATIONAL_REPLAY,
        reference_price_field="open",
        execution_policy_version="next-session-open/v1",
    )
    from aic_backend.application.paper import PaperTradingRuntime

    return PaperTradingRuntime(
        pit,
        execution,
        repository,
        Readiness(),
        Bands(),
        clock,
        BENCHMARK,
    )


def member_definition(role: RoleIdentity, portfolio_role: PortfolioRole):
    return ExperimentMemberDefinition(
        portfolio_role,
        ManagerProfile(
            f"manager-{role.value.lower()}",
            role.value.title(),
            f"{role.value.title()} Portfolio Manager",
            f"Independent {role.value} mandate",
            f"avatars/{role.value.lower()}.svg",
            role,
            True,
            (InvestmentHorizon.MEDIUM,),
            (TradingStyle.TREND,),
        ),
        DecisionSourceAssignment(
            f"fixture/{role.value.lower()}",
            DecisionSourceKind.FIXTURE,
            "v1",
            f"fixtures/{role.value.lower()}.json",
        ),
    )


def create_command(group_id: str = "shadow-lab-1") -> CreateShadowExperiment:
    policy = ExperimentPolicyBundle(
        "pit-operational-replay/v1",
        "a-share-calendar/v1",
        "next-session-open/v1",
        "a-share-pre-trade-risk/v1",
        "a-share-fees/v1",
        "fixed-bps/v1",
        BENCHMARK.canonical_key,
        Money(Decimal("500000")),
        DAYS[0],
        "shadow-experiment/v1",
        "shadow-comparison/v1",
        AssetUniverse(
            (AssetClass.CASH, AssetClass.EQUITY, AssetClass.ETF),
            (MarketVenue.CN_SSE, MarketVenue.CN_SZSE),
            (Currency.CNY,),
            Currency.CNY,
        ),
    )
    return CreateShadowExperiment(
        group_id,
        "AIC Internal Investment Lab",
        policy,
        (
            member_definition(RoleIdentity.CHAMPION, PortfolioRole.CHAMPION),
            member_definition(RoleIdentity.ATLAS, PortfolioRole.SHADOW),
            member_definition(RoleIdentity.SAGE, PortfolioRole.SHADOW),
            member_definition(RoleIdentity.AEGIS, PortfolioRole.SHADOW),
        ),
    )


def order(account_id: str, role: str, trading_date: date, symbol: str, quantity: str):
    return PaperOrderIntent(
        f"{role}-{trading_date.isoformat()}",
        account_id,
        datetime.combine(trading_date - timedelta(days=1), datetime.min.time(), UTC)
        + timedelta(hours=8),
        trading_date,
        instrument(symbol),
        OrderSide.BUY,
        Quantity(Decimal(quantity)),
        f"fixture:{role}",
    )


def sources(manifest, *, failing_role: RoleIdentity | None = None):
    symbols = {
        RoleIdentity.CHAMPION: None,
        RoleIdentity.ATLAS: ("600001", "1000"),
        RoleIdentity.SAGE: ("600002", "1000"),
        RoleIdentity.AEGIS: ("600003", "100"),
    }
    values = {}
    for member in manifest.members:
        assignment = member.definition.decision_source
        role = member.definition.profile.role_identity
        if role is failing_role:
            values[assignment.source_id] = FailingDecisionSource(assignment.source_id)
            continue
        target = symbols[role]
        intents = (
            ()
            if target is None
            else (order(member.account_id, role.value, DAYS[0], *target),)
        )
        values[assignment.source_id] = ScriptedPaperDecisionSource(
            assignment.source_id, intents
        )
    return values


@pytest.mark.asyncio
async def test_minimum_group_runs_independent_compounding_and_deterministic_restart() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 9, 7, 8, tzinfo=UTC))
    paper_repository = InMemoryPaperTradingRepository()
    experiment_repository = InMemoryShadowExperimentRepository()
    runtime = paper_runtime(pit, clock, paper_repository)
    service = ShadowExperimentService(runtime, experiment_repository, clock)
    manifest = await service.create(create_command())

    assert len(manifest.members) == 4
    assert sum(
        member.definition.portfolio_role is PortfolioRole.SHADOW
        for member in manifest.members
    ) == 3
    assert {member.initial_capital.amount for member in manifest.members} == {
        Decimal("500000")
    }

    day_one = await service.run_session(manifest.group_id, DAYS[0], sources(manifest))
    assert day_one.status is GroupSessionStatus.FINALIZED
    assert all(
        result.status is MemberSessionStatus.SUCCEEDED for result in day_one.member_results
    )
    records = [await paper_repository.get(member.account_id) for member in manifest.members]
    assert all(record is not None for record in records)
    non_null_records = [record for record in records if record is not None]
    assert len({record.account.portfolio_id for record in non_null_records}) == 4
    assert len({record.performance[-1].nav.amount for record in non_null_records}) == 4
    assert [len(record.portfolio_state.positions) for record in non_null_records] == [0, 1, 1, 1]
    assert all(
        record.account.initial_capital.amount == Decimal("500000")
        for record in non_null_records
    )

    group_record = await service.get(manifest.group_id)
    assert group_record is not None and len(group_record.comparisons) == 1
    assert group_record.comparisons[0].qualified_winner_account_id is None
    assert {
        item.sample_status for item in group_record.comparisons[0].metrics
    } == {ComparisonSampleStatus.INSUFFICIENT_SAMPLE}

    clock.value = datetime(2026, 9, 8, 8, tzinfo=UTC)
    restarted = ShadowExperimentService(
        paper_runtime(pit, clock, paper_repository), experiment_repository, clock
    )
    day_two_sources = {
        member.definition.decision_source.source_id: ScriptedPaperDecisionSource(
            member.definition.decision_source.source_id, ()
        )
        for member in manifest.members
    }
    day_two = await restarted.run_session(manifest.group_id, DAYS[1], day_two_sources)
    before_replay = await restarted.get(manifest.group_id)
    replay = await restarted.run_session(manifest.group_id, DAYS[1], day_two_sources)
    assert replay == day_two
    assert await restarted.get(manifest.group_id) == before_replay
    for member in manifest.members:
        record = await paper_repository.get(member.account_id)
        assert record is not None
        assert len(record.performance) == 2
        assert record.account.initial_capital.amount == Decimal("500000")
    assert all(
        context.availability_mode is AvailabilityMode.OPERATIONAL_REPLAY
        for context in pit.contexts
    )


@pytest.mark.asyncio
async def test_one_shadow_failure_is_isolated_and_role_activity_is_real_state() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 9, 7, 8, tzinfo=UTC))
    paper_repository = InMemoryPaperTradingRepository()
    experiment_repository = InMemoryShadowExperimentRepository()
    service = ShadowExperimentService(
        paper_runtime(pit, clock, paper_repository), experiment_repository, clock
    )
    manifest = await service.create(create_command("isolation-lab"))
    result = await service.run_session(
        manifest.group_id, DAYS[0], sources(manifest, failing_role=RoleIdentity.SAGE)
    )
    assert result.status is GroupSessionStatus.FINALIZED_WITH_FAILURES
    failed = tuple(
        item for item in result.member_results if item.status is MemberSessionStatus.FAILED
    )
    assert len(failed) == 1 and failed[0].error_code == "RuntimeError"
    assert sum(
        item.status is MemberSessionStatus.SUCCEEDED for item in result.member_results
    ) == 3

    group_record = await service.get(manifest.group_id)
    assert group_record is not None
    failing_account = failed[0].account_id
    assert any(
        item.account_id == failing_account and item.status is RoleActivityStatus.ERROR
        for item in group_record.activities
    )
    assert not any(
        item.account_id != failing_account and item.status is RoleActivityStatus.ERROR
        for item in group_record.activities
    )
    latest_activity = await service.role_activity(manifest.group_id)
    assert len(latest_activity) == 4
    assert next(
        item for item in latest_activity if item.account_id == failing_account
    ).status is RoleActivityStatus.ERROR
    for member in manifest.members:
        record = await paper_repository.get(member.account_id)
        assert record is not None
        expected = 0 if member.account_id == failing_account else 1
        assert len(record.performance) == expected


@pytest.mark.asyncio
async def test_missing_or_mismatched_decision_source_fails_only_assigned_member() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 9, 7, 8, tzinfo=UTC))
    experiment_repository = InMemoryShadowExperimentRepository()
    service = ShadowExperimentService(
        paper_runtime(pit, clock, InMemoryPaperTradingRepository()),
        experiment_repository,
        clock,
    )
    manifest = await service.create(create_command("source-contract-lab"))
    assigned = sources(manifest)
    missing_source_id = manifest.members[-1].definition.decision_source.source_id
    del assigned[missing_source_id]
    result = await service.run_session(manifest.group_id, DAYS[0], assigned)
    assert result.status is GroupSessionStatus.FINALIZED_WITH_FAILURES
    missing = next(item for item in result.member_results if item.source_id == missing_source_id)
    assert missing.error_code == "DECISION_SOURCE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_create_and_session_are_idempotent_and_unknown_group_is_rejected() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 9, 7, 8, tzinfo=UTC))
    repository = InMemoryShadowExperimentRepository()
    service = ShadowExperimentService(
        paper_runtime(pit, clock, InMemoryPaperTradingRepository()), repository, clock
    )
    command = create_command("idempotency-lab")
    first = await service.create(command)
    assert await service.create(command) == first
    with pytest.raises(ValueError, match="different experiment"):
        await service.create(
            CreateShadowExperiment(
                command.group_id,
                "Different Lab",
                command.policy_bundle,
                command.members,
            )
        )
    with pytest.raises(ValueError, match="at least three Shadows"):
        await service.create(
            CreateShadowExperiment(
                "undersized-lab",
                "Undersized Lab",
                command.policy_bundle,
                command.members[:3],
            )
        )
    with pytest.raises(LookupError, match="not found"):
        await service.run_session("missing", DAYS[0], {})
