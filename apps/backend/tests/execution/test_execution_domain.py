from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.domain.execution import (
    AShareBoardLotPolicy,
    ExecutionOutcome,
    ExecutionPolicyVersions,
    ExplicitPriceLimitPolicy,
    PreTradeRiskInput,
    PreTradeRiskPolicy,
    PriceLimitBand,
    PriceLimitClassification,
    RiskDecision,
    RiskDecisionType,
    RiskInputSummary,
    RiskPolicyConfig,
    RiskReasonCode,
    RiskSnapshot,
    SettlementBook,
    SettlementPosition,
    SettlementRolloverEvent,
    TradingEligibility,
)
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.models import (
    Fill,
    FillId,
    Money,
    Order,
    OrderId,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioId,
    PortfolioSnapshot,
    PositionSnapshot,
    Price,
    Quantity,
)

NOW = datetime(2026, 8, 21, 7, tzinfo=UTC)
PORTFOLIO = PortfolioId("portfolio-domain")
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600001", InstrumentType.EQUITY)


def snapshot(
    *, cash: str = "800", quantity: str = "10", mark: str = "20", nav: str = "1000"
) -> PortfolioSnapshot:
    position = PositionSnapshot(
        INSTRUMENT,
        Decimal(quantity),
        Decimal("18"),
        Decimal(mark),
        Decimal(quantity) * Decimal(mark),
        Decimal("20"),
        Decimal("0"),
    )
    return PortfolioSnapshot(
        PORTFOLIO,
        NOW,
        Money(Decimal(cash)),
        (position,),
        Money(Decimal(quantity) * Decimal(mark)),
        Money(Decimal("0")),
        Money(Decimal("20")),
        Money(Decimal(nav)),
    )


def risk_input(**overrides) -> PreTradeRiskInput:
    values = {
        "snapshot": snapshot(),
        "instrument": INSTRUMENT,
        "side": OrderSide.BUY,
        "quantity": Quantity(Decimal("10")),
        "price": Price(Decimal("10")),
        "eligibility": TradingEligibility(True, True, False, False, True),
        "as_of": NOW,
        "transaction_cost": Decimal("0"),
        "sellable_quantity": Decimal("10"),
        "orders_today": 0,
        "filled_orders_today": 0,
        "daily_turnover": Decimal("0"),
    }
    values.update(overrides)
    return PreTradeRiskInput(**values)


def test_lot_and_price_limit_policies_are_explicit_and_replaceable() -> None:
    lot = AShareBoardLotPolicy()
    assert lot.validate(OrderSide.BUY, Quantity(Decimal("100")))
    assert not lot.validate(OrderSide.BUY, Quantity(Decimal("99")))
    assert not lot.validate(OrderSide.BUY, Quantity(Decimal("100.5")))
    assert lot.validate(OrderSide.SELL, Quantity(Decimal("17")))
    with pytest.raises(ValueError):
        Quantity(Decimal("0"))
    with pytest.raises(ValueError):
        Quantity(Decimal("-1"))
    with pytest.raises(ValueError):
        AShareBoardLotPolicy(0)

    limits = ExplicitPriceLimitPolicy()
    band = PriceLimitBand(Decimal("9"), Decimal("11"), "prior-close", NOW)
    assert limits.classify(Price(Decimal("11.01")), band) is PriceLimitClassification.UPPER_LIMIT
    assert limits.classify(Price(Decimal("8.99")), band) is PriceLimitClassification.LOWER_LIMIT
    assert limits.classify(Price(Decimal("10")), band) is PriceLimitClassification.WITHIN_LIMIT
    assert limits.classify(Price(Decimal("10")), None) is PriceLimitClassification.UNKNOWN_LIMIT


@pytest.mark.parametrize(
    "args",
    [
        (Decimal("0"), Decimal("11"), "source", NOW),
        (Decimal("12"), Decimal("11"), "source", NOW),
        (Decimal("9"), Decimal("11"), " ", NOW),
        (Decimal("9"), Decimal("11"), "source", datetime(2026, 1, 1)),
    ],
)
def test_price_limit_band_rejects_invalid_evidence(args) -> None:
    with pytest.raises(ValueError):
        PriceLimitBand(*args)


