from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.application.execution import (
    AShareExecutionService,
    ExecutionOrderIntent,
    ExecutionState,
)
from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityDecision,
    PointInTimeDataResult,
)
from aic_backend.domain.execution import (
    PreTradeRiskPolicy,
    PriceLimitBand,
    RiskDecisionType,
    RiskPolicyConfig,
    RiskReasonCode,
)
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentTradingState,
    InstrumentType,
    Market,
)
from aic_backend.domain.portfolio.models import (
    Money,
    OrderId,
    OrderSide,
    OrderStatus,
    PortfolioId,
    Price,
    Quantity,
)
from aic_backend.domain.portfolio.policies import ConfigurableFeePolicy, FixedBpsSlippagePolicy
from aic_backend.infrastructure.execution_persistence import InMemoryExecutionEvidenceRepository


@dataclass(frozen=True)
class Day:
    trading_date: date
    is_open: bool


@dataclass(frozen=True)
class Status:
    trading_date: date
    state: InstrumentTradingState


@dataclass(frozen=True)
class Bar:
    trading_date: date
    close: Decimal


@dataclass(frozen=True)
class Persisted:
    record: Bar


class PitFixture:
    def __init__(self) -> None:
        self.calendar: dict[date, bool] = {}
        self.lifecycle: dict[str, str] = {}
        self.statuses: dict[tuple[str, date], tuple[InstrumentTradingState, datetime]] = {}
        self.prices: dict[tuple[str, date], tuple[Decimal, datetime]] = {}
        self.contexts = []

    async def list_calendar_as_of(self, market, start, end, context):
        self.contexts.append(context)
        records = () if start not in self.calendar else (Day(start, self.calendar[start]),)
        return PointInTimeDataResult(records, (), (), context.policy_version)

    async def list_instruments_as_of(self, lifecycle_date, context, market=None):
        self.contexts.append(context)
        records = []
        decisions = []
        for key, value in sorted(self.lifecycle.items()):
            instrument = parse_instrument(key)
            if market is not None and instrument.market is not market:
                continue
            source = "listing_lifecycle"
            classification = AvailabilityClassification.AVAILABLE
            if value == "listed":
                records.append(instrument)
            elif value == "not_listed":
                source = "listing_date"
                classification = AvailabilityClassification.NOT_YET_AVAILABLE
            elif value == "delisted":
                source = "known_delisting_date"
                classification = AvailabilityClassification.NOT_YET_AVAILABLE
            else:
                source = "missing_listing_date"
                classification = AvailabilityClassification.UNKNOWN_AVAILABILITY
            decisions.append(
                AvailabilityDecision(key, classification, None, source, context.policy_version)
            )
        return PointInTimeDataResult(tuple(records), tuple(decisions), (), context.policy_version)

    async def list_trading_status_as_of(self, instrument, start, end, context):
        self.contexts.append(context)
        value = self.statuses.get((instrument.canonical_key, start))
        if value is None:
            return PointInTimeDataResult((), (), (), context.policy_version)
        state, available_at = value
        classification = (
            AvailabilityClassification.AVAILABLE
            if available_at <= context.as_of
            else AvailabilityClassification.NOT_YET_AVAILABLE
        )
        decision = AvailabilityDecision(
            f"{instrument.canonical_key}:{start}",
            classification,
            available_at,
            "provider_timestamp",
            context.policy_version,
        )
        records = (
            (Status(start, state),)
            if classification is AvailabilityClassification.AVAILABLE
            else ()
        )
        return PointInTimeDataResult(records, (decision,), (), context.policy_version)

    async def get_daily_bars_as_of(self, instrument, start, end, context):
        self.contexts.append(context)
        value = self.prices.get((instrument.canonical_key, start))
        if value is None:
            return PointInTimeDataResult((), (), (), context.policy_version)
        price, available_at = value
        classification = (
            AvailabilityClassification.AVAILABLE
            if available_at <= context.as_of
            else AvailabilityClassification.NOT_YET_AVAILABLE
        )
        decision = AvailabilityDecision(
            f"{instrument.canonical_key}:{start}",
            classification,
            available_at,
            "provider_timestamp",
            context.policy_version,
        )
        records = (
            (Persisted(Bar(start, price)),)
            if classification is AvailabilityClassification.AVAILABLE
            else ()
        )
        return PointInTimeDataResult(records, (decision,), (), context.policy_version)


