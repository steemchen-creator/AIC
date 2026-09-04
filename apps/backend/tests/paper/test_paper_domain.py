from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.paper import (
    CapitalMode,
    MetricSampleStatus,
    OperationalStatus,
    PaperAccount,
    PaperAccountStatus,
    PaperErrorCode,
    PaperMode,
    PaperPerformanceConfig,
    PaperPortfolioState,
    PaperRuntimeError,
    PaperSession,
    PaperSessionStatus,
    PaperStateEvent,
    TradeEpisode,
    calculate_performance,
    derive_trade_episodes,
    trade_statistics,
)
from aic_backend.domain.portfolio.models import (
    Fill,
    FillId,
    Money,
    OrderId,
    OrderSide,
    PortfolioId,
    PortfolioSnapshot,
    Price,
    Quantity,
)

NOW = datetime(2026, 9, 1, 8, tzinfo=UTC)
ACCOUNT_ID = "paper-domain"
PORTFOLIO_ID = PortfolioId("portfolio-domain")
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600001", InstrumentType.EQUITY)


def account(status: PaperAccountStatus = PaperAccountStatus.CREATED) -> PaperAccount:
    return PaperAccount(
        ACCOUNT_ID,
        PORTFOLIO_ID,
        "Paper",
        Money(Decimal("500000")),
        PaperMode.FORWARD_PAPER,
        CapitalMode.CONTINUOUS_COMPOUNDING,
        status,
        NOW,
        NOW,
    )


def session(
    trading_date: date, status: PaperSessionStatus = PaperSessionStatus.MARKING
) -> PaperSession:
    return PaperSession(
        f"session-{trading_date}",
        ACCOUNT_ID,
        trading_date,
        status,
        NOW,
        NOW,
        None,
        "daily-bar-forward-paper/v1",
    )


def fill(
    fill_id: str,
    side: OrderSide,
    quantity: str,
    price: str,
    occurred_at: datetime,
) -> Fill:
    return Fill(
        FillId(fill_id),
        OrderId(f"order-{fill_id}"),
        PORTFOLIO_ID,
        INSTRUMENT,
        side,
        Quantity(Decimal(quantity)),
        Price(Decimal(price)),
        occurred_at,
        Money(Decimal("5")),
        Money(Decimal("1") if side is OrderSide.SELL else Decimal("0")),
        Money(Decimal("0")),
        "next-session-open/v1",
    )


def test_account_and_session_state_machines_reject_illegal_transitions() -> None:
    ready = account().transition(PaperAccountStatus.READY, NOW)
    running = ready.transition(PaperAccountStatus.RUNNING, NOW)
    paused = running.transition(PaperAccountStatus.PAUSED, NOW)
    assert paused.transition(PaperAccountStatus.RUNNING, NOW).status is PaperAccountStatus.RUNNING
    with pytest.raises(PaperRuntimeError) as error:
        account().transition(PaperAccountStatus.CLOSED, NOW)
    assert error.value.code is PaperErrorCode.INVALID_ACCOUNT_STATE

    value = session(date(2026, 9, 1), PaperSessionStatus.PLANNED)
    value = value.transition(PaperSessionStatus.OPEN, NOW)
    value = value.transition(PaperSessionStatus.PROCESSING, NOW)
    value = value.transition(PaperSessionStatus.MARKING, NOW)
    finalized = value.transition(PaperSessionStatus.FINALIZED, NOW)
    assert finalized.finalized_at == NOW
    with pytest.raises(PaperRuntimeError):
        finalized.transition(PaperSessionStatus.PROCESSING, NOW)


def test_account_is_forward_only_and_never_resets_initial_capital() -> None:
    value = account(PaperAccountStatus.RUNNING).finalize(date(2026, 9, 2), NOW)
    assert value.initial_capital.amount == Decimal("500000")
    with pytest.raises(PaperRuntimeError) as error:
        value.finalize(date(2026, 9, 1), NOW)
    assert error.value.code is PaperErrorCode.FORWARD_ONLY_VIOLATION


def test_performance_metrics_are_deterministic_and_mark_small_samples() -> None:
    value = account(PaperAccountStatus.RUNNING)
    history = ()
    fills: tuple[Fill, ...] = ()
    for index in range(20):
        trading_date = date(2025, 1, 1) + timedelta(days=index * 20)
        nav = Decimal("500000") + Decimal(index + 1) * Decimal("1000")
        portfolio = PortfolioSnapshot(
            PORTFOLIO_ID,
            NOW + timedelta(days=index * 20),
            Money(nav),
            (),
            Money(Decimal("0")),
            Money(Decimal("0")),
            Money(Decimal("0")),
            Money(nav),
        )
        current_session = session(trading_date)
        result = calculate_performance(
            value,
            current_session,
            portfolio,
            history,
            Decimal("100") + Decimal(index),
            fills,
            PaperPerformanceConfig(minimum_ratio_samples=20, minimum_cagr_days=365),
        )
        history += (result,)
    assert history[0].sample_status is MetricSampleStatus.INSUFFICIENT_SAMPLE
    assert history[-1].sample_status is MetricSampleStatus.SUFFICIENT
    assert history[-1].annualized_volatility is not None
    assert history[-1].sharpe is not None
    assert history[-1].cagr is not None
    assert history[-1].total_return == Decimal("0.04")
    assert history[-1].benchmark_return == Decimal("0.19")
    assert history[-1].excess_return == Decimal("-0.15")


