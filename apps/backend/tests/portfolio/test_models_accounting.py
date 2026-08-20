from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.accounting import PortfolioAccount
from aic_backend.domain.portfolio.models import (
    AuditEvent,
    BacktestErrorCode,
    BacktestRun,
    BacktestRunId,
    CashEntryType,
    CashLedgerEntry,
    Fill,
    FillId,
    Money,
    Order,
    OrderId,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioError,
    PortfolioId,
    Price,
    Quantity,
)
from aic_backend.domain.portfolio.policies import ConfigurableFeePolicy, FixedBpsSlippagePolicy

NOW = datetime(2026, 1, 5, 7, tzinfo=UTC)
PORTFOLIO = PortfolioId("portfolio-1")
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


def fill(side: OrderSide, quantity: str, price: str, fee: str = "0", tax: str = "0") -> Fill:
    return Fill(
        FillId(f"fill-{side.value}-{quantity}"),
        OrderId("order-1"),
        PORTFOLIO,
        INSTRUMENT,
        side,
        Quantity(Decimal(quantity)),
        Price(Decimal(price)),
        NOW,
        Money(Decimal(fee)),
        Money(Decimal(tax)),
        Money(Decimal("0")),
        "policy/v1",
    )


def test_value_objects_validate_decimal_identity_currency_and_timezone() -> None:
    assert Money(Decimal("1.25")).currency == "CNY"
    assert Quantity(Decimal("2")).value == Decimal("2")
    assert Price(Decimal("3")).value == Decimal("3")
    with pytest.raises(TypeError):
        Money(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Quantity(Decimal("0"))
    with pytest.raises(ValueError):
        Money(Decimal("1"), "USD")


def test_order_lifecycle_accepts_only_declared_full_fill_transitions() -> None:
    order = Order(
        OrderId("order-1"),
        PORTFOLIO,
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("10")),
        OrderType.MARKET,
        None,
        NOW,
    )
    accepted = order.transition(OrderStatus.ACCEPTED)
    assert accepted.transition(OrderStatus.FILLED).status is OrderStatus.FILLED
    assert order.transition(OrderStatus.CANCELLED).status is OrderStatus.CANCELLED
    assert order.transition(OrderStatus.REJECTED).status is OrderStatus.REJECTED
    with pytest.raises(PortfolioError, match="invalid order transition"):
        order.transition(OrderStatus.FILLED)
    with pytest.raises(PortfolioError):
        accepted.transition(OrderStatus.CREATED)
    with pytest.raises(PortfolioError):
        accepted.transition(OrderStatus.FILLED).transition(OrderStatus.CANCELLED)


def test_limit_order_requires_price_and_timestamps_are_aware() -> None:
    with pytest.raises(PortfolioError) as error:
        Order(
            OrderId("o"),
            PORTFOLIO,
            INSTRUMENT,
            OrderSide.BUY,
            Quantity(Decimal("1")),
            OrderType.LIMIT,
            None,
            NOW,
        )
    assert error.value.code is BacktestErrorCode.INVALID_PRICE
    with pytest.raises(ValueError, match="timezone"):
        Order(
            OrderId("o"),
            PORTFOLIO,
            INSTRUMENT,
            OrderSide.BUY,
            Quantity(Decimal("1")),
            OrderType.MARKET,
            None,
            NOW.replace(tzinfo=None),
        )


def test_weighted_average_cost_realized_pnl_and_cash_ledger() -> None:
    account = PortfolioAccount(PORTFOLIO, Money(Decimal("10000")))
    initial = CashLedgerEntry(
        "initial",
        PORTFOLIO,
        NOW,
        CashEntryType.INITIAL_CAPITAL,
        Money(Decimal("10000")),
        Money(Decimal("10000")),
        "run",
    )
    account.record_initial_capital(initial)
    account.apply_fill(fill(OrderSide.BUY, "100", "10", "5"), ("buy", "fee"))
    account.apply_fill(fill(OrderSide.BUY, "100", "20", "5"), ("buy2", "fee2"))
    position = account.positions[INSTRUMENT.canonical_key]
    assert position.quantity == Decimal("200")
    assert position.average_cost == Decimal("15.05")
    account.apply_fill(fill(OrderSide.SELL, "50", "25", "5", "1"), ("sell", "fee3", "tax"))
    position = account.positions[INSTRUMENT.canonical_key]
    assert position.quantity == Decimal("150")
    assert position.realized_pnl == Decimal("491.50")
    snapshot = account.snapshot(NOW, {INSTRUMENT: Decimal("22")})
    assert snapshot.market_value.amount == Decimal("3300")
    assert snapshot.unrealized_pnl.amount == Decimal("1042.50")
    assert snapshot.nav.amount == account.cash + Decimal("3300")
    assert [item.entry_type for item in account.cash_ledger] == [
        CashEntryType.INITIAL_CAPITAL,
        CashEntryType.BUY_SETTLEMENT,
        CashEntryType.FEE,
        CashEntryType.BUY_SETTLEMENT,
        CashEntryType.FEE,
        CashEntryType.SELL_SETTLEMENT,
        CashEntryType.FEE,
        CashEntryType.TAX,
    ]