def instrument(symbol: str, market: Market = Market.CN_SSE) -> InstrumentIdentity:
    return InstrumentIdentity(market, symbol, InstrumentType.EQUITY)


def parse_instrument(key: str) -> InstrumentIdentity:
    if key.startswith("CN.SSE."):
        return instrument(key.removeprefix("CN.SSE."), Market.CN_SSE)
    return instrument(key.removeprefix("CN.SZSE."), Market.CN_SZSE)


def at(day: date, hour: int = 7) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def band(day: date, lower: str = "1", upper: str = "100") -> PriceLimitBand:
    return PriceLimitBand(Decimal(lower), Decimal(upper), f"limit:{day}", at(day, 6))


def populated_fixture() -> PitFixture:
    value = PitFixture()
    open_days = (date(2026, 8, 21), date(2026, 8, 24), date(2026, 8, 27))
    closed_days = (date(2026, 8, 22), date(2026, 8, 23), date(2026, 8, 25), date(2026, 8, 26))
    value.calendar.update({day: True for day in open_days})
    value.calendar.update({day: False for day in closed_days})
    prices = {
        "600001": ("10", "11", "12"),
        "600002": ("20", "21", "22"),
        "600003": ("30", "30", "31"),
        "600004": ("8", "8", "8"),
    }
    for symbol, series in prices.items():
        item = instrument(symbol)
        value.lifecycle[item.canonical_key] = "listed"
        for day, price in zip(open_days, series, strict=True):
            value.prices[(item.canonical_key, day)] = (Decimal(price), at(day, 6))
            value.statuses[(item.canonical_key, day)] = (InstrumentTradingState.TRADING, at(day, 6))
    return value


def service(
    pit: PitFixture,
    *,
    config: RiskPolicyConfig | None = None,
    repository: InMemoryExecutionEvidenceRepository | None = None,
) -> AShareExecutionService:
    return AShareExecutionService(
        pit,  # type: ignore[arg-type]
        ConfigurableFeePolicy(Decimal("0.0003"), Decimal("5"), Decimal("0.001")),
        FixedBpsSlippagePolicy(),
        PreTradeRiskPolicy(
            config or RiskPolicyConfig(Decimal("0.6"), Decimal("1"), version="fixture-risk/v1")
        ),
        repository,
    )


def state() -> ExecutionState:
    return ExecutionState.initialize(
        PortfolioId("portfolio-e2e"), Money(Decimal("500000")), at(date(2026, 8, 20))
    )


async def submit(
    runtime: AShareExecutionService,
    execution_state: ExecutionState,
    order_id: str,
    day: date,
    symbol: str,
    side: OrderSide,
    quantity: str,
    *,
    limit: PriceLimitBand | None = None,
    requested_price: str | None = None,
):
    return await runtime.execute(
        execution_state,
        ExecutionOrderIntent(
            instrument(symbol),
            side,
            Quantity(Decimal(quantity)),
            None if requested_price is None else Price(Decimal(requested_price)),
        ),
        OrderId(order_id),
        at(day),
        limit if limit is not None else band(day),
    )