def test_settlement_book_enforces_t1_and_stable_open_day_rollover() -> None:
    book = SettlementBook(PORTFOLIO)
    assert book.get(INSTRUMENT).total_quantity == 0
    first = book.rollover(date(2026, 8, 21), NOW)
    assert first is not None and first.released_quantity == 0
    fill = Fill(
        FillId("fill-buy"),
        OrderId("order-buy"),
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("117")),
        Price(Decimal("10")),
        NOW,
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        "execution/v1",
    )
    position = book.apply_fill(fill)
    assert position == SettlementPosition(INSTRUMENT, Decimal("117"), Decimal("0"), Decimal("117"))
    assert book.rollover(date(2026, 8, 22), NOW) is not None
    assert book.get(INSTRUMENT).sellable_quantity == Decimal("117")
    assert book.rollover(date(2026, 8, 22), NOW) is None

    sell = Fill(
        FillId("fill-sell"),
        OrderId("order-sell"),
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.SELL,
        Quantity(Decimal("17")),
        Price(Decimal("10")),
        NOW,
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        "execution/v1",
    )
    assert book.apply_fill(sell).sellable_quantity == Decimal("100")
    with pytest.raises(ValueError):
        book.apply_fill(
            Fill(
                FillId("fill-too-large"),
                OrderId("order-too-large"),
                PORTFOLIO,
                INSTRUMENT,
                OrderSide.SELL,
                Quantity(Decimal("101")),
                Price(Decimal("10")),
                NOW,
                Money(Decimal("0")),
                Money(Decimal("0")),
                Money(Decimal("0")),
                "execution/v1",
            )
        )


def test_settlement_position_and_seed_validate_invariants() -> None:
    book = SettlementBook(PORTFOLIO)
    value = SettlementPosition(INSTRUMENT, Decimal("10"), Decimal("8"), Decimal("2"))
    book.seed(value)
    with pytest.raises(ValueError):
        book.seed(value)
    with pytest.raises(ValueError):
        SettlementPosition(INSTRUMENT, Decimal("1"), Decimal("1"), Decimal("1"))
    with pytest.raises(ValueError):
        SettlementPosition(INSTRUMENT, Decimal("1.5"), Decimal("0"), Decimal("0"))
    with pytest.raises(ValueError):
        SettlementRolloverEvent("", PORTFOLIO, date(2026, 8, 21), NOW, Decimal("0"), "v")
    with pytest.raises(ValueError):
        SettlementRolloverEvent("event", PORTFOLIO, date(2026, 8, 21), NOW, Decimal("-1"), "v")
    with pytest.raises(ValueError):
        SettlementRolloverEvent("event", PORTFOLIO, date(2026, 8, 21), NOW, Decimal("0"), " ")
    with pytest.raises(ValueError):
        ExecutionPolicyVersions("", "lot", "limit", "settlement", "risk")


@pytest.mark.parametrize(
    ("config", "value", "expected"),
    [
        (
            RiskPolicyConfig(Decimal("0.2"), Decimal("1")),
            risk_input(quantity=Quantity(Decimal("10")), price=Price(Decimal("10"))),
            RiskReasonCode.SINGLE_POSITION_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("0.25")),
            risk_input(quantity=Quantity(Decimal("10")), price=Price(Decimal("10"))),
            RiskReasonCode.GROSS_EXPOSURE_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("1"), minimum_cash_amount=Decimal("750")),
            risk_input(quantity=Quantity(Decimal("10")), price=Price(Decimal("10"))),
            RiskReasonCode.CASH_BUFFER_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("1"), max_orders_per_day=1),
            risk_input(orders_today=1),
            RiskReasonCode.TRADE_FREQUENCY_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("1"), max_filled_orders_per_day=1),
            risk_input(filled_orders_today=1),
            RiskReasonCode.TRADE_FREQUENCY_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("1"), max_daily_turnover_pct=Decimal("0.15")),
            risk_input(daily_turnover=Decimal("100")),
            RiskReasonCode.TRADE_FREQUENCY_LIMIT,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("1")),
            risk_input(
                side=OrderSide.SELL,
                quantity=Quantity(Decimal("11")),
                sellable_quantity=Decimal("10"),
            ),
            RiskReasonCode.INSUFFICIENT_SELLABLE_POSITION,
        ),
        (
            RiskPolicyConfig(Decimal("1"), Decimal("1")),
            risk_input(quantity=Quantity(Decimal("100")), price=Price(Decimal("10"))),
            RiskReasonCode.INSUFFICIENT_CASH,
        ),
    ],
)
def test_pre_trade_risk_guards(config, value, expected) -> None:
    assert expected in PreTradeRiskPolicy(config).evaluate(value)


