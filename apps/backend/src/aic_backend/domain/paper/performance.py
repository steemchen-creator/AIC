"""Deterministic performance and closed-position-cycle calculations."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
from hashlib import sha256

from aic_backend.domain.paper.models import (
    MetricSampleStatus,
    PaperAccount,
    PaperPerformanceConfig,
    PaperPerformanceSnapshot,
    PaperSession,
    TradeEpisode,
)
from aic_backend.domain.portfolio.models import Fill, Money, OrderSide, PortfolioSnapshot


def stable_id(prefix: str, *parts: object) -> str:
    material = "|".join(str(part) for part in parts)
    return f"{prefix}-{sha256(material.encode('utf-8')).hexdigest()[:32]}"


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _sample_std(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        return Decimal("0")
    average = _mean(values)
    variance = sum(((value - average) ** 2 for value in values), Decimal("0")) / Decimal(
        len(values) - 1
    )
    return variance.sqrt()


def calculate_performance(
    account: PaperAccount,
    session: PaperSession,
    snapshot: PortfolioSnapshot,
    history: tuple[PaperPerformanceSnapshot, ...],
    benchmark_value: Decimal,
    fills: tuple[Fill, ...],
    config: PaperPerformanceConfig,
) -> PaperPerformanceSnapshot:
    previous_nav = history[-1].nav.amount if history else account.initial_capital.amount
    daily_return = snapshot.nav.amount / previous_nav - Decimal("1")
    cumulative_return = snapshot.nav.amount / account.initial_capital.amount - Decimal("1")
    nav_values = tuple(item.nav.amount for item in history) + (snapshot.nav.amount,)
    peak = max((account.initial_capital.amount, *nav_values))
    drawdowns: list[Decimal] = []
    running_peak = account.initial_capital.amount
    for value in nav_values:
        running_peak = max(running_peak, value)
        drawdowns.append(value / running_peak - Decimal("1"))
    current_drawdown = snapshot.nav.amount / peak - Decimal("1")
    max_drawdown = min(drawdowns, default=Decimal("0"))
    returns = tuple(item.daily_return for item in history) + (daily_return,)
    sample_status = (
        MetricSampleStatus.SUFFICIENT
        if len(returns) >= config.minimum_ratio_samples
        else MetricSampleStatus.INSUFFICIENT_SAMPLE
    )
    volatility: Decimal | None = None
    sharpe: Decimal | None = None
    sortino: Decimal | None = None
    if len(returns) >= config.minimum_ratio_samples:
        with localcontext() as context:
            context.prec = 38
            root = Decimal(config.annualization_days).sqrt()
            volatility = _sample_std(returns) * root
            daily_risk_free = config.risk_free_rate / Decimal(config.annualization_days)
            excess = tuple(value - daily_risk_free for value in returns)
            excess_std = _sample_std(excess)
            sharpe = None if excess_std == 0 else _mean(excess) / excess_std * root
            downside = tuple(min(value - daily_risk_free, Decimal("0")) for value in returns)
            downside_deviation = (
                sum((value**2 for value in downside), Decimal("0")) / Decimal(len(downside))
            ).sqrt()
            sortino = None if downside_deviation == 0 else _mean(excess) / downside_deviation * root
    first_date = history[0].trading_date if history else session.trading_date
    elapsed_days = max((session.trading_date - first_date).days, 0)
    cagr: Decimal | None = None
    if elapsed_days >= config.minimum_cagr_days:
        with localcontext() as context:
            context.prec = 38
            years = Decimal(elapsed_days) / Decimal("365")
            cagr = (snapshot.nav.amount / account.initial_capital.amount) ** (
                Decimal("1") / years
            ) - Decimal("1")
    calmar = None if cagr is None or max_drawdown == 0 else cagr / abs(max_drawdown)
    first_benchmark = history[0].benchmark_value if history else benchmark_value
    benchmark_return = (
        Decimal("0") if first_benchmark == 0 else benchmark_value / first_benchmark - Decimal("1")
    )
    fees = sum((fill.fee.amount for fill in fills), Decimal("0"))
    taxes = sum((fill.tax.amount for fill in fills), Decimal("0"))
    slippage = sum((fill.slippage.amount for fill in fills), Decimal("0"))
    turnover_notional = sum(
        (fill.fill_price.value * fill.quantity.value for fill in fills), Decimal("0")
    )
    turnover = turnover_notional / account.initial_capital.amount
    exposures = tuple(item.market_value for item in snapshot.positions)
    largest = max(exposures, default=Decimal("0"))
    net_pnl = snapshot.nav.amount - account.initial_capital.amount
    gross_pnl = net_pnl + fees + taxes + slippage
    return PaperPerformanceSnapshot(
        stable_id("paper-performance", account.account_id, session.trading_date),
        account.account_id,
        session.session_id,
        session.trading_date,
        snapshot.as_of,
        snapshot.cash,
        snapshot.market_value,
        snapshot.realized_pnl,
        snapshot.unrealized_pnl,
        snapshot.nav,
        Money(gross_pnl),
        Money(net_pnl),
        snapshot.market_value,
        snapshot.cash.amount / snapshot.nav.amount,
        largest / snapshot.nav.amount,
        len(snapshot.positions),
        benchmark_value,
        daily_return,
        cumulative_return,
        Money(peak),
        current_drawdown,
        max_drawdown,
        cumulative_return,
        cagr,
        volatility,
        sharpe,
        sortino,
        calmar,
        benchmark_return,
        cumulative_return - benchmark_return,
        turnover,
        Money(fees),
        Money(taxes),
        Money(slippage),
        len(fills),
        sample_status,
        config.version,
        snapshot.positions,
    )


def derive_trade_episodes(
    account_id: str,
    fills: tuple[Fill, ...],
    trading_dates: tuple[date, ...],
) -> tuple[TradeEpisode, ...]:
    grouped: dict[str, list[Fill]] = defaultdict(list)
    for fill in sorted(fills, key=lambda item: (item.executed_at, item.fill_id.value)):
        grouped[fill.instrument.canonical_key].append(fill)
    date_index = {value: index for index, value in enumerate(sorted(set(trading_dates)))}
    episodes: list[TradeEpisode] = []
    for instrument_fills in grouped.values():
        quantity = Decimal("0")
        cycle: list[Fill] = []
        for fill in instrument_fills:
            if quantity == 0 and fill.side is OrderSide.SELL:
                continue
            cycle.append(fill)
            direction = Decimal("1") if fill.side is OrderSide.BUY else Decimal("-1")
            quantity += direction * fill.quantity.value
            if quantity != 0:
                continue
            buys = tuple(item for item in cycle if item.side is OrderSide.BUY)
            sells = tuple(item for item in cycle if item.side is OrderSide.SELL)
            entry = sum(
                (
                    item.fill_price.value * item.quantity.value + item.fee.amount + item.tax.amount
                    for item in buys
                ),
                Decimal("0"),
            )
            exit_value = sum(
                (
                    item.fill_price.value * item.quantity.value - item.fee.amount - item.tax.amount
                    for item in sells
                ),
                Decimal("0"),
            )
            opened_at, closed_at = cycle[0].executed_at, cycle[-1].executed_at
            holding_days = max(
                date_index.get(closed_at.date(), 0) - date_index.get(opened_at.date(), 0), 0
            )
            source_ids = tuple(item.fill_id.value for item in cycle)
            episodes.append(
                TradeEpisode(
                    stable_id("paper-episode", account_id, *source_ids),
                    account_id,
                    cycle[0].instrument,
                    opened_at,
                    closed_at,
                    Money(entry),
                    Money(exit_value),
                    Money(exit_value - entry),
                    Decimal("0") if entry == 0 else exit_value / entry - Decimal("1"),
                    holding_days,
                    source_ids,
                )
            )
            cycle = []
    return tuple(episodes)


def trade_statistics(episodes: tuple[TradeEpisode, ...]) -> dict[str, Decimal | int | None]:
    wins = tuple(item.net_pnl.amount for item in episodes if item.net_pnl.amount > 0)
    losses = tuple(item.net_pnl.amount for item in episodes if item.net_pnl.amount < 0)
    count = len(episodes)
    win_rate = None if count == 0 else Decimal(len(wins)) / Decimal(count)
    average_win = None if not wins else _mean(wins)
    average_loss = None if not losses else _mean(tuple(abs(value) for value in losses))
    profit_factor = (
        None
        if not losses
        else sum(wins, Decimal("0")) / sum((abs(value) for value in losses), Decimal("0"))
    )
    expectancy = None if count == 0 else _mean(tuple(item.net_pnl.amount for item in episodes))
    profit_loss_ratio = (
        None
        if average_win is None or average_loss is None or average_loss == 0
        else average_win / average_loss
    )
    return {
        "episode_count": count,
        "win_rate": win_rate,
        "average_win": average_win,
        "average_loss": average_loss,
        "profit_loss_ratio": profit_loss_ratio,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
    }
