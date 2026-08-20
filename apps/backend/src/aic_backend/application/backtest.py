"""Deterministic, PIT-only daily backtest orchestration."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from aic_backend.application.point_in_time import AvailabilityMode, PointInTimeContext
from aic_backend.application.ports.backtest import BacktestRecord, BacktestRepository
from aic_backend.application.use_cases.point_in_time_market_data import PointInTimeMarketDataService
from aic_backend.domain.market_data import AdjustmentMode, InstrumentIdentity, Market
from aic_backend.domain.portfolio import FeePolicy, SlippagePolicy
from aic_backend.domain.portfolio.accounting import PortfolioAccount
from aic_backend.domain.portfolio.models import (
    AuditEvent,
    BacktestErrorCode,
    BacktestResult,
    BacktestRun,
    BacktestStatus,
    BenchmarkResult,
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
    PortfolioSnapshot,
    Price,
    Quantity,
)


def stable_id(prefix: str, *parts: object) -> str:
    material = "|".join(str(part) for part in parts)
    return f"{prefix}-{sha256(material.encode('utf-8')).hexdigest()[:32]}"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    trading_date: date
    instrument: InstrumentIdentity
    side: OrderSide
    quantity: Quantity
    order_type: OrderType = OrderType.MARKET
    requested_price: Price | None = None


@dataclass(frozen=True, slots=True)
class ScriptedDecisionSource:
    intents: tuple[OrderIntent, ...]

    def for_date(self, value: date) -> tuple[OrderIntent, ...]:
        return tuple(intent for intent in self.intents if intent.trading_date == value)


class DeterministicBacktestEngine:
    DATA_POLICY_VERSION = "point-in-time-availability/v1"
    EXECUTION_POLICY_VERSION = "daily-close-fill/v1"

    def __init__(
        self,
        market_data: PointInTimeMarketDataService,
        fee_policy: FeePolicy,
        slippage_policy: SlippagePolicy,
        repository: BacktestRepository | None = None,
    ) -> None:
        self._market_data = market_data
        self._fee_policy = fee_policy
        self._slippage_policy = slippage_policy
        self._repository = repository

    async def execute(
        self,
        run: BacktestRun,
        market: Market,
        decisions: ScriptedDecisionSource,
        benchmark: InstrumentIdentity,
    ) -> BacktestRecord:
        self._validate_run(run)
        account = PortfolioAccount(run.portfolio_id, run.initial_capital)
        orders: list[Order] = []
        fills: list[Fill] = []
        ledger: list[CashLedgerEntry] = []
        snapshots: list[PortfolioSnapshot] = []
        events: list[AuditEvent] = []
        initial = CashLedgerEntry(
            stable_id("cash", run.run_id.value, "initial"),
            run.portfolio_id,
            run.created_at,
            CashEntryType.INITIAL_CAPITAL,
            run.initial_capital,
            run.initial_capital,
            run.run_id.value,
        )
        account.record_initial_capital(initial)
        ledger.append(initial)
        events.extend(
            (
                self._event(run, run.created_at, "RUN_CREATED", run.run_id.value, {}),
                self._event(
                    run,
                    run.created_at,
                    "INITIAL_CAPITAL",
                    initial.entry_id,
                    {"amount": str(run.initial_capital.amount)},
                ),
            )
        )

        def context(as_of: datetime) -> PointInTimeContext:
            return PointInTimeContext(
                as_of, AvailabilityMode.HISTORICAL_RESEARCH, AdjustmentMode.RAW
            )

        calendar = await self._market_data.list_calendar_as_of(
            market, run.start.date(), run.end.date(), context(run.end)
        )
        trading_days = tuple(
            day for day in calendar.records if day.is_open and day.session is not None
        )
        if not trading_days:
            raise PortfolioError(
                BacktestErrorCode.PIT_DATA_UNAVAILABLE, "no PIT-visible trading days"
            )
        benchmark_start: Decimal | None = None
        benchmark_end: Decimal | None = None
        warnings = list(calendar.warnings)
        for day in trading_days:
            assert day.session is not None
            as_of = day.session.session_close
            marks: dict[InstrumentIdentity, Decimal] = {}
            for index, intent in enumerate(decisions.for_date(day.trading_date)):
                reference = await self._price(intent.instrument, day.trading_date, as_of)
                order = Order(
                    OrderId(stable_id("order", run.run_id.value, day.trading_date, index)),
                    run.portfolio_id,
                    intent.instrument,
                    intent.side,
                    intent.quantity,
                    intent.order_type,
                    intent.requested_price,
                    as_of,
                ).transition(OrderStatus.ACCEPTED)
                fill_price, slippage = self._slippage_policy.apply(
                    intent.side, reference, intent.quantity
                )
                fee, tax = self._fee_policy.calculate(intent.side, intent.quantity, fill_price)
                fill = Fill(
                    FillId(stable_id("fill", order.order_id.value)),
                    order.order_id,
                    run.portfolio_id,
                    intent.instrument,
                    intent.side,
                    intent.quantity,
                    fill_price,
                    as_of,
                    fee,
                    tax,
                    slippage,
                    f"{self._fee_policy.version}|{self._slippage_policy.version}|{self.EXECUTION_POLICY_VERSION}",
                )
                change_count = 1 + int(fee.amount != 0) + int(tax.amount != 0)
                entry_ids = tuple(
                    stable_id("cash", fill.fill_id.value, item) for item in range(change_count)
                )
                changes = account.apply_fill(fill, entry_ids)
                order = order.transition(OrderStatus.FILLED)
                orders.append(order)
                fills.append(fill)
                ledger.extend(changes)
                events.extend(self._trade_events(run, order, fill, changes))
                marks[intent.instrument] = reference.value
            for position in account.positions.values():
                if position.quantity and position.key.instrument not in marks:
                    marks[position.key.instrument] = (
                        await self._price(position.key.instrument, day.trading_date, as_of)
                    ).value
            snapshot = account.snapshot(as_of, marks)
            snapshots.append(snapshot)
            events.append(
                self._event(
                    run,
                    as_of,
                    "NAV_SNAPSHOT",
                    stable_id("nav", run.run_id.value, day.trading_date),
                    {"nav": str(snapshot.nav.amount)},
                )
            )
            try:
                benchmark_mark = (await self._price(benchmark, day.trading_date, as_of)).value
                benchmark_start = benchmark_mark if benchmark_start is None else benchmark_start
                benchmark_end = benchmark_mark
            except PortfolioError:
                warnings.append(
                    f"benchmark unavailable: {benchmark.canonical_key}:{day.trading_date}"
                )
        if not snapshots:
            raise PortfolioError(
                BacktestErrorCode.REPLAY_FAILURE, "backtest produced no NAV snapshots"
            )
        benchmark_result = self._benchmark(benchmark, benchmark_start, benchmark_end)
        result = self._result(run, account, fills, snapshots[-1], benchmark_result, tuple(warnings))
        record = BacktestRecord(
            run, tuple(orders), tuple(fills), tuple(ledger), tuple(snapshots), tuple(events), result
        )
        if self._repository is not None:
            await self._repository.save(record)
        return record

    async def _price(
        self, instrument: InstrumentIdentity, trading_date: date, as_of: datetime
    ) -> Price:
        result = await self._market_data.get_daily_bars_as_of(
            instrument,
            trading_date,
            trading_date,
            PointInTimeContext(as_of, AvailabilityMode.HISTORICAL_RESEARCH, AdjustmentMode.RAW),
        )
        exact = tuple(item for item in result.records if item.record.trading_date == trading_date)
        if len(exact) != 1:
            code = (
                BacktestErrorCode.PIT_DATA_UNAVAILABLE
                if result.decisions
                else BacktestErrorCode.MARKET_DATA_UNAVAILABLE
            )
            raise PortfolioError(
                code, f"PIT price unavailable for {instrument.canonical_key}:{trading_date}"
            )
        return Price(exact[0].record.close)

    def _validate_run(self, run: BacktestRun) -> None:
        expected = (
            self.DATA_POLICY_VERSION,
            self._fee_policy.version,
            self._slippage_policy.version,
            self.EXECUTION_POLICY_VERSION,
        )
        actual = (
            run.data_policy_version,
            run.fee_policy_version,
            run.slippage_policy_version,
            run.execution_policy_version,
        )
        if actual != expected:
            raise PortfolioError(
                BacktestErrorCode.POLICY_FAILURE,
                "run policy versions do not match injected policies",
            )

    def _event(
        self,
        run: BacktestRun,
        timestamp: datetime,
        event_type: str,
        source_id: str,
        payload: dict[str, str],
    ) -> AuditEvent:
        return AuditEvent(
            stable_id("event", run.run_id.value, event_type, source_id),
            timestamp,
            event_type,
            source_id,
            run.portfolio_id,
            payload,
        )

    def _trade_events(
        self, run: BacktestRun, order: Order, fill: Fill, changes: Sequence[CashLedgerEntry]
    ) -> tuple[AuditEvent, ...]:
        values = [
            self._event(
                run, order.created_at, "ORDER", order.order_id.value, {"status": order.status.value}
            ),
            self._event(
                run,
                fill.executed_at,
                "FILL",
                fill.fill_id.value,
                {"price": str(fill.fill_price.value)},
            ),
        ]
        values.extend(
            self._event(
                run,
                item.occurred_at,
                "CASH_CHANGE",
                item.entry_id,
                {"amount": str(item.amount.amount)},
            )
            for item in changes
        )
        values.append(
            self._event(
                run,
                fill.executed_at,
                "POSITION_CHANGE",
                fill.fill_id.value,
                {"instrument": fill.instrument.canonical_key},
            )
        )
        return tuple(values)

    @staticmethod
    def _benchmark(
        instrument: InstrumentIdentity, start: Decimal | None, end: Decimal | None
    ) -> BenchmarkResult:
        if start is None or end is None:
            return BenchmarkResult(instrument, Decimal("0"), Decimal("0"), Decimal("0"))
        return BenchmarkResult(instrument, start, end, end / start - Decimal("1"))

    @staticmethod
    def _result(
        run: BacktestRun,
        account: PortfolioAccount,
        fills: Sequence[Fill],
        final: PortfolioSnapshot,
        benchmark: BenchmarkResult,
        warnings: tuple[str, ...],
    ) -> BacktestResult:
        fees = sum((fill.fee.amount for fill in fills), Decimal("0"))
        taxes = sum((fill.tax.amount for fill in fills), Decimal("0"))
        slippage = sum((fill.slippage.amount for fill in fills), Decimal("0"))
        net = final.nav.amount - run.initial_capital.amount
        gross = net + fees + taxes + slippage
        total_return = net / run.initial_capital.amount
        return BacktestResult(
            run.run_id,
            run.initial_capital,
            final.nav,
            Money(gross),
            Money(fees),
            Money(taxes),
            Money(slippage),
            Money(net),
            total_return,
            final.realized_pnl,
            final.unrealized_pnl,
            len(fills),
            benchmark.benchmark_return,
            total_return - benchmark.benchmark_return,
            BacktestStatus.COMPLETED,
            warnings,
        )