def test_pre_trade_summary_and_zero_nav_behavior() -> None:
    policy = PreTradeRiskPolicy(RiskPolicyConfig(Decimal("1"), Decimal("1")))
    summary = policy.summarize(risk_input())
    assert summary.current_gross_exposure == Money(Decimal("200"))
    assert summary.post_trade_position_exposure == Money(Decimal("300"))
    zero = PortfolioSnapshot(
        PORTFOLIO,
        NOW,
        Money(Decimal("0")),
        (),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
    )
    assert policy.evaluate(risk_input(snapshot=zero)) == (RiskReasonCode.UNSUPPORTED_RULE,)
    restricted = risk_input(eligibility=TradingEligibility(False, False, True, True, False))
    assert set(policy.evaluate(restricted)) >= {
        RiskReasonCode.MARKET_CLOSED,
        RiskReasonCode.INSTRUMENT_NOT_LISTED,
        RiskReasonCode.INSTRUMENT_DELISTED,
        RiskReasonCode.INSTRUMENT_SUSPENDED,
        RiskReasonCode.INSTRUMENT_STATUS_UNKNOWN,
    }
    tiny = PortfolioSnapshot(
        PORTFOLIO,
        NOW,
        Money(Decimal("1")),
        (),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("1")),
    )
    assert RiskReasonCode.GROSS_EXPOSURE_LIMIT in policy.evaluate(
        risk_input(snapshot=tiny, transaction_cost=Decimal("2"))
    )
    with pytest.raises(ValueError):
        risk_input(as_of=datetime(2026, 8, 21))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_single_position_pct": Decimal("0")},
        {"max_gross_exposure_pct": Decimal("1.1")},
        {"minimum_cash_buffer_pct": Decimal("1.1")},
        {"minimum_cash_amount": Decimal("-1")},
        {"max_orders_per_day": 0},
        {"max_daily_turnover_pct": Decimal("0")},
        {"version": " "},
    ],
)
def test_risk_policy_config_rejects_unsafe_values(kwargs) -> None:
    values = {
        "max_single_position_pct": Decimal("1"),
        "max_gross_exposure_pct": Decimal("1"),
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        RiskPolicyConfig(**values)


def test_risk_decision_and_snapshot_are_immutable_validated_evidence() -> None:
    summary = RiskInputSummary(
        Money(Decimal("1000")),
        Money(Decimal("800")),
        Money(Decimal("200")),
        Money(Decimal("300")),
        Money(Decimal("300")),
        Money(Decimal("700")),
        0,
        0,
        Money(Decimal("0")),
    )
    value = RiskDecision(
        "risk-1",
        PORTFOLIO,
        OrderId("order-1"),
        NOW,
        RiskDecisionType.REJECT,
        (RiskReasonCode.INVALID_LOT_SIZE, RiskReasonCode.INVALID_LOT_SIZE),
        "risk/v1",
        summary,
    )
    assert value.reason_codes == (RiskReasonCode.INVALID_LOT_SIZE,)
    with pytest.raises(ValueError):
        RiskDecision("", PORTFOLIO, OrderId("o"), NOW, RiskDecisionType.ALLOW, (), "v", summary)
    with pytest.raises(ValueError):
        RiskDecision("r", PORTFOLIO, OrderId("o"), NOW, RiskDecisionType.ALLOW, (), " ", summary)
    with pytest.raises(ValueError):
        RiskDecision("r", PORTFOLIO, OrderId("o"), NOW, RiskDecisionType.REJECT, (), "v", summary)

    snapshot_value = RiskSnapshot(
        "snapshot-1",
        PORTFOLIO,
        NOW,
        Money(Decimal("1000")),
        Money(Decimal("800")),
        Money(Decimal("200")),
        Decimal("0.8"),
        Decimal("0.2"),
        1,
        Money(Decimal("100")),
        1,
        1,
        "risk/v1",
    )
    assert snapshot_value.position_count == 1
    with pytest.raises(ValueError):
        RiskSnapshot(
            "snapshot",
            PORTFOLIO,
            NOW,
            Money(Decimal("1000")),
            Money(Decimal("800")),
            Money(Decimal("200")),
            Decimal("1.1"),
            Decimal("0.2"),
            1,
            Money(Decimal("0")),
            0,
            0,
            "v",
        )

    valid_snapshot_args = (
        PORTFOLIO,
        NOW,
        Money(Decimal("1000")),
        Money(Decimal("800")),
        Money(Decimal("200")),
        Decimal("0.8"),
        Decimal("0.2"),
        1,
        Money(Decimal("0")),
        0,
        0,
        "risk/v1",
    )
    with pytest.raises(ValueError):
        RiskSnapshot("", *valid_snapshot_args)
    with pytest.raises(ValueError):
        RiskSnapshot(
            "snapshot",
            PORTFOLIO,
            NOW,
            Money(Decimal("0")),
            *valid_snapshot_args[3:],
        )
    with pytest.raises(ValueError):
        RiskSnapshot(
            "snapshot",
            PORTFOLIO,
            NOW,
            Money(Decimal("1000")),
            Money(Decimal("800")),
            Money(Decimal("200")),
            Decimal("0.8"),
            Decimal("1.1"),
            1,
            Money(Decimal("0")),
            0,
            0,
            "risk/v1",
        )
    with pytest.raises(ValueError):
        RiskSnapshot(
            "snapshot",
            PORTFOLIO,
            NOW,
            Money(Decimal("1000")),
            Money(Decimal("800")),
            Money(Decimal("200")),
            Decimal("0.8"),
            Decimal("0.2"),
            -1,
            Money(Decimal("0")),
            0,
            0,
            "risk/v1",
        )
    with pytest.raises(ValueError):
        RiskSnapshot("snapshot", *valid_snapshot_args[:-1], " ")


def test_execution_outcome_requires_terminal_consistent_evidence() -> None:
    summary = RiskInputSummary(
        Money(Decimal("1000")),
        Money(Decimal("1000")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("1000")),
        0,
        0,
        Money(Decimal("0")),
    )
    allow = RiskDecision(
        "allow", PORTFOLIO, OrderId("order"), NOW, RiskDecisionType.ALLOW, (), "risk/v1", summary
    )
    created = Order(
        OrderId("order"),
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("100")),
        OrderType.MARKET,
        None,
        NOW,
    )
    versions = ExecutionPolicyVersions("execution", "lot", "limit", "settlement", "risk")
    eligibility = TradingEligibility(True, True, False, False, True)
    with pytest.raises(ValueError):
        ExecutionOutcome(created, eligibility, allow, None, (), None, None, None, versions, (), {})
    rejected = created.transition(OrderStatus.REJECTED)
    reject = RiskDecision(
        "reject",
        PORTFOLIO,
        OrderId("order"),
        NOW,
        RiskDecisionType.REJECT,
        (RiskReasonCode.INVALID_LOT_SIZE,),
        "risk/v1",
        summary,
    )
    fill = Fill(
        FillId("fill"),
        OrderId("order"),
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("100")),
        Price(Decimal("10")),
        NOW,
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        "execution/v1",
    )
    with pytest.raises(ValueError):
        ExecutionOutcome(
            rejected, eligibility, reject, fill, (), None, None, None, versions, (), {}
        )
    with pytest.raises(ValueError):
        ExecutionOutcome(rejected, eligibility, allow, None, (), None, None, None, versions, (), {})
