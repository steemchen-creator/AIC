from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.application.etf import ETFPointInTimeService
from aic_backend.application.execution import (
    AShareExecutionService,
    ExecutionOrderIntent,
    ExecutionState,
)
from aic_backend.application.paper import PaperTradingRuntime, ScriptedPaperDecisionSource
from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityDecision,
    AvailabilityMode,
    DataAvailabilityPolicy,
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
    Currency,
    InstrumentExecutionProfile,
    InstrumentIdentity,
    InstrumentTradingState,
    InstrumentType,
    Market,
    SettlementCapability,
    standard_a_share_session,
)
from aic_backend.domain.paper import ActivatePaperAccount, PaperOrderIntent
from aic_backend.domain.portfolio.models import (
    Money,
    OrderId,
    OrderSide,
    PortfolioId,
    Price,
    Quantity,
)
from aic_backend.domain.portfolio.policies import (
    ConfigurableFeePolicy,
    ConfiguredAssetFeePolicy,
    FixedBpsSlippagePolicy,
)
from aic_backend.infrastructure.etf_persistence import InMemoryETFDataRepository
from aic_backend.infrastructure.paper_persistence import InMemoryPaperTradingRepository

DAY = date(2026, 9, 4)
ETF_T0 = InstrumentIdentity(Market.CN_SSE, "513100", InstrumentType.ETF)
ETF_T1 = InstrumentIdentity(Market.CN_SSE, "510300", InstrumentType.ETF)
QDII = InstrumentIdentity(Market.CN_SZSE, "159941", InstrumentType.ETF)
EQUITY = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)
INDEX = InstrumentIdentity(Market.INDEX_REFERENCE, "NDX", InstrumentType.INDEX)


@dataclass(frozen=True)
class Session:
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
class Stored:
    record: Bar


class PitFixture:
    def __init__(self) -> None:
        self.values: dict[tuple[InstrumentIdentity, date], Decimal] = {}
        self.open_days: set[date] = set()

    def add(self, instrument: InstrumentIdentity, day: date, price: str) -> None:
        self.values[(instrument, day)] = Decimal(price)
        self.open_days.add(day)

    async def list_calendar_as_of(self, market, start, end, context):
        del market, end
        records = (
            (Session(start, True, standard_a_share_session(start)),)
            if start in self.open_days
            else ()
        )
        return PointInTimeDataResult(records, (), (), context.policy_version)

    async def list_instruments_as_of(self, lifecycle_date, context, market=None):
        del lifecycle_date
        instruments = tuple(
            sorted(
                {
                    instrument
                    for instrument, _ in self.values
                    if market is None or instrument.market is market
                },
                key=lambda value: value.canonical_key,
            )
        )
        decisions = tuple(
            AvailabilityDecision(
                instrument.canonical_key,
                AvailabilityClassification.AVAILABLE,
                context.as_of,
                "fixture",
                context.policy_version,
            )
            for instrument in instruments
        )
        return PointInTimeDataResult(instruments, decisions, (), context.policy_version)

    async def list_trading_status_as_of(self, instrument, start, end, context):
        del end
        if (instrument, start) not in self.values:
            return PointInTimeDataResult((), (), (), context.policy_version)
        return PointInTimeDataResult(
            (Status(start, InstrumentTradingState.TRADING),), (), (), context.policy_version
        )

    async def get_daily_bars_as_of(self, instrument, start, end, context):
        del end
        price = self.values.get((instrument, start))
        records = () if price is None else (Stored(Bar(start, price, price)),)
        return PointInTimeDataResult(records, (), (), context.policy_version)

    async def list_corporate_actions_as_of(self, instrument, start, end, context):
        del instrument, start, end
        return PointInTimeDataResult((), (), (), context.policy_version)


def at(day: date, hour: int = 7) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def profile(
    instrument: InstrumentIdentity,
    settlement: SettlementCapability,
) -> InstrumentExecutionProfile:
    return InstrumentExecutionProfile(
        f"{instrument.canonical_key}:{settlement.value}",
        instrument,
        Currency.CNY,
        100,
        settlement,
        "exchange-product-rule/v1",
        instrument.market,
        "fixture://exchange-rule",
        at(DAY, 5),
        DAY,
        "etf-execution/v1",
    )


def asset_fees() -> ConfiguredAssetFeePolicy:
    return ConfiguredAssetFeePolicy(
        {
            InstrumentType.EQUITY: ConfigurableFeePolicy(
                Decimal("0"), Decimal("0"), Decimal("0.001"), "equity-fee/v1"
            ),
            InstrumentType.ETF: ConfigurableFeePolicy(
                Decimal("0"), Decimal("0"), Decimal("0"), "etf-fee/v1"
            ),
        },
        "asset-fee/v1",
    )