def test_invalid_fills_never_create_negative_cash_or_short_position() -> None:
    account = PortfolioAccount(PORTFOLIO, Money(Decimal("100")))
    with pytest.raises(PortfolioError) as cash_error:
        account.apply_fill(fill(OrderSide.BUY, "20", "10"), ("buy",))
    assert cash_error.value.code is BacktestErrorCode.INSUFFICIENT_CASH
    with pytest.raises(PortfolioError) as position_error:
        account.apply_fill(fill(OrderSide.SELL, "1", "10"), ("sell",))
    assert position_error.value.code is BacktestErrorCode.INSUFFICIENT_POSITION


def test_fee_and_slippage_are_injectable_deterministic_and_side_aware() -> None:
    fees = ConfigurableFeePolicy(Decimal("0.001"), Decimal("5"), Decimal("0.001"))
    buy_fee, buy_tax = fees.calculate(OrderSide.BUY, Quantity(Decimal("100")), Price(Decimal("10")))
    sell_fee, sell_tax = fees.calculate(
        OrderSide.SELL, Quantity(Decimal("1000")), Price(Decimal("10"))
    )
    assert (buy_fee.amount, buy_tax.amount) == (Decimal("5"), Decimal("0"))
    assert (sell_fee.amount, sell_tax.amount) == (Decimal("10"), Decimal("10"))
    slippage = FixedBpsSlippagePolicy(Decimal("10"))
    buy_price, buy_cost = slippage.apply(
        OrderSide.BUY, Price(Decimal("10")), Quantity(Decimal("100"))
    )
    sell_price, sell_cost = slippage.apply(
        OrderSide.SELL, Price(Decimal("10")), Quantity(Decimal("100"))
    )
    assert buy_price.value == Decimal("10.010")
    assert sell_price.value == Decimal("9.990")
    assert buy_cost == sell_cost == Money(Decimal("1.000"))


def test_policy_configuration_rejects_negative_costs() -> None:
    with pytest.raises(ValueError, match="rates"):
        ConfigurableFeePolicy(Decimal("-0.1"))
    with pytest.raises(ValueError, match="basis points"):
        FixedBpsSlippagePolicy(Decimal("-1"))


def test_accounting_rejects_invalid_aggregate_operations_and_missing_marks() -> None:
    with pytest.raises(ValueError, match="positive"):
        PortfolioAccount(PORTFOLIO, Money(Decimal("0")))
    account = PortfolioAccount(PORTFOLIO, Money(Decimal("100")))
    adjustment = CashLedgerEntry(
        "adjust",
        PORTFOLIO,
        NOW,
        CashEntryType.ADJUSTMENT,
        Money(Decimal("1")),
        Money(Decimal("101")),
        "source",
    )
    with pytest.raises(ValueError, match="initial entry"):
        account.record_initial_capital(adjustment)
    initial = CashLedgerEntry(
        "initial",
        PORTFOLIO,
        NOW,
        CashEntryType.INITIAL_CAPITAL,
        Money(Decimal("100")),
        Money(Decimal("100")),
        "run",
    )
    account.record_initial_capital(initial)
    with pytest.raises(ValueError, match="already"):
        account.record_initial_capital(initial)
    other = Fill(
        FillId("other"),
        OrderId("other"),
        PortfolioId("other"),
        INSTRUMENT,
        OrderSide.BUY,
        Quantity(Decimal("1")),
        Price(Decimal("1")),
        NOW,
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        "policy",
    )
    with pytest.raises(PortfolioError) as wrong_portfolio:
        account.apply_fill(other, ("entry",))
    assert wrong_portfolio.value.code is BacktestErrorCode.INVALID_ORDER
    with pytest.raises(ValueError, match="entry ids"):
        account.apply_fill(fill(OrderSide.BUY, "1", "1", "1"), ("entry",))
    bought = fill(OrderSide.BUY, "1", "1")
    account.apply_fill(bought, ("buy",))
    with pytest.raises(PortfolioError) as missing:
        account.snapshot(NOW, {})
    assert missing.value.code is BacktestErrorCode.PIT_DATA_UNAVAILABLE


def test_domain_models_validate_run_fill_event_and_identifier_boundaries() -> None:
    with pytest.raises(ValueError):
        PortfolioId(" ")
    with pytest.raises(ValueError, match="costs"):
        Fill(
            FillId("fill"),
            OrderId("order"),
            PORTFOLIO,
            INSTRUMENT,
            OrderSide.BUY,
            Quantity(Decimal("1")),
            Price(Decimal("1")),
            NOW,
            Money(Decimal("-1")),
            Money(Decimal("0")),
            Money(Decimal("0")),
            "policy",
        )
    event_payload = {"key": "value"}
    event = AuditEvent("event", NOW, "TYPE", "source", PORTFOLIO, event_payload)
    event_payload["key"] = "changed"
    assert event.payload["key"] == "value"
    with pytest.raises(ValueError, match="precede"):
        BacktestRun(
            BacktestRunId("run"),
            PORTFOLIO,
            NOW,
            NOW.replace(year=2025),
            Money(Decimal("1")),
            "data",
            "fee",
            "slip",
            "execution",
            NOW,
        )
