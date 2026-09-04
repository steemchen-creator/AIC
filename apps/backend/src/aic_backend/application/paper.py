"""Forward-only, PIT-safe daily-bar paper trading orchestration."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from aic_backend.application.execution import (
    AShareExecutionService,
    ExecutionCheckpoint,
    ExecutionOrderIntent,
    ExecutionState,
)
from aic_backend.application.point_in_time import AvailabilityMode, PointInTimeContext
from aic_backend.application.ports.paper import (
    PaperClock,
    PaperDecisionSource,
    PaperReadinessGate,
    PaperTradingRecord,
    PaperTradingRepository,
    PriceLimitBandSource,
)
from aic_backend.application.ports.persistence import PersistedDailyBar
from aic_backend.application.use_cases.point_in_time_market_data import PointInTimeMarketDataService
from aic_backend.domain.execution import ExecutionOutcome, SettlementBook
from aic_backend.domain.market_data import (
    AdjustmentMode,
    InstrumentIdentity,
    Market,
    TradingSession,
)
from aic_backend.domain.paper import (
    ActivatePaperAccount,
    CapitalMode,
    OperationalStatus,
    PaperAccount,
    PaperAccountStatus,
    PaperErrorCode,
    PaperMode,
    PaperOrderIntent,
    PaperPerformanceConfig,
    PaperPortfolioState,
    PaperProcessingCheckpoint,
    PaperRuntimeError,
    PaperSession,
    PaperSessionResult,
    PaperSessionStatus,
    PaperStateEvent,
    calculate_performance,
    derive_trade_episodes,
    filled_values,
    stable_id,
)
from aic_backend.domain.portfolio.accounting import PortfolioAccount
from aic_backend.domain.portfolio.models import Money, OrderId, PortfolioId


@dataclass(frozen=True, slots=True)
class ScriptedPaperDecisionSource:
    source_id: str
    intents: tuple[PaperOrderIntent, ...]

    async def intents_for(
        self, account_id: str, trading_date: date
    ) -> tuple[PaperOrderIntent, ...]:
        return tuple(
            intent
            for intent in self.intents
            if intent.account_id == account_id and intent.effective_trading_date == trading_date
        )


class PaperTradingRuntime:
    """Application service for the official forward-only paper account."""

    CHAMPION_NAME = "AIC Champion Paper Portfolio"
    CHAMPION_INITIAL_CAPITAL = Money(Decimal("500000"))
    SESSION_POLICY_VERSION = "daily-bar-forward-paper/v1"
    EXECUTION_POLICY_VERSION = "next-session-open/v1"

    def __init__(
        self,
        pit_market_data: PointInTimeMarketDataService,
        execution: AShareExecutionService,
        repository: PaperTradingRepository,
        readiness: PaperReadinessGate,
        price_limits: PriceLimitBandSource,
        clock: PaperClock,
        benchmark: InstrumentIdentity,
        performance_config: PaperPerformanceConfig | None = None,
        checkpoint_hook: Callable[[PaperProcessingCheckpoint], None] | None = None,
    ) -> None:
        if execution.availability_mode is not AvailabilityMode.OPERATIONAL_REPLAY:
            raise ValueError("paper execution must use OPERATIONAL_REPLAY")
        if execution.execution_policy_version != self.EXECUTION_POLICY_VERSION:
            raise ValueError("paper execution must use next-session-open/v1")
        self._pit = pit_market_data
        self._execution = execution
        self._repository = repository
        self._readiness = readiness
        self._price_limits = price_limits
        self._clock = clock
        self._benchmark = benchmark
        self._performance = performance_config or PaperPerformanceConfig()
        self._checkpoint_hook = checkpoint_hook

    async def create_champion(self) -> PaperAccount:
        now = self._now()
        account_id = stable_id("paper-account", self.CHAMPION_NAME, PaperMode.FORWARD_PAPER.value)
        existing = await self._repository.get(account_id)
        if existing is not None:
            return existing.account
        portfolio_id = PortfolioId(stable_id("paper-portfolio", account_id))
        account = PaperAccount(
            account_id,
            portfolio_id,
            self.CHAMPION_NAME,
            self.CHAMPION_INITIAL_CAPITAL,
            PaperMode.FORWARD_PAPER,
            CapitalMode.CONTINUOUS_COMPOUNDING,
            PaperAccountStatus.CREATED,
            now,
            now,
        )
        state = ExecutionState.initialize(portfolio_id, account.initial_capital, now)
        event = self._event(
            account,
            now,
            "ACCOUNT_CREATED",
            account.account_id,
            OperationalStatus.IDLE,
            to_status=PaperAccountStatus.CREATED.value,
            payload={"initial_capital": str(account.initial_capital.amount)},
        )
        await self._repository.save(
            PaperTradingRecord(account, self._freeze_state(state), events=(event,))
        )
        return account

    async def activate(self, command: ActivatePaperAccount) -> PaperAccount:
        record = await self._required_record(command.account_id)
        if record.account.status is PaperAccountStatus.RUNNING:
            return record.account
        if record.account.status not in {PaperAccountStatus.CREATED, PaperAccountStatus.READY}:
            raise PaperRuntimeError(
                PaperErrorCode.INVALID_ACCOUNT_STATE,
                f"cannot activate account from {record.account.status.value}",
            )
        failures = await self._readiness.check(record.account, command.requested_at)
        if failures:
            raise PaperRuntimeError(PaperErrorCode.READINESS_FAILED, ",".join(failures))
        account: PaperAccount = record.account
        events: list[PaperStateEvent] = []
        if account.status is PaperAccountStatus.CREATED:
            previous = account.status
            account = account.transition(PaperAccountStatus.READY, command.requested_at)
            events.append(
                self._event(
                    account,
                    command.requested_at,
                    "ACCOUNT_READY",
                    command.account_id,
                    OperationalStatus.READY,
                    from_status=previous.value,
                    to_status=account.status.value,
                )
            )
        activation_previous = account.status
        account = account.transition(PaperAccountStatus.RUNNING, command.requested_at)
        events.append(
            self._event(
                account,
                command.requested_at,
                "ACCOUNT_ACTIVATED",
                command.account_id,
                OperationalStatus.READY,
                from_status=activation_previous.value,
                to_status=account.status.value,
            )
        )
        await self._repository.save(
            replace(record, account=account, events=record.events + tuple(events))
        )
        return account

    async def pause(self, account_id: str, reason: str) -> PaperAccount:
        record = await self._required_record(account_id)
        if record.account.status is PaperAccountStatus.PAUSED:
            return record.account
        if record.account.status is not PaperAccountStatus.RUNNING:
            raise PaperRuntimeError(
                PaperErrorCode.INVALID_ACCOUNT_STATE,
                f"cannot pause account from {record.account.status.value}",
            )
        now = self._now()
        account = record.account.transition(PaperAccountStatus.PAUSED, now)
        event = self._event(
            account,
            now,
            "ACCOUNT_PAUSED",
            reason,
            OperationalStatus.PAUSED,
            from_status=record.account.status.value,
            to_status=account.status.value,
            payload={"reason": reason},
        )
        await self._repository.save(
            replace(record, account=account, events=record.events + (event,))
        )
        return account

    async def resume(self, account_id: str) -> PaperAccount:
        record = await self._required_record(account_id)
        if record.account.status is PaperAccountStatus.RUNNING:
            return record.account
        if record.account.status is not PaperAccountStatus.PAUSED:
            raise PaperRuntimeError(
                PaperErrorCode.INVALID_ACCOUNT_STATE,
                f"cannot resume account from {record.account.status.value}",
            )
        now = self._now()
        failures = await self._readiness.check(record.account, now)
        if failures:
            raise PaperRuntimeError(PaperErrorCode.READINESS_FAILED, ",".join(failures))
        account = record.account.transition(PaperAccountStatus.RUNNING, now)
        event = self._event(
            account,
            now,
            "ACCOUNT_RESUMED",
            account_id,
            OperationalStatus.READY,
            from_status=record.account.status.value,
            to_status=account.status.value,
        )
        await self._repository.save(
            replace(record, account=account, events=record.events + (event,))
        )
        return account

    async def stop(self, account_id: str) -> PaperAccount:
        record = await self._required_record(account_id)
        if record.account.status is PaperAccountStatus.STOPPED:
            return record.account
        if record.account.status not in {PaperAccountStatus.RUNNING, PaperAccountStatus.PAUSED}:
            raise PaperRuntimeError(
                PaperErrorCode.INVALID_ACCOUNT_STATE,
                f"cannot stop account from {record.account.status.value}",
            )
        now = self._now()
        account = record.account.transition(PaperAccountStatus.STOPPED, now)
        event = self._event(
            account,
            now,
            "ACCOUNT_STOPPED",
            account_id,
            OperationalStatus.STOPPED,
            from_status=record.account.status.value,
            to_status=account.status.value,
        )
        await self._repository.save(
            replace(record, account=account, events=record.events + (event,))
        )
        return account

    async def process_session(
        self,
        account_id: str,
        trading_date: date,
        decisions: PaperDecisionSource,
    ) -> PaperSessionResult | None:
        record = await self._required_record(account_id)
        if record.account.status is not PaperAccountStatus.RUNNING:
            raise PaperRuntimeError(
                PaperErrorCode.INVALID_ACCOUNT_STATE,
                "paper account must be RUNNING to process a session",
            )
        existing = next(
            (item for item in record.sessions if item.trading_date == trading_date), None
        )
        if record.account.last_finalized_date is not None:
            if trading_date < record.account.last_finalized_date:
                raise PaperRuntimeError(
                    PaperErrorCode.FORWARD_ONLY_VIOLATION,
                    "backdated paper session cannot rewrite finalized history",
                )
            if trading_date == record.account.last_finalized_date:
                if existing is None or existing.status is not PaperSessionStatus.FINALIZED:
                    raise PaperRuntimeError(
                        PaperErrorCode.STATE_INCONSISTENCY,
                        "finalized account date has no immutable finalized session",
                    )
                return self._existing_result(record, existing)

        now = self._now()
        context = PointInTimeContext(now, AvailabilityMode.OPERATIONAL_REPLAY, AdjustmentMode.RAW)
        intents = tuple(
            sorted(
                await decisions.intents_for(account_id, trading_date),
                key=lambda item: item.intent_id,
            )
        )
        self._validate_intents(record.account, intents, trading_date)
        state = self._thaw_state(record.account, record.portfolio_state)
        markets = {
            self._benchmark.market,
            *(intent.instrument.market for intent in intents),
            *(
                position.key.instrument.market
                for position in state.account.positions.values()
                if position.quantity
            ),
        }
        sessions: dict[Market, TradingSession] = {}
        for market in sorted(markets, key=lambda item: item.value):
            result = await self._pit.list_calendar_as_of(
                market, trading_date, trading_date, context
            )
            day = next((item for item in result.records if item.trading_date == trading_date), None)
            if day is None:
                await self._block(
                    record,
                    existing,
                    trading_date,
                    now,
                    PaperErrorCode.PIT_DATA_UNAVAILABLE,
                    "calendar evidence unavailable",
                )
            assert day is not None
            if not day.is_open:
                return None
            assert day.session is not None
            sessions[market] = day.session
        if any(now < session.session_close for session in sessions.values()):
            await self._block(
                record,
                existing,
                trading_date,
                now,
                PaperErrorCode.SESSION_FINALIZATION_BLOCKED,
                "daily-bar session cannot finalize before market close",
            )

        session = existing or PaperSession(
            stable_id("paper-session", account_id, trading_date),
            account_id,
            trading_date,
            PaperSessionStatus.PLANNED,
            now,
            None,
            None,
            self.SESSION_POLICY_VERSION,
        )
        new_events: list[PaperStateEvent] = []
        if session.status is PaperSessionStatus.PLANNED:
            new_events.append(
                self._event(
                    record.account,
                    now,
                    "SESSION_PLANNED",
                    session.session_id,
                    OperationalStatus.READY,
                    session_id=session.session_id,
                    to_status=session.status.value,
                )
            )
            session = session.transition(PaperSessionStatus.OPEN, now)
            new_events.append(
                self._event(
                    record.account,
                    now,
                    "SESSION_OPENED",
                    session.session_id,
                    OperationalStatus.READY,
                    session_id=session.session_id,
                    to_status=session.status.value,
                )
            )
        session = session.transition(PaperSessionStatus.PROCESSING, now)
        new_events.append(
            self._event(
                record.account,
                now,
                "PROCESSING_ORDERS",
                decisions.source_id,
                OperationalStatus.PROCESSING_ORDERS,
                session_id=session.session_id,
            )
        )
        instruments = {
            *(intent.instrument for intent in intents),
            *(
                position.key.instrument
                for position in state.account.positions.values()
                if position.quantity
            ),
        }
        for instrument in sorted(instruments, key=lambda item: item.canonical_key):
            actions = await self._pit.list_corporate_actions_as_of(
                instrument, trading_date, trading_date, context
            )
            if actions.records:
                await self._block(
                    record,
                    session,
                    trading_date,
                    now,
                    PaperErrorCode.UNSUPPORTED_CORPORATE_ACTION,
                    f"unsupported corporate action for {instrument.canonical_key}",
                    tuple(new_events),
                )
        await self._preflight_marks(record, session, state, trading_date, context, new_events)
        for market in sorted(markets, key=lambda item: item.value):
            await self._execution.advance_session(state, market, now)

        outcomes: list[ExecutionOutcome] = []
        for intent in intents:
            market_session = sessions[intent.instrument.market]
            if intent.submitted_at >= market_session.morning_open or intent.submitted_at >= now:
                raise PaperRuntimeError(
                    PaperErrorCode.INVALID_ORDER_TIMING,
                    "NEXT_OPEN intent must exist before the target session opens",
                )
            band = await self._price_limits.get_band(intent.instrument, trading_date, now)
            new_events.append(
                self._event(
                    record.account,
                    now,
                    "ORDER_INTENT",
                    intent.intent_id,
                    OperationalStatus.RISK_CHECKING,
                    session_id=session.session_id,
                    payload={
                        "source_reference": intent.source_reference,
                        "timing": intent.timing.value,
                    },
                )
            )
            outcome = await self._execution.execute(
                state,
                ExecutionOrderIntent(
                    intent.instrument,
                    intent.side,
                    intent.quantity,
                    intent.requested_price,
                ),
                OrderId(stable_id("paper-order", account_id, intent.intent_id)),
                now,
                band,
                checkpoint=self._execution_checkpoint,
            )
            outcomes.append(outcome)

        session = session.transition(PaperSessionStatus.MARKING, now)
        new_events.append(
            self._event(
                record.account,
                now,
                "MARKING_TO_MARKET",
                session.session_id,
                OperationalStatus.MARKING_TO_MARKET,
                session_id=session.session_id,
            )
        )
        marks: dict[InstrumentIdentity, Decimal] = {}
        for position in state.account.positions.values():
            if not position.quantity:
                continue
            bar = await self._daily_bar(position.key.instrument, trading_date, context)
            if bar is None:
                await self._block(
                    record,
                    session,
                    trading_date,
                    now,
                    PaperErrorCode.MARK_DATA_UNAVAILABLE,
                    f"missing PIT mark for {position.key.instrument.canonical_key}",
                    tuple(new_events),
                )
            assert bar is not None
            marks[position.key.instrument] = bar.record.close
        snapshot = state.account.snapshot(now, marks)
        state.last_snapshot = snapshot
        benchmark_bar = await self._daily_bar(self._benchmark, trading_date, context)
        if benchmark_bar is None:
            await self._block(
                record,
                session,
                trading_date,
                now,
                PaperErrorCode.MARK_DATA_UNAVAILABLE,
                "benchmark mark unavailable",
                tuple(new_events),
            )
        assert benchmark_bar is not None
        all_outcomes = record.outcomes + tuple(outcomes)
        all_fills = filled_values(all_outcomes)
        performance = calculate_performance(
            record.account,
            session,
            snapshot,
            record.performance,
            benchmark_bar.record.close,
            all_fills,
            self._performance,
        )
        all_dates = tuple(item.trading_date for item in record.sessions) + (trading_date,)
        episodes = derive_trade_episodes(account_id, all_fills, all_dates)
        existing_episode_ids = {item.episode_id for item in record.episodes}
        new_episodes = tuple(
            item for item in episodes if item.episode_id not in existing_episode_ids
        )
        self._checkpoint(PaperProcessingCheckpoint.AFTER_SNAPSHOT_BEFORE_FINALIZATION)
        session = session.transition(PaperSessionStatus.FINALIZED, now)
        account = record.account.finalize(trading_date, now)
        new_events.append(
            self._event(
                account,
                now,
                "EOD_MARK",
                session.session_id,
                OperationalStatus.MARKING_TO_MARKET,
                session_id=session.session_id,
                payload={"position_count": str(performance.position_count)},
            )
        )
        new_events.append(
            self._event(
                account,
                now,
                "NAV_SNAPSHOT",
                performance.snapshot_id,
                OperationalStatus.FINALIZING,
                session_id=session.session_id,
                payload={"nav": str(performance.nav.amount)},
            )
        )
        new_events.append(
            self._event(
                account,
                now,
                "PERFORMANCE_SNAPSHOT",
                performance.snapshot_id,
                OperationalStatus.FINALIZING,
                session_id=session.session_id,
                payload={"nav": str(performance.nav.amount)},
            )
        )
        new_events.append(
            self._event(
                account,
                now,
                "SESSION_FINALIZED",
                session.session_id,
                OperationalStatus.IDLE,
                session_id=session.session_id,
                to_status=session.status.value,
            )
        )
        updated = PaperTradingRecord(
            account,
            self._freeze_state(state),
            self._upsert_session(record.sessions, session),
            record.intents + tuple(intent for intent in intents if intent not in record.intents),
            all_outcomes,
            record.performance + (performance,),
            record.episodes + new_episodes,
            self._unique_events(record.events + tuple(new_events)),
        )
        await self._repository.save(updated)
        return PaperSessionResult(
            session,
            intents,
            tuple(outcomes),
            performance,
            new_episodes,
            tuple(new_events),
        )

    async def _preflight_marks(
        self,
        record: PaperTradingRecord,
        session: PaperSession,
        state: ExecutionState,
        trading_date: date,
        context: PointInTimeContext,
        events: list[PaperStateEvent],
    ) -> None:
        for position in state.account.positions.values():
            if (
                position.quantity
                and await self._daily_bar(position.key.instrument, trading_date, context) is None
            ):
                await self._block(
                    record,
                    session,
                    trading_date,
                    context.as_of,
                    PaperErrorCode.MARK_DATA_UNAVAILABLE,
                    f"missing PIT mark for {position.key.instrument.canonical_key}",
                    tuple(events),
                )

    async def _daily_bar(
        self,
        instrument: InstrumentIdentity,
        trading_date: date,
        context: PointInTimeContext,
    ) -> PersistedDailyBar | None:
        result = await self._pit.get_daily_bars_as_of(
            instrument, trading_date, trading_date, context
        )
        return next(
            (item for item in result.records if item.record.trading_date == trading_date),
            None,
        )

    async def _block(
        self,
        record: PaperTradingRecord,
        session: PaperSession | None,
        trading_date: date,
        now: datetime,
        code: PaperErrorCode,
        message: str,
        preceding_events: tuple[PaperStateEvent, ...] = (),
    ) -> None:
        blocked = session or PaperSession(
            stable_id("paper-session", record.account.account_id, trading_date),
            record.account.account_id,
            trading_date,
            PaperSessionStatus.PLANNED,
            now,
            None,
            None,
            self.SESSION_POLICY_VERSION,
        )
        if blocked.status is not PaperSessionStatus.BLOCKED:
            blocked = blocked.transition(PaperSessionStatus.BLOCKED, now)
        account = record.account
        if account.status is PaperAccountStatus.RUNNING:
            account = account.transition(PaperAccountStatus.PAUSED, now)
        event = self._event(
            account,
            now,
            code.value,
            blocked.session_id,
            OperationalStatus.WAITING_FOR_MARKET_DATA,
            session_id=blocked.session_id,
            from_status=record.account.status.value,
            to_status=account.status.value,
            payload={"message": message},
        )
        updated = replace(
            record,
            account=account,
            sessions=self._upsert_session(record.sessions, blocked),
            events=self._unique_events(record.events + preceding_events + (event,)),
        )
        await self._repository.save(updated)
        raise PaperRuntimeError(PaperErrorCode.SESSION_FINALIZATION_BLOCKED, message)

    def _execution_checkpoint(self, value: ExecutionCheckpoint) -> None:
        mapping = {
            ExecutionCheckpoint.RISK_DECISION_RECORDED: (
                PaperProcessingCheckpoint.AFTER_RISK_BEFORE_FILL
            ),
            ExecutionCheckpoint.FILL_CREATED: (
                PaperProcessingCheckpoint.AFTER_FILL_BEFORE_ACCOUNTING
            ),
            ExecutionCheckpoint.ACCOUNTING_APPLIED: (
                PaperProcessingCheckpoint.AFTER_ACCOUNTING_BEFORE_SNAPSHOT
            ),
        }
        self._checkpoint(mapping[value])

    def _checkpoint(self, value: PaperProcessingCheckpoint) -> None:
        if self._checkpoint_hook is not None:
            self._checkpoint_hook(value)

    async def _required_record(self, account_id: str) -> PaperTradingRecord:
        record = await self._repository.get(account_id)
        if record is None:
            raise PaperRuntimeError(
                PaperErrorCode.ACCOUNT_NOT_FOUND, f"paper account not found: {account_id}"
            )
        return record

    def _now(self) -> datetime:
        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("paper clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _validate_intents(
        account: PaperAccount,
        intents: tuple[PaperOrderIntent, ...],
        trading_date: date,
    ) -> None:
        ids: set[str] = set()
        for intent in intents:
            if intent.account_id != account.account_id:
                raise PaperRuntimeError(
                    PaperErrorCode.STATE_INCONSISTENCY,
                    "order intent belongs to another paper account",
                )
            if intent.effective_trading_date != trading_date:
                raise PaperRuntimeError(
                    PaperErrorCode.INVALID_ORDER_TIMING,
                    "order intent effective date does not match the session",
                )
            if intent.intent_id in ids:
                raise PaperRuntimeError(
                    PaperErrorCode.STATE_INCONSISTENCY, "duplicate order intent identity"
                )
            ids.add(intent.intent_id)

    @staticmethod
    def _freeze_state(state: ExecutionState) -> PaperPortfolioState:
        return PaperPortfolioState(
            Money(state.account.cash),
            tuple(
                sorted(
                    state.account.positions.values(),
                    key=lambda item: item.key.instrument.canonical_key,
                )
            ),
            tuple(state.account.cash_ledger),
            tuple(
                sorted(
                    state.settlement.positions.values(),
                    key=lambda item: item.instrument.canonical_key,
                )
            ),
            state.last_snapshot,
            state.settlement.last_trading_date,
            state.activity_date,
            state.orders_today,
            state.filled_orders_today,
            state.daily_turnover,
        )

    @staticmethod
    def _thaw_state(account: PaperAccount, value: PaperPortfolioState) -> ExecutionState:
        portfolio = PortfolioAccount(account.portfolio_id, account.initial_capital)
        portfolio.cash = value.cash.amount
        portfolio.positions = {item.key.instrument.canonical_key: item for item in value.positions}
        portfolio.cash_ledger = list(value.cash_ledger)
        settlement = SettlementBook(account.portfolio_id)
        for item in value.settlement_positions:
            settlement.seed(item)
        settlement.last_trading_date = value.last_trading_date
        return ExecutionState(
            portfolio,
            settlement,
            value.last_snapshot,
            value.activity_date,
            value.orders_today,
            value.filled_orders_today,
            value.daily_turnover,
        )

    @staticmethod
    def _upsert_session(
        sessions: tuple[PaperSession, ...], value: PaperSession
    ) -> tuple[PaperSession, ...]:
        return tuple(item for item in sessions if item.session_id != value.session_id) + (value,)

    @staticmethod
    def _unique_events(events: tuple[PaperStateEvent, ...]) -> tuple[PaperStateEvent, ...]:
        values: dict[str, PaperStateEvent] = {}
        for event in events:
            existing = values.get(event.event_id)
            if existing is not None and existing != event:
                raise PaperRuntimeError(
                    PaperErrorCode.STATE_INCONSISTENCY,
                    "paper event identity identifies different evidence",
                )
            values[event.event_id] = event
        return tuple(values.values())

    def _event(
        self,
        account: PaperAccount,
        occurred_at: datetime,
        event_type: str,
        source_id: str,
        operational_status: OperationalStatus,
        *,
        session_id: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        payload: dict[str, str] | None = None,
    ) -> PaperStateEvent:
        return PaperStateEvent(
            stable_id(
                "paper-event",
                account.account_id,
                event_type,
                source_id,
                session_id or "account",
                occurred_at.isoformat(),
            ),
            account.account_id,
            occurred_at,
            event_type,
            source_id,
            operational_status,
            session_id,
            from_status,
            to_status,
            payload or {},
        )

    @staticmethod
    def _existing_result(record: PaperTradingRecord, session: PaperSession) -> PaperSessionResult:
        performance = next(
            item for item in record.performance if item.session_id == session.session_id
        )
        intents = tuple(
            item for item in record.intents if item.effective_trading_date == session.trading_date
        )
        order_ids = {
            stable_id("paper-order", record.account.account_id, item.intent_id) for item in intents
        }
        outcomes = tuple(item for item in record.outcomes if item.order.order_id.value in order_ids)
        events = tuple(item for item in record.events if item.session_id == session.session_id)
        return PaperSessionResult(session, intents, outcomes, performance, (), events)