def test_etf_fee_policy_keeps_decimal_costs_and_net_pnl_exact() -> None:
    policy = ConfiguredAssetFeePolicy(
        {
            InstrumentType.EQUITY: ConfigurableFeePolicy(
                Decimal("0.0003"), Decimal("5"), Decimal("0.001")
            ),
            InstrumentType.ETF: ConfigurableFeePolicy(
                Decimal("0.0001"), Decimal("1"), Decimal("0"), "etf-fee/v1"
            ),
        }
    )
    quantity = Quantity(Decimal("100"))
    buy_commission, buy_tax = policy.calculate_for(
        ETF_T0, OrderSide.BUY, quantity, Price(Decimal("10"))
    )
    sell_commission, sell_tax = policy.calculate_for(
        ETF_T0, OrderSide.SELL, quantity, Price(Decimal("10.5"))
    )
    net_pnl = Decimal("50") - buy_commission.amount - sell_commission.amount
    assert (buy_commission.amount, sell_commission.amount) == (Decimal("1"), Decimal("1.0"))
    assert buy_tax.amount == sell_tax.amount == Decimal("0")
    assert net_pnl == Decimal("48.0")
    with pytest.raises(ValueError, match="asset class"):
        policy.calculate_for(INDEX, OrderSide.BUY, quantity, Price(Decimal("1")))
    with pytest.raises(ValueError, match="version"):
        ConfiguredAssetFeePolicy(policy.profiles, " ")


def state() -> ExecutionState:
    return ExecutionState.initialize(
        PortfolioId("mixed-portfolio"), Money(Decimal("100000")), at(DAY - timedelta(days=1))
    )


def band(day: date) -> PriceLimitBand:
    return PriceLimitBand(Decimal("0.1"), Decimal("100"), "fixture-limit/v1", at(day, 5))


def service(
    pit: PitFixture,
    etf_repository: InMemoryETFDataRepository,
    *,
    operational: bool = False,
) -> AShareExecutionService:
    return AShareExecutionService(
        pit,  # type: ignore[arg-type]
        ConfigurableFeePolicy(),
        FixedBpsSlippagePolicy(),
        PreTradeRiskPolicy(RiskPolicyConfig(Decimal("1"), Decimal("1"))),
        etf_point_in_time=ETFPointInTimeService(etf_repository, DataAvailabilityPolicy()),
        asset_fee_policy=asset_fees(),
        availability_mode=(
            AvailabilityMode.OPERATIONAL_REPLAY
            if operational
            else AvailabilityMode.HISTORICAL_RESEARCH
        ),
        reference_price_field="open" if operational else "close",
        execution_policy_version="next-session-open/v1" if operational else None,
    )


async def submit(
    runtime: AShareExecutionService,
    execution_state: ExecutionState,
    instrument: InstrumentIdentity,
    side: OrderSide,
    day: date,
    order_id: str,
    quantity: str = "100",
):
    return await runtime.execute(
        execution_state,
        ExecutionOrderIntent(instrument, side, Quantity(Decimal(quantity))),
        OrderId(order_id),
        at(day),
        band(day),
    )


@pytest.mark.asyncio
async def test_t0_etf_can_sell_same_day_and_records_asset_policy_versions() -> None:
    pit, repository = PitFixture(), InMemoryETFDataRepository()
    pit.add(ETF_T0, DAY, "10")
    await repository.save_execution_profile(profile(ETF_T0, SettlementCapability.T0))
    runtime, execution_state = service(pit, repository), state()
    buy = await submit(runtime, execution_state, ETF_T0, OrderSide.BUY, DAY, "t0-buy")
    sell = await submit(runtime, execution_state, ETF_T0, OrderSide.SELL, DAY, "t0-sell")
    assert buy.risk_decision.decision is sell.risk_decision.decision is RiskDecisionType.ALLOW
    assert buy.settlement_position is not None
    assert buy.settlement_position.sellable_quantity == Decimal("100")
    assert sell.fill is not None and sell.fill.tax.amount == 0
    assert sell.metadata["settlement_capability"] == "T0"
    assert sell.metadata["fee_policy_version"] == "asset-fee/v1"
    assert sell.policy_versions.lot == "etf-execution/v1/lot"
    assert sell.policy_versions.settlement.endswith("/T0")


@pytest.mark.asyncio
async def test_t1_etf_blocks_same_day_sell_then_releases_on_next_open_day() -> None:
    next_day = DAY + timedelta(days=3)
    pit, repository = PitFixture(), InMemoryETFDataRepository()
    pit.add(ETF_T1, DAY, "4")
    pit.add(ETF_T1, next_day, "4.1")
    await repository.save_execution_profile(profile(ETF_T1, SettlementCapability.T1))
    runtime, execution_state = service(pit, repository), state()
    await submit(runtime, execution_state, ETF_T1, OrderSide.BUY, DAY, "t1-buy")
    same_day = await submit(runtime, execution_state, ETF_T1, OrderSide.SELL, DAY, "t1-sell")
    next_open = await submit(
        runtime, execution_state, ETF_T1, OrderSide.SELL, next_day, "t1-next-open"
    )
    assert RiskReasonCode.INSUFFICIENT_SELLABLE_POSITION in same_day.risk_decision.reason_codes
    assert next_open.risk_decision.decision is RiskDecisionType.ALLOW
    assert next_open.metadata["settlement_capability"] == "T1"


