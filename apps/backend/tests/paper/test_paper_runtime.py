from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.application.execution import AShareExecutionService
from aic_backend.application.paper import PaperTradingRuntime, ScriptedPaperDecisionSource
from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityDecision,
    AvailabilityMode,
    PointInTimeDataResult,
)
from aic_backend.domain.execution import (
    PreTradeRiskPolicy,
    PriceLimitBand,
    RiskPolicyConfig,
    RiskReasonCode,
)
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentTradingState,
    InstrumentType,
    Market,
    standard_a_share_session,
)
from aic_backend.domain.paper import (
    ActivatePaperAccount,
    PaperAccountStatus,
    PaperErrorCode,
    PaperOrderIntent,
    PaperProcessingCheckpoint,
    PaperRuntimeError,
    PaperSessionStatus,
)
from aic_backend.domain.portfolio.models import OrderSide, Quantity
from aic_backend.domain.portfolio.policies import ConfigurableFeePolicy, FixedBpsSlippagePolicy
from aic_backend.infrastructure.paper_persistence import InMemoryPaperTradingRepository


@dataclass(frozen=True)
class Day:
    trading_date: date
    is_open: bool
    session: object | None


@dataclass(frozen=True)
class Status:
    trading_date: date
    state: InstrumentTradingState


@dataclass(frozen=True)
class Bar:
    trading_date: date
    open: Decimal
    close: Decimal


@dataclass(frozen=True)
class Persisted:
    record: Bar


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class Readiness:
    def __init__(self) -> None:
        self.failures: tuple[str, ...] = ()

    async def check(self, account, as_of):
        return self.failures


class Bands:
    async def get_band(self, instrument, trading_date, as_of):
        return PriceLimitBand(
            Decimal("1"), Decimal("100"), f"band:{instrument.canonical_key}:{trading_date}", as_of
        )


@dataclass(frozen=True)
class RawDecisionSource:
    intents: tuple[PaperOrderIntent, ...]

    async def intents_for(self, account_id, trading_date):
        return self.intents