@pytest.mark.asyncio
async def test_core_e2e_is_deterministic_and_enforces_t1_risk_and_audit() -> None:
    async def replay():
        pit = populated_fixture()
        repository = InMemoryExecutionEvidenceRepository()
        runtime = service(pit, repository=repository)
        execution_state = state()
        friday = date(2026, 8, 21)
        monday = date(2026, 8, 24)
        values = [
            await submit(
                runtime, execution_state, "buy-a", friday, "600001", OrderSide.BUY, "1000"
            ),
            await submit(
                runtime, execution_state, "buy-b", friday, "600002", OrderSide.BUY, "1000"
            ),
            await submit(
                runtime, execution_state, "sell-a-t0", friday, "600001", OrderSide.SELL, "100"
            ),
        ]
        assert (
            await runtime.advance_session(execution_state, Market.CN_SSE, at(date(2026, 8, 22)))
            is None
        )
        assert (
            await runtime.advance_session(execution_state, Market.CN_SSE, at(date(2026, 8, 23)))
            is None
        )
        values.extend(
            (
                await submit(
                    runtime, execution_state, "sell-a", monday, "600001", OrderSide.SELL, "200"
                ),
                await submit(
                    runtime, execution_state, "buy-c", monday, "600003", OrderSide.BUY, "1000"
                ),
                await submit(
                    runtime, execution_state, "invalid-lot", monday, "600004", OrderSide.BUY, "99"
                ),
            )
        )
        pit.statuses[(instrument("600004").canonical_key, monday)] = (
            InstrumentTradingState.SUSPENDED,
            at(monday, 6),
        )
        values.append(
            await submit(
                runtime, execution_state, "suspended", monday, "600004", OrderSide.BUY, "100"
            )
        )
        return pit, repository, execution_state, tuple(values)

    first_pit, first_repo, first_state, first = await replay()
    _, _, second_state, second = await replay()
    assert first == second
    assert first_state.account.cash == second_state.account.cash == Decimal("442172.8000")
    assert first_state.last_snapshot.nav.amount == Decimal("501972.8000")
    assert first_state.settlement.get(instrument("600001")) == second_state.settlement.get(
        instrument("600001")
    )
    assert first_state.settlement.get(instrument("600001")).sellable_quantity == Decimal("800")
    assert first_state.settlement.get(instrument("600003")).today_bought_quantity == Decimal("1000")
    assert first[2].risk_decision.reason_codes == (RiskReasonCode.INSUFFICIENT_SELLABLE_POSITION,)
    assert first[3].order.status is OrderStatus.FILLED
    assert RiskReasonCode.INVALID_LOT_SIZE in first[5].risk_decision.reason_codes
    assert RiskReasonCode.INSTRUMENT_SUSPENDED in first[6].risk_decision.reason_codes
    assert sum(value.fill is not None for value in first) == 4
    assert all(value.risk_decision.policy_version == "fixture-risk/v1" for value in first)
    assert any(event.event_type == "RISK_SNAPSHOT" for event in first[0].audit_events)
    assert (
        await first_repo.get_risk_decision(first[0].risk_decision.risk_decision_id)
        == first[0].risk_decision
    )
    assert all(context.as_of.tzinfo is not None for context in first_pit.contexts)


@pytest.mark.asyncio
async def test_weekend_and_closed_holiday_do_not_release_t1_until_next_open() -> None:
    pit = populated_fixture()
    runtime, execution_state = service(pit), state()
    friday, monday, thursday = date(2026, 8, 21), date(2026, 8, 24), date(2026, 8, 27)
    await submit(runtime, execution_state, "friday-buy", friday, "600001", OrderSide.BUY, "100")
    for closed in (date(2026, 8, 22), date(2026, 8, 23)):
        assert await runtime.advance_session(execution_state, Market.CN_SSE, at(closed)) is None
        assert execution_state.settlement.get(instrument("600001")).sellable_quantity == 0
    monday_event = await runtime.advance_session(execution_state, Market.CN_SSE, at(monday))
    assert monday_event is not None and monday_event.released_quantity == Decimal("100")
    await submit(runtime, execution_state, "monday-buy", monday, "600001", OrderSide.BUY, "100")
    for holiday in (date(2026, 8, 25), date(2026, 8, 26)):
        assert await runtime.advance_session(execution_state, Market.CN_SSE, at(holiday)) is None
        assert execution_state.settlement.get(instrument("600001")).sellable_quantity == Decimal(
            "100"
        )
    holiday_event = await runtime.advance_session(execution_state, Market.CN_SSE, at(thursday))
    assert holiday_event is not None and holiday_event.released_quantity == Decimal("100")
    assert execution_state.settlement.get(instrument("600001")).sellable_quantity == Decimal("200")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("10", RiskDecisionType.ALLOW),
        ("11.01", RiskDecisionType.REJECT),
        ("8.99", RiskDecisionType.REJECT),
    ],
)
async def test_price_limit_policy_controls_execution(requested, expected) -> None:
    pit = populated_fixture()
    outcome = await submit(
        service(pit),
        state(),
        f"price-{requested}",
        date(2026, 8, 21),
        "600001",
        OrderSide.BUY,
        "100",
        requested_price=requested,
        limit=band(date(2026, 8, 21), "9", "11"),
    )
    assert outcome.risk_decision.decision is expected
    if expected is RiskDecisionType.REJECT:
        assert RiskReasonCode.PRICE_OUTSIDE_LIMIT in outcome.risk_decision.reason_codes