@pytest.mark.asyncio
async def test_unknown_profile_missing_profile_lot_and_index_all_fail_closed() -> None:
    pit, repository = PitFixture(), InMemoryETFDataRepository()
    for value in (ETF_T0, ETF_T1):
        pit.add(value, DAY, "10")
    await repository.save_execution_profile(profile(ETF_T0, SettlementCapability.UNKNOWN))
    runtime = service(pit, repository)
    unknown = await submit(runtime, state(), ETF_T0, OrderSide.BUY, DAY, "unknown")
    missing = await submit(runtime, state(), ETF_T1, OrderSide.BUY, DAY, "missing")
    invalid_lot = await submit(
        runtime, state(), ETF_T0, OrderSide.BUY, DAY, "invalid-lot", "99"
    )
    index = await submit(runtime, state(), INDEX, OrderSide.BUY, DAY, "index")
    assert RiskReasonCode.UNSUPPORTED_RULE in unknown.risk_decision.reason_codes
    assert RiskReasonCode.UNSUPPORTED_RULE in missing.risk_decision.reason_codes
    assert RiskReasonCode.INVALID_LOT_SIZE in invalid_lot.risk_decision.reason_codes
    assert index.risk_decision.reason_codes == (
        RiskReasonCode.NON_TRADABLE_REFERENCE_INSTRUMENT,
    )
    assert index.metadata["instrument_type"] == "INDEX"


@pytest.mark.asyncio
async def test_mixed_equity_domestic_etf_and_nasdaq_qdii_portfolio_is_cny_cash_only() -> None:
    pit, repository = PitFixture(), InMemoryETFDataRepository()
    for value, price in ((EQUITY, "10"), (ETF_T1, "4"), (QDII, "2")):
        pit.add(value, DAY, price)
    await repository.save_execution_profile(profile(ETF_T1, SettlementCapability.T1))
    await repository.save_execution_profile(profile(QDII, SettlementCapability.T0))
    runtime, execution_state = service(pit, repository), state()
    outcomes = (
        await submit(runtime, execution_state, EQUITY, OrderSide.BUY, DAY, "equity"),
        await submit(runtime, execution_state, ETF_T1, OrderSide.BUY, DAY, "domestic-etf"),
        await submit(runtime, execution_state, QDII, OrderSide.BUY, DAY, "nasdaq-qdii"),
    )
    assert all(value.risk_decision.decision is RiskDecisionType.ALLOW for value in outcomes)
    asset_types = {
        item.instrument.instrument_type for item in execution_state.last_snapshot.positions
    }
    assert asset_types == {
        InstrumentType.EQUITY,
        InstrumentType.ETF,
    }
    assert execution_state.last_snapshot.cash.amount == Decimal("98400")


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class Readiness:
    async def check(self, account, as_of):
        del account, as_of
        return ()


class Bands:
    async def get_band(self, instrument, trading_date, as_of):
        del instrument
        return PriceLimitBand(Decimal("0.1"), Decimal("100"), "paper-band/v1", as_of)


@pytest.mark.asyncio
async def test_champion_paper_runtime_holds_equity_domestic_and_nasdaq_qdii_etf() -> None:
    pit, etf_repository = PitFixture(), InMemoryETFDataRepository()
    for value, price in ((EQUITY, "10"), (ETF_T1, "4"), (QDII, "2"), (INDEX, "100")):
        pit.add(value, DAY, price)
    await etf_repository.save_execution_profile(profile(ETF_T1, SettlementCapability.T1))
    await etf_repository.save_execution_profile(profile(QDII, SettlementCapability.T0))
    paper_repository = InMemoryPaperTradingRepository()
    clock = Clock(at(DAY, 8))
    paper = PaperTradingRuntime(
        pit,  # type: ignore[arg-type]
        service(pit, etf_repository, operational=True),
        paper_repository,
        Readiness(),
        Bands(),
        clock,
        INDEX,
    )
    account = await paper.create_champion()
    await paper.activate(ActivatePaperAccount(account.account_id, clock.now()))
    intents = tuple(
        PaperOrderIntent(
            f"paper-{instrument.symbol}",
            account.account_id,
            at(DAY - timedelta(days=1), 8),
            DAY,
            instrument,
            OrderSide.BUY,
            Quantity(Decimal("100")),
            "fixture:spec009",
        )
        for instrument in (EQUITY, ETF_T1, QDII)
    )
    result = await paper.process_session(
        account.account_id,
        DAY,
        ScriptedPaperDecisionSource("fixture:spec009", intents),
    )
    assert result is not None
    assert all(outcome.fill is not None for outcome in result.outcomes)
    saved = await paper_repository.get(account.account_id)
    assert saved is not None
    assert {item.key.instrument for item in saved.portfolio_state.positions} == {
        EQUITY,
        ETF_T1,
        QDII,
    }
    assert saved.performance[-1].nav.amount == Decimal("500000")
    assert saved.performance[-1].position_count == 3
    assert all(
        outcome.metadata["instrument_type"] in {"EQUITY", "ETF"}
        for outcome in saved.outcomes
    )
