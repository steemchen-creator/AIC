from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from aic_backend.application.backtest import (
    DeterministicBacktestEngine,
    OrderIntent,
    ScriptedDecisionSource,
)
from aic_backend.application.point_in_time import PointInTimeDataResult
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.models import (
    BacktestErrorCode,
    BacktestRun,
    BacktestRunId,
    Money,
    OrderSide,
    PortfolioError,
    PortfolioId,
    Quantity,
)
from aic_backend.domain.portfolio.policies import ConfigurableFeePolicy, FixedBpsSlippagePolicy
from aic_backend.infrastructure.backtest_persistence import InMemoryBacktestRepository


@dataclass(frozen=True)
class Session:
    session_close: datetime


@dataclass(frozen=True)
class Day:
    trading_date: date
    is_open: bool
    session: Session


@dataclass(frozen=True)
class Bar:
    trading_date: date
    close: Decimal


@dataclass(frozen=True)
class Persisted:
    record: Bar
    available_at: datetime


class PitOnlyFixture:
    def __init__(self, prices: dict[tuple[str, date], tuple[Decimal, datetime]]) -> None:
        self.prices = prices
        self.calls: list[tuple[str, datetime]] = []

    async def list_calendar_as_of(self, market, start, end, context):
        days = []
        current = start
        while current <= end:
            close = datetime.combine(current, time(15), UTC)
            days.append(Day(current, True, Session(close)))
            current = current.fromordinal(current.toordinal() + 1)
        return PointInTimeDataResult(tuple(days), (), (), context.policy_version)

    async def get_daily_bars_as_of(self, instrument, start, end, context):
        self.calls.append((instrument.canonical_key, context.as_of))
        item = self.prices.get((instrument.canonical_key, start))
        records = ()
        decisions = ()
        if item is not None:
            price, available_at = item
            decisions = (object(),)
            if available_at <= context.as_of:
                records = (Persisted(Bar(start, price), available_at),)
        return PointInTimeDataResult(records, decisions, (), context.policy_version)


class EmptyCalendarFixture(PitOnlyFixture):
    async def list_calendar_as_of(self, market, start, end, context):
        return PointInTimeDataResult((), (), (), context.policy_version)


def instrument(symbol: str) -> InstrumentIdentity:
    return InstrumentIdentity(Market.CN_SSE, symbol, InstrumentType.EQUITY)


def run() -> BacktestRun:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    return BacktestRun(
        BacktestRunId("run-1"),
        PortfolioId("portfolio-1"),
        start,
        datetime(2026, 1, 7, 23, tzinfo=UTC),
        Money(Decimal("500000")),
        "point-in-time-availability/v1",
        "configurable-fee/v1",
        "fixed-bps-slippage/v1",
        "daily-close-fill/v1",
        start,
    )


def fixture(future_a: bool = False) -> PitOnlyFixture:
    values: dict[tuple[str, date], tuple[Decimal, datetime]] = {}
    prices = {
        "600001": ("10", "11", "12"),
        "600002": ("20", "19", "21"),
        "600003": ("5", "6", "7"),
        "000300": ("100", "102", "103"),
    }
    for symbol, series in prices.items():
        for offset, value in enumerate(series):
            day = date(2026, 1, 5 + offset)
            available = datetime(2026, 1, 5 + offset, 14, tzinfo=UTC)
            if future_a and symbol == "600001" and offset == 0:
                available = datetime(2026, 1, 6, 14, tzinfo=UTC)
            values[(instrument(symbol).canonical_key, day)] = (Decimal(value), available)
    return PitOnlyFixture(values)


def decisions() -> ScriptedDecisionSource:
    return ScriptedDecisionSource(
        (
            OrderIntent(
                date(2026, 1, 5), instrument("600001"), OrderSide.BUY, Quantity(Decimal("1000"))
            ),
            OrderIntent(
                date(2026, 1, 5), instrument("600002"), OrderSide.BUY, Quantity(Decimal("1000"))
            ),
            OrderIntent(
                date(2026, 1, 5), instrument("600003"), OrderSide.BUY, Quantity(Decimal("1000"))
            ),
            OrderIntent(
                date(2026, 1, 7), instrument("600001"), OrderSide.SELL, Quantity(Decimal("200"))
            ),
        )
    )