@pytest.mark.asyncio
async def test_unknown_or_future_price_limit_is_conservatively_rejected() -> None:
    day = date(2026, 8, 21)
    pit = populated_fixture()
    runtime = service(pit)
    missing = await runtime.execute(
        state(),
        ExecutionOrderIntent(instrument("600001"), OrderSide.BUY, Quantity(Decimal("100"))),
        OrderId("missing-band"),
        at(day),
        None,
    )
    future = await runtime.execute(
        state(),
        ExecutionOrderIntent(instrument("600001"), OrderSide.BUY, Quantity(Decimal("100"))),
        OrderId("future-band"),
        at(day),
        PriceLimitBand(Decimal("9"), Decimal("11"), "future", at(day, 8)),
    )
    assert all(
        RiskReasonCode.PRICE_LIMIT_UNKNOWN in value.risk_decision.reason_codes
        for value in (missing, future)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "reason"),
    [
        ("not_listed", RiskReasonCode.INSTRUMENT_NOT_LISTED),
        ("delisted", RiskReasonCode.INSTRUMENT_DELISTED),
        ("unknown", RiskReasonCode.INSTRUMENT_STATUS_UNKNOWN),
    ],
)
async def test_instrument_lifecycle_is_a_conservative_gate(lifecycle, reason) -> None:
    pit = populated_fixture()
    pit.lifecycle[instrument("600001").canonical_key] = lifecycle
    outcome = await submit(
        service(pit),
        state(),
        f"lifecycle-{lifecycle}",
        date(2026, 8, 21),
        "600001",
        OrderSide.BUY,
        "100",
    )
    assert reason in outcome.risk_decision.reason_codes
    assert outcome.fill is None


@pytest.mark.asyncio
async def test_suspension_rejects_buy_and_sell_without_changing_position() -> None:
    friday, monday = date(2026, 8, 21), date(2026, 8, 24)
    pit = populated_fixture()
    runtime, execution_state = service(pit), state()
    await submit(runtime, execution_state, "seed-a", friday, "600001", OrderSide.BUY, "100")
    pit.statuses[(instrument("600001").canonical_key, monday)] = (
        InstrumentTradingState.SUSPENDED,
        at(monday, 6),
    )
    pit.statuses[(instrument("600004").canonical_key, monday)] = (
        InstrumentTradingState.SUSPENDED,
        at(monday, 6),
    )
    sell = await submit(
        runtime, execution_state, "suspended-sell", monday, "600001", OrderSide.SELL, "100"
    )
    buy = await submit(
        runtime, execution_state, "suspended-buy", monday, "600004", OrderSide.BUY, "100"
    )
    assert all(
        RiskReasonCode.INSTRUMENT_SUSPENDED in value.risk_decision.reason_codes
        for value in (sell, buy)
    )
    assert execution_state.account.positions[instrument("600001").canonical_key].quantity == 100


@pytest.mark.asyncio
async def test_future_status_and_bar_are_never_borrowed() -> None:
    day = date(2026, 8, 21)
    pit = populated_fixture()
    pit.statuses[(instrument("600001").canonical_key, day)] = (
        InstrumentTradingState.TRADING,
        at(day, 8),
    )
    future_status = await submit(
        service(pit), state(), "future-status", day, "600001", OrderSide.BUY, "100"
    )
    assert RiskReasonCode.INSTRUMENT_STATUS_UNKNOWN in future_status.risk_decision.reason_codes
    pit = populated_fixture()
    pit.prices[(instrument("600001").canonical_key, day)] = (Decimal("10"), at(day, 8))
    future_bar = await submit(
        service(pit), state(), "future-bar", day, "600001", OrderSide.BUY, "100"
    )
    assert RiskReasonCode.PIT_DATA_UNAVAILABLE in future_bar.risk_decision.reason_codes