class PitFixture:
    def __init__(self, trading_days: tuple[date, ...]) -> None:
        self.trading_days = trading_days
        self.bars: dict[tuple[str, date], tuple[Decimal, Decimal, datetime]] = {}
        self.instruments: set[InstrumentIdentity] = set()
        self.suspended: set[tuple[str, date]] = set()
        self.actions: set[tuple[str, date]] = set()
        self.contexts = []

    async def list_calendar_as_of(self, market, start, end, context):
        self.contexts.append(context)
        is_open = start in self.trading_days
        records = (Day(start, is_open, standard_a_share_session(start) if is_open else None),)
        return PointInTimeDataResult(records, (), (), context.policy_version)

    async def list_instruments_as_of(self, lifecycle_date, context, market=None):
        self.contexts.append(context)
        records = tuple(
            item
            for item in sorted(self.instruments, key=lambda value: value.canonical_key)
            if market is None or item.market is market
        )
        decisions = tuple(
            AvailabilityDecision(
                item.canonical_key,
                AvailabilityClassification.AVAILABLE,
                None,
                "listing_lifecycle",
                context.policy_version,
            )
            for item in records
        )
        return PointInTimeDataResult(records, decisions, (), context.policy_version)

    async def list_trading_status_as_of(self, instrument, start, end, context):
        self.contexts.append(context)
        state = (
            InstrumentTradingState.SUSPENDED
            if (instrument.canonical_key, start) in self.suspended
            else InstrumentTradingState.TRADING
        )
        return PointInTimeDataResult(
            (Status(start, state),),
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
        classification = (
            AvailabilityClassification.AVAILABLE
            if available_at <= context.as_of
            else AvailabilityClassification.NOT_YET_AVAILABLE
        )
        records = (
            (Persisted(Bar(start, open_price, close_price)),)
            if classification is AvailabilityClassification.AVAILABLE
            else ()
        )
        return PointInTimeDataResult(
            records,
            (
                AvailabilityDecision(
                    f"{instrument.canonical_key}:{start}",
                    classification,
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
        records = (object(),) if (instrument.canonical_key, start) in self.actions else ()
        return PointInTimeDataResult(records, (), (), context.policy_version)


def instrument(symbol: str, kind: InstrumentType = InstrumentType.EQUITY) -> InstrumentIdentity:
    return InstrumentIdentity(Market.CN_SSE, symbol, kind)


TRADING_DAYS = tuple(date(2026, 9, value) for value in (1, 2, 3, 4, 7, 8))
BENCHMARK = instrument("000001", InstrumentType.INDEX)


def populated_pit() -> PitFixture:
    pit = PitFixture(TRADING_DAYS)
    price_series = {
        "600001": (
            ("10", "10"),
            ("10", "11"),
            ("11", "10"),
            ("10", "12"),
            ("12", "11"),
            ("11", "13"),
        ),
        "600002": (
            ("20", "20"),
            ("20", "21"),
            ("21", "22"),
            ("22", "21"),
            ("21", "23"),
            ("23", "24"),
        ),
        "600003": (
            ("30", "30"),
            ("30", "30"),
            ("30", "31"),
            ("31", "32"),
            ("32", "33"),
            ("33", "34"),
        ),
        "600004": (("8", "8"), ("8", "8"), ("8", "8"), ("8", "8"), ("8", "8"), ("8", "8")),
        "000001": (
            ("3000", "3000"),
            ("3000", "3030"),
            ("3030", "3000"),
            ("3000", "3060"),
            ("3060", "3090"),
            ("3090", "3120"),
        ),
    }
    for symbol, values in price_series.items():
        item = BENCHMARK if symbol == "000001" else instrument(symbol)
        pit.instruments.add(item)
        for trading_date, (open_price, close_price) in zip(TRADING_DAYS, values, strict=True):
            pit.bars[(item.canonical_key, trading_date)] = (
                Decimal(open_price),
                Decimal(close_price),
                datetime.combine(trading_date, datetime.min.time(), UTC)
                + timedelta(hours=7, minutes=30),
            )
    return pit


def decision(
    account_id: str,
    intent_id: str,
    trading_date: date,
    symbol: str,
    side: OrderSide,
    quantity: str,
) -> PaperOrderIntent:
    return PaperOrderIntent(
        intent_id,
        account_id,
        datetime.combine(trading_date - timedelta(days=1), datetime.min.time(), UTC)
        + timedelta(hours=8),
        trading_date,
        instrument(symbol),
        side,
        Quantity(Decimal(quantity)),
        f"script:{intent_id}",
    )


def runtime(
    pit: PitFixture,
    clock: MutableClock,
    repository: InMemoryPaperTradingRepository,
    *,
    checkpoint_hook=None,
    readiness: Readiness | None = None,
    availability_mode: AvailabilityMode = AvailabilityMode.OPERATIONAL_REPLAY,
    execution_policy_version: str = "next-session-open/v1",
) -> PaperTradingRuntime:
    execution = AShareExecutionService(
        pit,  # type: ignore[arg-type]
        ConfigurableFeePolicy(Decimal("0.0003"), Decimal("5"), Decimal("0.001")),
        FixedBpsSlippagePolicy(Decimal("0")),
        PreTradeRiskPolicy(RiskPolicyConfig(Decimal("0.4"), Decimal("1"))),
        availability_mode=availability_mode,
        reference_price_field="open",
        execution_policy_version=execution_policy_version,
    )
    return PaperTradingRuntime(
        pit,  # type: ignore[arg-type]
        execution,
        repository,
        readiness or Readiness(),
        Bands(),
        clock,
        BENCHMARK,
        checkpoint_hook=checkpoint_hook,
    )


async def activated(runtime_value: PaperTradingRuntime, clock: MutableClock) -> str:
    account = await runtime_value.create_champion()
    await runtime_value.activate(ActivatePaperAccount(account.account_id, clock.now()))
    return account.account_id


def set_day(clock: MutableClock, trading_date: date) -> None:
    clock.value = datetime.combine(trading_date, datetime.min.time(), UTC) + timedelta(hours=8)


def source(*intents: PaperOrderIntent) -> ScriptedPaperDecisionSource:
    return ScriptedPaperDecisionSource("scripted-fixture/v1", tuple(intents))


@pytest.mark.asyncio
async def test_activation_pause_resume_stop_and_readiness_gate() -> None:
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    repository = InMemoryPaperTradingRepository()
    readiness = Readiness()
    value = runtime(populated_pit(), clock, repository, readiness=readiness)
    account = await value.create_champion()
    assert account.initial_capital.amount == Decimal("500000")
    assert account.status is PaperAccountStatus.CREATED
    readiness.failures = ("PIT_NOT_READY",)
    with pytest.raises(PaperRuntimeError) as error:
        await value.activate(ActivatePaperAccount(account.account_id, clock.now()))
    assert error.value.code is PaperErrorCode.READINESS_FAILED
    readiness.failures = ()
    assert (
        await value.activate(ActivatePaperAccount(account.account_id, clock.now()))
    ).status is PaperAccountStatus.RUNNING
    assert (await value.pause(account.account_id, "operator")).status is PaperAccountStatus.PAUSED
    assert (await value.resume(account.account_id)).status is PaperAccountStatus.RUNNING
    assert (await value.stop(account.account_id)).status is PaperAccountStatus.STOPPED


@pytest.mark.asyncio
async def test_runtime_enforces_configuration_and_lifecycle_boundaries() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    repository = InMemoryPaperTradingRepository()
    with pytest.raises(ValueError, match="OPERATIONAL_REPLAY"):
        runtime(
            pit,
            clock,
            repository,
            availability_mode=AvailabilityMode.HISTORICAL_RESEARCH,
        )
    with pytest.raises(ValueError, match="next-session-open"):
        runtime(pit, clock, repository, execution_policy_version="close/v1")

    value = runtime(pit, clock, repository)
    with pytest.raises(PaperRuntimeError) as error:
        await value.pause("missing", "operator")
    assert error.value.code is PaperErrorCode.ACCOUNT_NOT_FOUND

    account = await value.create_champion()
    assert await value.create_champion() == account
    for operation in (
        lambda: value.pause(account.account_id, "operator"),
        lambda: value.resume(account.account_id),
        lambda: value.stop(account.account_id),
    ):
        with pytest.raises(PaperRuntimeError) as error:
            await operation()
        assert error.value.code is PaperErrorCode.INVALID_ACCOUNT_STATE

    assert (
        await value.activate(ActivatePaperAccount(account.account_id, clock.now()))
    ).status is PaperAccountStatus.RUNNING
    assert (
        await value.activate(ActivatePaperAccount(account.account_id, clock.now()))
    ).status is PaperAccountStatus.RUNNING
    assert (await value.pause(account.account_id, "operator")).status is PaperAccountStatus.PAUSED
    assert (await value.pause(account.account_id, "operator")).status is PaperAccountStatus.PAUSED

    readiness = value._readiness  # noqa: SLF001 - injected boundary fixture
    assert isinstance(readiness, Readiness)
    readiness.failures = ("PIT_NOT_READY",)
    with pytest.raises(PaperRuntimeError) as error:
        await value.resume(account.account_id)
    assert error.value.code is PaperErrorCode.READINESS_FAILED
    readiness.failures = ()
    assert (await value.resume(account.account_id)).status is PaperAccountStatus.RUNNING
    assert (await value.resume(account.account_id)).status is PaperAccountStatus.RUNNING
    assert (await value.stop(account.account_id)).status is PaperAccountStatus.STOPPED
    assert (await value.stop(account.account_id)).status is PaperAccountStatus.STOPPED
    with pytest.raises(PaperRuntimeError) as error:
        await value.process_session(account.account_id, TRADING_DAYS[0], source())
    assert error.value.code is PaperErrorCode.INVALID_ACCOUNT_STATE

    clock.value = datetime(2026, 9, 1, 8)
    with pytest.raises(ValueError, match="timezone-aware"):
        await runtime(pit, clock, InMemoryPaperTradingRepository()).create_champion()


@pytest.mark.asyncio
async def test_runtime_rejects_inconsistent_history_and_invalid_intents() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    repository = InMemoryPaperTradingRepository()
    value = runtime(pit, clock, repository)
    account_id = await activated(value, clock)
    set_day(clock, TRADING_DAYS[0])

    valid = decision(account_id, "valid", TRADING_DAYS[0], "600001", OrderSide.BUY, "100")
    invalid_intents = (
        (replace(valid, account_id="another-account"), PaperErrorCode.STATE_INCONSISTENCY),
        (
            replace(valid, intent_id="wrong-date", effective_trading_date=TRADING_DAYS[1]),
            PaperErrorCode.INVALID_ORDER_TIMING,
        ),
    )
    for intent, expected_code in invalid_intents:
        with pytest.raises(PaperRuntimeError) as error:
            await value.process_session(account_id, TRADING_DAYS[0], RawDecisionSource((intent,)))
        assert error.value.code is expected_code
    with pytest.raises(PaperRuntimeError) as error:
        await value.process_session(account_id, TRADING_DAYS[0], source(valid, valid))
    assert error.value.code is PaperErrorCode.STATE_INCONSISTENCY

    record = await repository.get(account_id)
    assert record is not None
    await repository.save(
        replace(record, account=record.account.finalize(TRADING_DAYS[0], clock.now()))
    )
    with pytest.raises(PaperRuntimeError) as error:
        await value.process_session(account_id, TRADING_DAYS[0], source())
    assert error.value.code is PaperErrorCode.STATE_INCONSISTENCY


@pytest.mark.asyncio
async def test_official_champion_multi_day_e2e_restart_and_idempotency() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    repository = InMemoryPaperTradingRepository()
    value = runtime(pit, clock, repository)
    account_id = await activated(value, clock)

    set_day(clock, TRADING_DAYS[0])
    day1 = await value.process_session(account_id, TRADING_DAYS[0], source())
    assert day1 is not None and day1.outcomes == ()
    assert day1.performance.nav.amount == Decimal("500000")

    set_day(clock, TRADING_DAYS[1])
    day2_source = source(
        decision(account_id, "buy-a", TRADING_DAYS[1], "600001", OrderSide.BUY, "1000"),
        decision(account_id, "buy-b", TRADING_DAYS[1], "600002", OrderSide.BUY, "1000"),
    )
    day2 = await value.process_session(account_id, TRADING_DAYS[1], day2_source)
    assert day2 is not None and sum(item.fill is not None for item in day2.outcomes) == 2
    assert tuple(item.fill.fill_price.value for item in day2.outcomes if item.fill) == (
        Decimal("10"),
        Decimal("20"),
    )

    set_day(clock, TRADING_DAYS[2])
    day3_source = source(
        decision(account_id, "01-buy-c", TRADING_DAYS[2], "600003", OrderSide.BUY, "1000"),
        decision(account_id, "02-sell-c-t0", TRADING_DAYS[2], "600003", OrderSide.SELL, "100"),
        decision(account_id, "03-risk-reject", TRADING_DAYS[2], "600004", OrderSide.BUY, "30000"),
    )
    day3 = await value.process_session(account_id, TRADING_DAYS[2], day3_source)
    assert day3 is not None
    assert day3.outcomes[0].fill is not None
    assert day3.outcomes[1].fill is None
    assert day3.outcomes[2].fill is None
    assert RiskReasonCode.INSUFFICIENT_SELLABLE_POSITION in (
        day3.outcomes[1].risk_decision.reason_codes
    )
    assert RiskReasonCode.SINGLE_POSITION_LIMIT in day3.outcomes[2].risk_decision.reason_codes

    value = runtime(pit, clock, repository)
    set_day(clock, TRADING_DAYS[3])
    day4 = await value.process_session(
        account_id,
        TRADING_DAYS[3],
        source(
            decision(account_id, "sell-a-part", TRADING_DAYS[3], "600001", OrderSide.SELL, "200")
        ),
    )
    assert day4 is not None and day4.outcomes[0].fill is not None

    set_day(clock, TRADING_DAYS[4])
    day5 = await value.process_session(account_id, TRADING_DAYS[4], source())
    assert day5 is not None and day5.outcomes == ()

    set_day(clock, TRADING_DAYS[5])
    day6_source = source(
        decision(account_id, "sell-a-close", TRADING_DAYS[5], "600001", OrderSide.SELL, "800")
    )
    day6 = await value.process_session(account_id, TRADING_DAYS[5], day6_source)
    assert day6 is not None
    assert len(day6.new_episodes) == 1
    record = await repository.get(account_id)
    assert record is not None
    assert len(record.performance) == 6
    assert record.performance[-1].position_count == 2
    assert record.performance[-1].nav.amount != Decimal("500000")
    assert record.account.initial_capital.amount == Decimal("500000")
    assert record.account.last_finalized_date == TRADING_DAYS[-1]
    fills = tuple(outcome.fill for outcome in record.outcomes if outcome.fill is not None)
    assert record.performance[-1].fee_total.amount == sum(
        (fill.fee.amount for fill in fills), Decimal("0")
    )
    assert record.performance[-1].tax_total.amount == sum(
        (fill.tax.amount for fill in fills), Decimal("0")
    )
    assert (
        record.performance[-1].gross_pnl.amount - record.performance[-1].net_pnl.amount
        == record.performance[-1].fee_total.amount
        + record.performance[-1].tax_total.amount
        + record.performance[-1].slippage_total.amount
    )
    execution_events = {
        event.event_type for outcome in record.outcomes for event in outcome.audit_events
    }
    assert {
        "ORDER_INTENT",
        "ELIGIBILITY",
        "RISK_DECISION",
        "FILL",
        "CASH_CHANGE",
        "POSITION_SETTLEMENT",
        "RISK_SNAPSHOT",
        "NAV",
    } <= execution_events
    assert {
        "ACCOUNT_CREATED",
        "ACCOUNT_ACTIVATED",
        "EOD_MARK",
        "NAV_SNAPSHOT",
        "PERFORMANCE_SNAPSHOT",
        "SESSION_FINALIZED",
    } <= {
        event.event_type for event in record.events
    }
    assert all(
        context.availability_mode is AvailabilityMode.OPERATIONAL_REPLAY for context in pit.contexts
    )

    before = record
    duplicate = await value.process_session(account_id, TRADING_DAYS[-1], day6_source)
    assert duplicate is not None and duplicate.performance == day6.performance
    assert await repository.get(account_id) == before
    with pytest.raises(PaperRuntimeError) as error:
        await value.process_session(account_id, TRADING_DAYS[0], source())
    assert error.value.code is PaperErrorCode.FORWARD_ONLY_VIOLATION


@pytest.mark.asyncio
async def test_closed_market_creates_no_session_and_future_bar_cannot_fill() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    repository = InMemoryPaperTradingRepository()
    value = runtime(pit, clock, repository)
    account_id = await activated(value, clock)
    closed_date = date(2026, 9, 5)
    set_day(clock, closed_date)
    assert await value.process_session(account_id, closed_date, source()) is None
    record = await repository.get(account_id)
    assert record is not None and record.sessions == ()

    set_day(clock, TRADING_DAYS[0])
    key = (instrument("600001").canonical_key, TRADING_DAYS[0])
    open_price, close_price, _ = pit.bars[key]
    pit.bars[key] = (open_price, close_price, clock.now() + timedelta(hours=1))
    result = await value.process_session(
        account_id,
        TRADING_DAYS[0],
        source(decision(account_id, "future", TRADING_DAYS[0], "600001", OrderSide.BUY, "100")),
    )
    assert result is not None and result.outcomes[0].fill is None
    assert RiskReasonCode.PIT_DATA_UNAVAILABLE in result.outcomes[0].risk_decision.reason_codes


@pytest.mark.asyncio
async def test_same_day_complete_bar_cannot_fill_at_same_day_open() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    repository = InMemoryPaperTradingRepository()
    value = runtime(pit, clock, repository)
    account_id = await activated(value, clock)
    set_day(clock, TRADING_DAYS[0])
    unsafe = PaperOrderIntent(
        "unsafe",
        account_id,
        clock.now(),
        TRADING_DAYS[0],
        instrument("600001"),
        OrderSide.BUY,
        Quantity(Decimal("100")),
        "day-complete-bar",
    )
    with pytest.raises(PaperRuntimeError) as error:
        await value.process_session(account_id, TRADING_DAYS[0], source(unsafe))
    assert error.value.code is PaperErrorCode.INVALID_ORDER_TIMING
    record = await repository.get(account_id)
    assert record is not None and record.outcomes == () and record.performance == ()


@pytest.mark.asyncio
async def test_missing_mark_and_corporate_action_pause_without_fabricating_nav() -> None:
    pit = populated_pit()
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    repository = InMemoryPaperTradingRepository()
    value = runtime(pit, clock, repository)
    account_id = await activated(value, clock)
    set_day(clock, TRADING_DAYS[0])
    await value.process_session(
        account_id,
        TRADING_DAYS[0],
        source(decision(account_id, "buy", TRADING_DAYS[0], "600001", OrderSide.BUY, "100")),
    )
    original = await repository.get(account_id)
    assert original is not None

    set_day(clock, TRADING_DAYS[1])
    del pit.bars[(instrument("600001").canonical_key, TRADING_DAYS[1])]
    with pytest.raises(PaperRuntimeError) as error:
        await value.process_session(account_id, TRADING_DAYS[1], source())
    assert error.value.code is PaperErrorCode.SESSION_FINALIZATION_BLOCKED
    blocked = await repository.get(account_id)
    assert blocked is not None
    assert blocked.account.status is PaperAccountStatus.PAUSED
    assert blocked.sessions[-1].status is PaperSessionStatus.BLOCKED
    assert blocked.performance == original.performance
    restored = populated_pit().bars[(instrument("600001").canonical_key, TRADING_DAYS[1])]
    pit.bars[(instrument("600001").canonical_key, TRADING_DAYS[1])] = restored
    await value.resume(account_id)
    recovered = await value.process_session(account_id, TRADING_DAYS[1], source())
    assert recovered is not None
    assert recovered.session.status is PaperSessionStatus.FINALIZED

    pit = populated_pit()
    repository = InMemoryPaperTradingRepository()
    clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
    value = runtime(pit, clock, repository)
    account_id = await activated(value, clock)
    set_day(clock, TRADING_DAYS[0])
    pit.actions.add((instrument("600001").canonical_key, TRADING_DAYS[0]))
    with pytest.raises(PaperRuntimeError):
        await value.process_session(
            account_id,
            TRADING_DAYS[0],
            source(decision(account_id, "buy", TRADING_DAYS[0], "600001", OrderSide.BUY, "100")),
        )
    blocked = await repository.get(account_id)
    assert blocked is not None and blocked.account.status is PaperAccountStatus.PAUSED


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint", tuple(PaperProcessingCheckpoint))
async def test_crash_recovery_is_atomic_and_deterministic(checkpoint) -> None:
    async def setup(repository, hook=None):
        pit = populated_pit()
        clock = MutableClock(datetime(2026, 8, 31, 8, tzinfo=UTC))
        value = runtime(pit, clock, repository)
        account_id = await activated(value, clock)
        set_day(clock, TRADING_DAYS[0])
        await value.process_session(account_id, TRADING_DAYS[0], source())
        set_day(clock, TRADING_DAYS[1])
        value = runtime(pit, clock, repository, checkpoint_hook=hook)
        day2_source = source(
            decision(account_id, "buy", TRADING_DAYS[1], "600001", OrderSide.BUY, "100")
        )
        return pit, clock, value, account_id, day2_source

    baseline_repository = InMemoryPaperTradingRepository()
    _, _, baseline_runtime, baseline_id, day2_source = await setup(baseline_repository)
    await baseline_runtime.process_session(baseline_id, TRADING_DAYS[1], day2_source)
    baseline = await baseline_repository.get(baseline_id)

    crashed_repository = InMemoryPaperTradingRepository()
    raised = False

    def hook(value):
        nonlocal raised
        if value is checkpoint and not raised:
            raised = True
            raise PaperRuntimeError(PaperErrorCode.INJECTED_CRASH, value.value)

    pit, clock, crashed_runtime, account_id, day2_source = await setup(crashed_repository, hook)
    before = await crashed_repository.get(account_id)
    with pytest.raises(PaperRuntimeError) as error:
        await crashed_runtime.process_session(account_id, TRADING_DAYS[1], day2_source)
    assert error.value.code is PaperErrorCode.INJECTED_CRASH
    assert await crashed_repository.get(account_id) == before

    recovered_runtime = runtime(pit, clock, crashed_repository)
    await recovered_runtime.process_session(account_id, TRADING_DAYS[1], day2_source)
    assert await crashed_repository.get(account_id) == baseline