def test_trade_episode_requires_full_position_cycle_and_defines_statistics() -> None:
    day1 = NOW
    day2 = NOW + timedelta(days=1)
    day3 = NOW + timedelta(days=2)
    values = (
        fill("buy", OrderSide.BUY, "100", "10", day1),
        fill("partial", OrderSide.SELL, "40", "11", day2),
    )
    assert derive_trade_episodes(ACCOUNT_ID, values, (day1.date(), day2.date())) == ()
    values += (fill("close", OrderSide.SELL, "60", "12", day3),)
    episodes = derive_trade_episodes(ACCOUNT_ID, values, (day1.date(), day2.date(), day3.date()))
    assert len(episodes) == 1
    assert episodes[0].source_fill_ids == ("buy", "partial", "close")
    assert episodes[0].net_pnl.amount == Decimal("143")
    statistics = trade_statistics(episodes)
    assert statistics["episode_count"] == 1
    assert statistics["win_rate"] == Decimal("1")
    assert statistics["profit_factor"] is None


def test_paper_domain_rejects_invalid_evidence_and_freezes_event_payload() -> None:
    base_account = account()
    with pytest.raises(ValueError, match="account_id"):
        replace(base_account, account_id=" ")
    with pytest.raises(ValueError, match="timezone"):
        replace(base_account, created_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="positive"):
        replace(base_account, initial_capital=Money(Decimal("0")))

    with pytest.raises(ValueError, match="finalized_at"):
        session(date(2026, 9, 1), PaperSessionStatus.FINALIZED)

    portfolio = PortfolioSnapshot(
        PORTFOLIO_ID,
        NOW,
        Money(Decimal("100")),
        (),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("100")),
    )
    state = PaperPortfolioState(Money(Decimal("100")), (), (), (), portfolio, None)
    with pytest.raises(ValueError, match="negative"):
        replace(state, cash=Money(Decimal("-1")))
    with pytest.raises(ValueError, match="match"):
        replace(state, cash=Money(Decimal("99")))
    with pytest.raises(ValueError, match="counters"):
        replace(state, orders_today=-1)

    with pytest.raises(ValueError, match="conventions"):
        PaperPerformanceConfig(annualization_days=0)
    with pytest.raises(ValueError, match="minimum_cagr_days"):
        PaperPerformanceConfig(minimum_cagr_days=0)

    performance = calculate_performance(
        replace(base_account, initial_capital=Money(Decimal("100"))),
        session(date(2026, 9, 1)),
        portfolio,
        (),
        Decimal("100"),
        (),
        PaperPerformanceConfig(),
    )
    with pytest.raises(ValueError, match="amounts"):
        replace(performance, nav=Money(Decimal("0")))
    with pytest.raises(ValueError, match="cash_pct"):
        replace(performance, cash_pct=Decimal("-0.1"))
    with pytest.raises(ValueError, match="largest_position_pct"):
        replace(performance, largest_position_pct=Decimal("1.1"))
    with pytest.raises(ValueError, match="counters"):
        replace(performance, fill_count=-1)

    payload = {"reason": "operator"}
    event = PaperStateEvent(
        "event-1",
        ACCOUNT_ID,
        NOW,
        "ACCOUNT_PAUSED",
        ACCOUNT_ID,
        OperationalStatus.PAUSED,
        payload=payload,
    )
    payload["reason"] = "changed"
    assert event.payload["reason"] == "operator"
    with pytest.raises(TypeError):
        event.payload["reason"] = "changed"  # type: ignore[index]

    episode = TradeEpisode(
        "episode-1",
        ACCOUNT_ID,
        INSTRUMENT,
        NOW,
        NOW + timedelta(days=1),
        Money(Decimal("100")),
        Money(Decimal("110")),
        Money(Decimal("10")),
        Decimal("0.1"),
        1,
        ("fill-1",),
    )
    with pytest.raises(ValueError, match="timestamps"):
        replace(episode, closed_at=NOW - timedelta(days=1))
    with pytest.raises(ValueError, match="source fills"):
        replace(episode, source_fill_ids=())