@pytest.mark.asyncio
async def test_closed_or_unknown_calendar_is_rejected() -> None:
    pit = populated_fixture()
    closed = await submit(
        service(pit), state(), "closed", date(2026, 8, 22), "600001", OrderSide.BUY, "100"
    )
    unknown = await submit(
        service(pit), state(), "unknown-calendar", date(2026, 8, 28), "600001", OrderSide.BUY, "100"
    )
    assert RiskReasonCode.MARKET_CLOSED in closed.risk_decision.reason_codes
    assert RiskReasonCode.PIT_DATA_UNAVAILABLE in unknown.risk_decision.reason_codes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "order_id", "symbol", "quantity", "reason"),
    [
        (
            RiskPolicyConfig(Decimal("0.2"), Decimal("1")),
            "concentration",
            "600001",
            "12500",
            RiskReasonCode.SINGLE_POSITION_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("0.1")),
            "gross",
            "600001",
            "6000",
            RiskReasonCode.GROSS_EXPOSURE_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("1"), minimum_cash_buffer_pct=Decimal("0.9")),
            "cash-buffer",
            "600001",
            "6000",
            RiskReasonCode.CASH_BUFFER_LIMIT,
        ),
    ],
)
async def test_configured_portfolio_risk_limits_reject(
    config, order_id, symbol, quantity, reason
) -> None:
    outcome = await submit(
        service(populated_fixture(), config=config),
        state(),
        order_id,
        date(2026, 8, 21),
        symbol,
        OrderSide.BUY,
        quantity,
    )
    assert reason in outcome.risk_decision.reason_codes
    assert outcome.order.status is OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_daily_order_fill_and_turnover_guards_are_deterministic() -> None:
    day = date(2026, 8, 21)
    order_limited = service(
        populated_fixture(),
        config=RiskPolicyConfig(Decimal("1"), Decimal("1"), max_orders_per_day=1),
    )
    order_state = state()
    assert (
        await submit(order_limited, order_state, "first", day, "600001", OrderSide.BUY, "100")
    ).fill
    second = await submit(order_limited, order_state, "second", day, "600002", OrderSide.BUY, "100")
    assert RiskReasonCode.TRADE_FREQUENCY_LIMIT in second.risk_decision.reason_codes

    turnover_limited = service(
        populated_fixture(),
        config=RiskPolicyConfig(Decimal("1"), Decimal("1"), max_daily_turnover_pct=Decimal("0.03")),
    )
    turnover_state = state()
    await submit(
        turnover_limited, turnover_state, "turnover-1", day, "600001", OrderSide.BUY, "1000"
    )
    turnover = await submit(
        turnover_limited, turnover_state, "turnover-2", day, "600002", OrderSide.BUY, "1000"
    )
    assert RiskReasonCode.TRADE_FREQUENCY_LIMIT in turnover.risk_decision.reason_codes

    fill_limited = service(
        populated_fixture(),
        config=RiskPolicyConfig(Decimal("1"), Decimal("1"), max_filled_orders_per_day=1),
    )
    fill_state = state()
    await submit(fill_limited, fill_state, "fill-1", day, "600001", OrderSide.BUY, "100")
    fill_guard = await submit(
        fill_limited, fill_state, "fill-2", day, "600002", OrderSide.BUY, "100"
    )
    assert RiskReasonCode.TRADE_FREQUENCY_LIMIT in fill_guard.risk_decision.reason_codes


@pytest.mark.asyncio
async def test_missing_current_position_mark_rejects_without_latest_fallback() -> None:
    friday, monday = date(2026, 8, 21), date(2026, 8, 24)
    pit = populated_fixture()
    runtime, execution_state = service(pit), state()
    await submit(runtime, execution_state, "buy-a", friday, "600001", OrderSide.BUY, "100")
    del pit.prices[(instrument("600001").canonical_key, monday)]
    outcome = await submit(
        runtime, execution_state, "buy-b", monday, "600002", OrderSide.BUY, "100"
    )
    assert RiskReasonCode.PIT_DATA_UNAVAILABLE in outcome.risk_decision.reason_codes
    assert outcome.fill is None


@pytest.mark.asyncio
async def test_sell_without_position_is_rejected_without_shorting() -> None:
    outcome = await submit(
        service(populated_fixture()),
        state(),
        "naked-sell",
        date(2026, 8, 21),
        "600001",
        OrderSide.SELL,
        "100",
    )
    assert set(outcome.risk_decision.reason_codes) >= {
        RiskReasonCode.INSUFFICIENT_POSITION,
        RiskReasonCode.INSUFFICIENT_SELLABLE_POSITION,
    }
    assert outcome.fill is None