@pytest.mark.asyncio
async def test_three_position_replay_is_deterministic_auditable_and_cost_transparent() -> None:
    fee = ConfigurableFeePolicy(Decimal("0.0003"), Decimal("5"), Decimal("0.001"))
    slip = FixedBpsSlippagePolicy(Decimal("5"))
    first_repo, second_repo = InMemoryBacktestRepository(), InMemoryBacktestRepository()
    first = await DeterministicBacktestEngine(fixture(), fee, slip, first_repo).execute(
        run(), Market.CN_SSE, decisions(), instrument("000300")
    )
    second = await DeterministicBacktestEngine(fixture(), fee, slip, second_repo).execute(
        run(), Market.CN_SSE, decisions(), instrument("000300")
    )
    assert first == second
    assert len(first.nav_snapshots[0].positions) == 3
    assert first.result.initial_capital == Money(Decimal("500000"))
    assert first.result.trade_count == 4
    assert first.result.fee_total.amount > 0
    assert first.result.tax_total.amount > 0
    assert first.result.slippage_total.amount > 0
    assert (
        first.result.gross_result.amount - first.result.net_result.amount
        == first.result.fee_total.amount
        + first.result.tax_total.amount
        + first.result.slippage_total.amount
    )
    assert first.result.final_nav.amount == first.nav_snapshots[-1].nav.amount
    assert first.result.total_return == first.result.net_result.amount / Decimal("500000")
    assert tuple(event.event_id for event in first.audit_events) == tuple(
        event.event_id for event in second.audit_events
    )
    assert await first_repo.get_result("run-1") == first.result


@pytest.mark.asyncio
async def test_future_bar_is_never_borrowed_for_trade_or_mark() -> None:
    engine = DeterministicBacktestEngine(
        fixture(future_a=True), ConfigurableFeePolicy(), FixedBpsSlippagePolicy()
    )
    with pytest.raises(PortfolioError) as error:
        await engine.execute(run(), Market.CN_SSE, decisions(), instrument("000300"))
    assert error.value.code is BacktestErrorCode.PIT_DATA_UNAVAILABLE


@pytest.mark.asyncio
async def test_policy_mismatch_and_missing_market_data_are_explicit() -> None:
    base = run()
    wrong = BacktestRun(
        base.run_id,
        base.portfolio_id,
        base.start,
        base.end,
        base.initial_capital,
        "wrong",
        base.fee_policy_version,
        base.slippage_policy_version,
        base.execution_policy_version,
        base.created_at,
    )
    engine = DeterministicBacktestEngine(
        fixture(), ConfigurableFeePolicy(), FixedBpsSlippagePolicy()
    )
    with pytest.raises(PortfolioError) as policy_error:
        await engine.execute(wrong, Market.CN_SSE, decisions(), instrument("000300"))
    assert policy_error.value.code is BacktestErrorCode.POLICY_FAILURE
    missing = ScriptedDecisionSource(
        (
            OrderIntent(
                date(2026, 1, 5), instrument("699999"), OrderSide.BUY, Quantity(Decimal("1"))
            ),
        )
    )
    with pytest.raises(PortfolioError) as data_error:
        await engine.execute(base, Market.CN_SSE, missing, instrument("000300"))
    assert data_error.value.code is BacktestErrorCode.MARKET_DATA_UNAVAILABLE


@pytest.mark.asyncio
async def test_empty_calendar_and_missing_benchmark_are_structured() -> None:
    empty = DeterministicBacktestEngine(
        EmptyCalendarFixture({}), ConfigurableFeePolicy(), FixedBpsSlippagePolicy()
    )
    with pytest.raises(PortfolioError) as calendar_error:
        await empty.execute(run(), Market.CN_SSE, ScriptedDecisionSource(()), instrument("000300"))
    assert calendar_error.value.code is BacktestErrorCode.PIT_DATA_UNAVAILABLE
    values = fixture()
    values.prices = {key: value for key, value in values.prices.items() if "000300" not in key[0]}
    result = await DeterministicBacktestEngine(
        values, ConfigurableFeePolicy(), FixedBpsSlippagePolicy()
    ).execute(run(), Market.CN_SSE, ScriptedDecisionSource(()), instrument("000300"))
    assert result.result.benchmark_return == Decimal("0")
    assert len(result.result.warnings) == 3
