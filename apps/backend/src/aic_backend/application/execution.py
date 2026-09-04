"""Deterministic A-share cash-account execution and pre-trade risk orchestration."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from aic_backend.application.point_in_time import AvailabilityMode, PointInTimeContext
from aic_backend.application.ports.execution import ExecutionEvidenceRepository
from aic_backend.application.use_cases.point_in_time_market_data import PointInTimeMarketDataService
from aic_backend.domain.execution import (
    AShareBoardLotPolicy,
    ExecutionOutcome,
    ExecutionPolicyVersions,
    ExplicitPriceLimitPolicy,
    LotPolicy,
    PreTradeRiskInput,
    PreTradeRiskPolicy,
    PriceLimitBand,
    PriceLimitClassification,
    PriceLimitPolicy,
    RiskDecision,
    RiskDecisionType,
    RiskInputSummary,
    RiskReasonCode,
    RiskSnapshot,
    SettlementBook,
    SettlementPosition,
    SettlementRolloverEvent,
    TradingEligibility,
)
from aic_backend.domain.market_data import (
    AdjustmentMode,
    InstrumentIdentity,
    InstrumentTradingState,
    Market,
)
from aic_backend.domain.portfolio.accounting import PortfolioAccount
from aic_backend.domain.portfolio.models import (
    AuditEvent,
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
    PortfolioId,
    PortfolioSnapshot,
    Price,
    Quantity,
)
from aic_backend.domain.portfolio.policies import FeePolicy, SlippagePolicy


@dataclass(frozen=True, slots=True)
class ExecutionOrderIntent:
    instrument: InstrumentIdentity
    side: OrderSide
    quantity: Quantity
    requested_price: Price | None = None


@dataclass(slots=True)
class ExecutionState:
    account: PortfolioAccount
    settlement: SettlementBook
    last_snapshot: PortfolioSnapshot
    activity_date: date | None = None
    orders_today: int = 0
    filled_orders_today: int = 0
    daily_turnover: Decimal = Decimal("0")
    pending_settlement_event: SettlementRolloverEvent | None = None
    outcomes: list[ExecutionOutcome] = field(default_factory=list)

    @classmethod
    def initialize(
        cls, portfolio_id: PortfolioId, initial_capital: Money, created_at: datetime
    ) -> "ExecutionState":
        account = PortfolioAccount(portfolio_id, initial_capital)
        account.record_initial_capital(
            CashLedgerEntry(
                _stable_id("capital", portfolio_id.value, created_at.isoformat()),
                portfolio_id,
                created_at,
                CashEntryType.INITIAL_CAPITAL,
                initial_capital,
                initial_capital,
                portfolio_id.value,
            )
        )
        return cls(account, SettlementBook(portfolio_id), account.snapshot(created_at, {}))

    def begin_activity(self, trading_date: date) -> None:
        if self.activity_date == trading_date:
            return
        self.activity_date = trading_date
        self.orders_today = 0
        self.filled_orders_today = 0
        self.daily_turnover = Decimal("0")


class AShareExecutionService:
    EXECUTION_VERSION = "a-share-deterministic-execution/v1"

    def __init__(
        self,
        pit_market_data: PointInTimeMarketDataService,
        fee_policy: FeePolicy,
        slippage_policy: SlippagePolicy,
        risk_policy: PreTradeRiskPolicy,
        repository: ExecutionEvidenceRepository | None = None,
        lot_policy: LotPolicy | None = None,
        price_limit_policy: PriceLimitPolicy | None = None,
    ) -> None:
        self._pit = pit_market_data
        self._fee = fee_policy
        self._slippage = slippage_policy
        self._risk = risk_policy
        self._repository = repository
        self._lot = lot_policy or AShareBoardLotPolicy()
        self._price_limit = price_limit_policy or ExplicitPriceLimitPolicy()
        self.policy_versions = ExecutionPolicyVersions(
            self.EXECUTION_VERSION,
            self._lot.version,
            self._price_limit.version,
            SettlementBook.VERSION,
            self._risk.version,
        )

    async def advance_session(
        self, state: ExecutionState, market: Market, as_of: datetime
    ) -> SettlementRolloverEvent | None:
        context = self._context(as_of)
        result = await self._pit.list_calendar_as_of(market, as_of.date(), as_of.date(), context)
        day = next((item for item in result.records if item.trading_date == as_of.date()), None)
        if day is None or not day.is_open:
            return None
        state.begin_activity(as_of.date())
        event = state.settlement.rollover(as_of.date(), as_of)
        if event is not None:
            state.pending_settlement_event = event
        return event

    async def execute(
        self,
        state: ExecutionState,
        intent: ExecutionOrderIntent,
        order_id: OrderId,
        as_of: datetime,
        price_limit_band: PriceLimitBand | None,
    ) -> ExecutionOutcome:
        context = self._context(as_of)
        state.begin_activity(as_of.date())
        order = Order(
            order_id,
            state.account.portfolio_id,
            intent.instrument,
            intent.side,
            intent.quantity,
            OrderType.LIMIT if intent.requested_price is not None else OrderType.MARKET,
            intent.requested_price,
            as_of,
        )
        reasons: set[RiskReasonCode] = set()

        calendar = await self._pit.list_calendar_as_of(
            intent.instrument.market, as_of.date(), as_of.date(), context
        )
        session = next(
            (item for item in calendar.records if item.trading_date == as_of.date()), None
        )
        if session is None:
            reasons.add(RiskReasonCode.PIT_DATA_UNAVAILABLE)
        elif not session.is_open:
            reasons.add(RiskReasonCode.MARKET_CLOSED)
        else:
            event = state.settlement.rollover(as_of.date(), as_of)
            if event is not None:
                state.pending_settlement_event = event

        eligibility = TradingEligibility(
            session is not None and session.is_open,
            False,
            False,
            False,
            False,
        )
        if not reasons:
            tradability_reasons, eligibility = await self._tradability(
                intent.instrument, as_of, context
            )
            reasons.update(tradability_reasons)

        reference_price = await self._reference_price(intent.instrument, as_of, context)
        if reference_price is None:
            reasons.add(RiskReasonCode.PIT_DATA_UNAVAILABLE)
        rule_price = intent.requested_price or reference_price
        if not self._lot.validate(intent.side, intent.quantity):
            reasons.add(RiskReasonCode.INVALID_LOT_SIZE)
        effective_band = (
            price_limit_band
            if price_limit_band is not None and price_limit_band.available_at <= as_of
            else None
        )
        price_classification = (
            PriceLimitClassification.UNKNOWN_LIMIT
            if rule_price is None
            else self._price_limit.classify(rule_price, effective_band)
        )
        if price_classification is PriceLimitClassification.UNKNOWN_LIMIT:
            reasons.add(RiskReasonCode.PRICE_LIMIT_UNKNOWN)
        elif price_classification in (
            PriceLimitClassification.UPPER_LIMIT,
            PriceLimitClassification.LOWER_LIMIT,
        ):
            reasons.add(RiskReasonCode.PRICE_OUTSIDE_LIMIT)

        current_snapshot = await self._snapshot(
            state, as_of, context, reference_price, intent.instrument
        )
        if current_snapshot is None or rule_price is None or reference_price is None:
            outcome = self._reject(
                state,
                order,
                as_of,
                reasons or {RiskReasonCode.PIT_DATA_UNAVAILABLE},
                state.last_snapshot,
                state.pending_settlement_event,
                eligibility,
                price_classification,
            )
            return await self._record(state, outcome)

        fill_price, slippage = self._slippage.apply(
            intent.side, intent.requested_price or reference_price, intent.quantity
        )
        fee, tax = self._fee.calculate(intent.side, intent.quantity, fill_price)
        settlement_position = state.settlement.get(intent.instrument)
        if intent.side is OrderSide.SELL:
            if intent.quantity.value > settlement_position.total_quantity:
                reasons.add(RiskReasonCode.INSUFFICIENT_POSITION)
            if intent.quantity.value > settlement_position.sellable_quantity:
                reasons.add(RiskReasonCode.INSUFFICIENT_SELLABLE_POSITION)
        risk_input = PreTradeRiskInput(
            current_snapshot,
            intent.instrument,
            intent.side,
            intent.quantity,
            fill_price,
            eligibility,
            as_of,
            fee.amount + tax.amount,
            settlement_position.sellable_quantity,
            state.orders_today,
            state.filled_orders_today,
            state.daily_turnover,
        )
        reasons.update(self._risk.evaluate(risk_input))
        state.orders_today += 1
        if reasons:
            outcome = self._reject(
                state,
                order,
                as_of,
                reasons,
                current_snapshot,
                state.pending_settlement_event,
                eligibility,
                price_classification,
                self._risk.summarize(risk_input),
            )
            return await self._record(state, outcome)

        decision = self._decision(
            order, as_of, (), self._risk.summarize(risk_input), RiskDecisionType.ALLOW
        )
        order = order.transition(OrderStatus.ACCEPTED)
        fill = Fill(
            FillId(_stable_id("fill", order_id.value, as_of.isoformat())),
            order_id,
            order.portfolio_id,
            order.instrument,
            order.side,
            order.quantity,
            fill_price,
            as_of,
            fee,
            tax,
            slippage,
            self.EXECUTION_VERSION,
        )
        entry_ids = [_stable_id("cash", fill.fill_id.value, "settlement")]
        if fee.amount:
            entry_ids.append(_stable_id("cash", fill.fill_id.value, "fee"))
        if tax.amount:
            entry_ids.append(_stable_id("cash", fill.fill_id.value, "tax"))
        cash_entries = state.account.apply_fill(fill, tuple(entry_ids))
        updated_settlement = state.settlement.apply_fill(fill)
        order = order.transition(OrderStatus.FILLED)
        state.filled_orders_today += 1
        state.daily_turnover += intent.quantity.value * fill_price.value
        marks = await self._marks(state, as_of, context)
        if marks is None:
            raise ValueError("accepted execution lost its PIT marks")
        post_snapshot = state.account.snapshot(as_of, marks)
        state.last_snapshot = post_snapshot
        risk_snapshot = self._risk_snapshot(state, order, post_snapshot, as_of)
        event = state.pending_settlement_event
        state.pending_settlement_event = None
        audit_events = self._accepted_audit_events(
            order,
            eligibility,
            decision,
            fill,
            cash_entries,
            updated_settlement,
            risk_snapshot,
            as_of,
        )
        outcome = ExecutionOutcome(
            order,
            eligibility,
            decision,
            fill,
            cash_entries,
            updated_settlement,
            event,
            risk_snapshot,
            self.policy_versions,
            audit_events,
            {"price_limit": price_classification.value, "snapshot_as_of": as_of.isoformat()},
        )
        return await self._record(state, outcome)

    async def _tradability(
        self, instrument: InstrumentIdentity, as_of: datetime, context: PointInTimeContext
    ) -> tuple[set[RiskReasonCode], TradingEligibility]:
        reasons: set[RiskReasonCode] = set()
        lifecycle = await self._pit.list_instruments_as_of(
            as_of.date(), context, market=instrument.market
        )
        if instrument not in lifecycle.records:
            decision = next(
                (
                    item
                    for item in lifecycle.decisions
                    if item.record_id == instrument.canonical_key
                ),
                None,
            )
            if decision is not None and decision.availability_source == "listing_date":
                reasons.add(RiskReasonCode.INSTRUMENT_NOT_LISTED)
                not_listed, delisted = True, False
            elif decision is not None and decision.availability_source == "known_delisting_date":
                reasons.add(RiskReasonCode.INSTRUMENT_DELISTED)
                not_listed, delisted = False, True
            else:
                reasons.add(RiskReasonCode.INSTRUMENT_STATUS_UNKNOWN)
                not_listed, delisted = True, False
            return reasons, TradingEligibility(True, not not_listed, delisted, False, False)
        status_result = await self._pit.list_trading_status_as_of(
            instrument, as_of.date(), as_of.date(), context
        )
        status = next(
            (item for item in status_result.records if item.trading_date == as_of.date()), None
        )
        if status is None or status.state is InstrumentTradingState.UNKNOWN:
            reasons.add(RiskReasonCode.INSTRUMENT_STATUS_UNKNOWN)
            known, suspended = False, False
        elif status.state is InstrumentTradingState.SUSPENDED:
            reasons.add(RiskReasonCode.INSTRUMENT_SUSPENDED)
            known, suspended = True, True
        else:
            known, suspended = True, False
        return reasons, TradingEligibility(True, True, False, suspended, known)

    async def _reference_price(
        self, instrument: InstrumentIdentity, as_of: datetime, context: PointInTimeContext
    ) -> Price | None:
        result = await self._pit.get_daily_bars_as_of(
            instrument, as_of.date(), as_of.date(), context
        )
        bar = next(
            (item.record for item in result.records if item.record.trading_date == as_of.date()),
            None,
        )
        return None if bar is None else Price(bar.close)

    async def _snapshot(
        self,
        state: ExecutionState,
        as_of: datetime,
        context: PointInTimeContext,
        reference: Price | None,
        instrument: InstrumentIdentity,
    ) -> PortfolioSnapshot | None:
        marks = await self._marks(state, as_of, context, allow_missing=True)
        if marks is None:
            return None
        if reference is not None:
            marks[instrument] = reference.value
        try:
            return state.account.snapshot(as_of, marks)
        except ValueError:
            return None

    async def _marks(
        self,
        state: ExecutionState,
        as_of: datetime,
        context: PointInTimeContext,
        allow_missing: bool = False,
    ) -> dict[InstrumentIdentity, Decimal] | None:
        marks: dict[InstrumentIdentity, Decimal] = {}
        for position in state.account.positions.values():
            if position.quantity == 0:
                continue
            price = await self._reference_price(position.key.instrument, as_of, context)
            if price is None:
                if allow_missing:
                    return None
                raise ValueError("accepted execution lost its PIT mark")
            marks[position.key.instrument] = price.value
        return marks

    def _reject(
        self,
        state: ExecutionState,
        order: Order,
        as_of: datetime,
        reasons: set[RiskReasonCode],
        snapshot: PortfolioSnapshot,
        settlement_event: SettlementRolloverEvent | None,
        eligibility: TradingEligibility,
        price_classification: PriceLimitClassification,
        summary: RiskInputSummary | None = None,
    ) -> ExecutionOutcome:
        state.orders_today += 1 if summary is None else 0
        summary = summary or self._neutral_summary(state, snapshot)
        decision = self._decision(order, as_of, tuple(reasons), summary, RiskDecisionType.REJECT)
        order = order.transition(OrderStatus.REJECTED)
        event = settlement_event
        state.pending_settlement_event = None
        audit_events = self._rejected_audit_events(order, eligibility, decision, as_of)
        return ExecutionOutcome(
            order,
            eligibility,
            decision,
            None,
            (),
            None,
            event,
            None,
            self.policy_versions,
            audit_events,
            {
                "price_limit": price_classification.value,
                "snapshot_as_of": snapshot.as_of.isoformat(),
            },
        )

    def _decision(
        self,
        order: Order,
        as_of: datetime,
        reasons: tuple[RiskReasonCode, ...],
        summary: RiskInputSummary,
        decision: RiskDecisionType,
    ) -> RiskDecision:
        material = (
            order.order_id.value,
            order.portfolio_id.value,
            order.instrument.canonical_key,
            order.side.value,
            str(order.quantity.value),
            as_of.isoformat(),
            decision.value,
            *(item.value for item in sorted(reasons, key=lambda value: value.value)),
            self._risk.version,
        )
        return RiskDecision(
            _stable_id("risk", *material),
            order.portfolio_id,
            order.order_id,
            as_of,
            decision,
            reasons,
            self._risk.version,
            summary,
        )

    @staticmethod
    def _neutral_summary(state: ExecutionState, snapshot: PortfolioSnapshot) -> RiskInputSummary:
        return RiskInputSummary(
            snapshot.nav,
            snapshot.cash,
            snapshot.market_value,
            snapshot.market_value,
            Money(Decimal("0")),
            snapshot.cash,
            state.orders_today,
            state.filled_orders_today,
            Money(state.daily_turnover),
        )

    def _risk_snapshot(
        self, state: ExecutionState, order: Order, snapshot: PortfolioSnapshot, as_of: datetime
    ) -> RiskSnapshot:
        exposures = tuple(item.market_value for item in snapshot.positions)
        largest = max(exposures, default=Decimal("0"))
        return RiskSnapshot(
            _stable_id("risk-snapshot", order.order_id.value, as_of.isoformat()),
            order.portfolio_id,
            as_of,
            snapshot.nav,
            snapshot.cash,
            snapshot.market_value,
            snapshot.cash.amount / snapshot.nav.amount,
            largest / snapshot.nav.amount,
            len(snapshot.positions),
            Money(state.daily_turnover),
            state.orders_today,
            state.filled_orders_today,
            self._risk.version,
        )

    async def _record(self, state: ExecutionState, outcome: ExecutionOutcome) -> ExecutionOutcome:
        if self._repository is not None:
            await self._repository.save(outcome)
        state.outcomes.append(outcome)
        return outcome

    def _rejected_audit_events(
        self,
        order: Order,
        eligibility: TradingEligibility,
        decision: RiskDecision,
        as_of: datetime,
    ) -> tuple[AuditEvent, ...]:
        return (
            self._audit(order, as_of, "ORDER_INTENT", order.order_id.value, {}),
            self._eligibility_event(order, eligibility, as_of),
            self._audit(
                order,
                as_of,
                "RISK_DECISION",
                decision.risk_decision_id,
                {"decision": decision.decision.value},
            ),
            self._audit(
                order,
                as_of,
                "ORDER_REJECTED",
                order.order_id.value,
                {"reasons": ",".join(item.value for item in decision.reason_codes)},
            ),
        )

    def _accepted_audit_events(
        self,
        order: Order,
        eligibility: TradingEligibility,
        decision: RiskDecision,
        fill: Fill,
        cash_entries: tuple[CashLedgerEntry, ...],
        settlement_position: SettlementPosition,
        risk_snapshot: RiskSnapshot,
        as_of: datetime,
    ) -> tuple[AuditEvent, ...]:
        values = [
            self._audit(order, as_of, "ORDER_INTENT", order.order_id.value, {}),
            self._eligibility_event(order, eligibility, as_of),
            self._audit(
                order,
                as_of,
                "RISK_DECISION",
                decision.risk_decision_id,
                {"decision": decision.decision.value},
            ),
            self._audit(order, as_of, "ORDER_ACCEPTED", order.order_id.value, {}),
            self._audit(
                order, as_of, "FILL", fill.fill_id.value, {"price": str(fill.fill_price.value)}
            ),
        ]
        values.extend(
            self._audit(
                order,
                as_of,
                "CASH_CHANGE",
                item.entry_id,
                {"amount": str(item.amount.amount)},
            )
            for item in cash_entries
        )
        values.extend(
            (
                self._audit(
                    order,
                    as_of,
                    "POSITION_SETTLEMENT",
                    fill.fill_id.value,
                    {"sellable": str(settlement_position.sellable_quantity)},
                ),
                self._audit(
                    order,
                    as_of,
                    "RISK_SNAPSHOT",
                    risk_snapshot.snapshot_id,
                    {"nav": str(risk_snapshot.nav.amount)},
                ),
                self._audit(
                    order,
                    as_of,
                    "NAV",
                    risk_snapshot.snapshot_id,
                    {"nav": str(risk_snapshot.nav.amount)},
                ),
            )
        )
        return tuple(values)

    def _eligibility_event(
        self, order: Order, eligibility: TradingEligibility, as_of: datetime
    ) -> AuditEvent:
        return self._audit(
            order,
            as_of,
            "ELIGIBILITY",
            order.order_id.value,
            {
                "market_open": str(eligibility.market_open).lower(),
                "listed": str(eligibility.instrument_listed).lower(),
                "delisted": str(eligibility.instrument_delisted).lower(),
                "suspended": str(eligibility.instrument_suspended).lower(),
                "status_known": str(eligibility.instrument_status_known).lower(),
            },
        )

    @staticmethod
    def _audit(
        order: Order,
        timestamp: datetime,
        event_type: str,
        source_id: str,
        payload: dict[str, str],
    ) -> AuditEvent:
        return AuditEvent(
            _stable_id("execution-audit", order.order_id.value, event_type, source_id),
            timestamp,
            event_type,
            source_id,
            order.portfolio_id,
            payload,
        )

    @staticmethod
    def _context(as_of: datetime) -> PointInTimeContext:
        return PointInTimeContext(as_of, AvailabilityMode.HISTORICAL_RESEARCH, AdjustmentMode.RAW)


def _stable_id(prefix: str, *parts: str) -> str:
    material = "|".join(parts)
    return f"{prefix}-{sha256(material.encode()).hexdigest()[:32]}"
