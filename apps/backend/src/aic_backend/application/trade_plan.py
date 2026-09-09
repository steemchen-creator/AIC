"""Trade Plan use cases and authoritative execution orchestration."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from aic_backend.application.execution import ExecutionOrderIntent, ExecutionState
from aic_backend.application.point_in_time import AvailabilityMode, PointInTimeContext
from aic_backend.application.ports.trade_plan import (
    AuthoritativeExecution,
    NextEligibleOpenCalendar,
    TradePlanRepository,
)
from aic_backend.application.trade_plan_record import TradePlanRecord
from aic_backend.application.use_cases.point_in_time_market_data import (
    PointInTimeMarketDataService,
)
from aic_backend.domain.execution import PriceLimitBand, RiskDecisionType
from aic_backend.domain.market_data import InstrumentIdentity
from aic_backend.domain.portfolio.models import (
    OrderId,
    OrderSide,
    PortfolioId,
    Price,
    Quantity,
)
from aic_backend.domain.trade_plan import (
    DirectiveType,
    HardStopPolicy,
    InvestmentHorizon,
    PlanExecutionEvidence,
    PlanObservation,
    ProfitTarget,
    TimeStopPolicy,
    TradePlan,
    TradePlanDirective,
    TradePlanError,
    TradePlanErrorCode,
    TradePlanId,
    TradePlanOutcome,
    TradePlanRevision,
    TradePlanStatus,
    TradingStyle,
    TrailingStopPolicy,
    TriggerType,
    stable_plan_id,
)


def _trade_time(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TradePlanError(
            TradePlanErrorCode.INVALID_TIMESTAMP,
            f"{field} must include timezone information",
        )
    return value


@dataclass(frozen=True, slots=True)
class CreateDraftPlan:
    plan_id: TradePlanId
    portfolio_id: PortfolioId
    instrument: InstrumentIdentity
    horizon: InvestmentHorizon
    style: TradingStyle
    thesis: str
    target_quantity: Quantity
    created_at: datetime
    expiry_at: datetime | None = None
    thesis_invalidation_reference: str | None = None
    hard_stop: HardStopPolicy | None = None
    profit_targets: tuple[ProfitTarget, ...] = ()
    trailing_stop: TrailingStopPolicy | None = None
    time_stop: TimeStopPolicy | None = None
    policy_version: str = "trade-plan/v1"


@dataclass(frozen=True, slots=True)
class PlanAmendment:
    expected_version: int
    reason: str
    actor: str
    source: str
    recorded_at: datetime
    horizon: InvestmentHorizon | None = None
    style: TradingStyle | None = None
    hard_stop: HardStopPolicy | None = None
    profit_targets: tuple[ProfitTarget, ...] | None = None
    trailing_stop: TrailingStopPolicy | None = None
    time_stop: TimeStopPolicy | None = None
    thesis_invalidation_reference: str | None = None


@dataclass(frozen=True, slots=True)
class OutcomeInputs:
    average_entry_price: Decimal | None
    remaining_quantity: Decimal
    realized_pnl: Decimal


class PointInTimeNextOpenCalendar:
    """Resolve the next open only from the existing PIT calendar authority."""

    def __init__(
        self,
        market_data: PointInTimeMarketDataService,
        *,
        availability_mode: AvailabilityMode = AvailabilityMode.HISTORICAL_RESEARCH,
        search_days: int = 31,
    ) -> None:
        if search_days < 1:
            raise ValueError("search_days must be positive")
        self._market_data = market_data
        self._availability_mode = availability_mode
        self._search_days = search_days

    async def next_open(self, instrument: InstrumentIdentity, decision_at: datetime) -> datetime:
        decision_at = _trade_time(decision_at, "decision_at")
        start = decision_at.date() + timedelta(days=1)
        end = start + timedelta(days=self._search_days - 1)
        result = await self._market_data.list_calendar_as_of(
            instrument.market,
            start,
            end,
            PointInTimeContext(decision_at, self._availability_mode),
        )
        eligible = tuple(
            item.session.morning_open
            for item in result.records
            if item.is_open and item.session is not None and item.session.morning_open > decision_at
        )
        if not eligible:
            raise TradePlanError(
                TradePlanErrorCode.FUTURE_EVIDENCE,
                "next eligible open is unavailable from PIT calendar",
            )
        return min(eligible)


class TradePlanService:
    def __init__(
        self,
        repository: TradePlanRepository,
        calendar: NextEligibleOpenCalendar,
        execution: AuthoritativeExecution,
    ) -> None:
        self._repository = repository
        self._calendar = calendar
        self._execution = execution

    async def create_draft(self, command: CreateDraftPlan) -> TradePlan:
        plan = TradePlan(
            command.plan_id,
            command.portfolio_id,
            command.instrument,
            command.horizon,
            command.style,
            command.thesis,
            command.target_quantity,
            command.created_at,
            command.created_at,
            expiry_at=command.expiry_at,
            thesis_invalidation_reference=command.thesis_invalidation_reference,
            hard_stop=command.hard_stop,
            profit_targets=command.profit_targets,
            trailing_stop=command.trailing_stop,
            time_stop=command.time_stop,
            policy_version=command.policy_version,
        )
        existing = await self._repository.get(plan.plan_id)
        if existing is not None:
            if existing.plan != plan:
                raise TradePlanError(
                    TradePlanErrorCode.DIRECTIVE_CONFLICT,
                    "plan id identifies different evidence",
                )
            return existing.plan
        await self._repository.save(TradePlanRecord(plan))
        return plan

    async def edit_draft(self, plan_id: TradePlanId, command: CreateDraftPlan) -> TradePlan:
        record = await self._required(plan_id)
        if record.plan.status is not TradePlanStatus.DRAFT:
            raise TradePlanError(
                TradePlanErrorCode.PROTECTED_FIELD_MUTATION,
                "activated or terminal plan cannot be edited in place",
            )
        if command.plan_id != plan_id or command.portfolio_id != record.plan.portfolio_id:
            raise TradePlanError(
                TradePlanErrorCode.PROTECTED_FIELD_MUTATION,
                "draft identity cannot be changed",
            )
        plan = TradePlan(
            command.plan_id,
            command.portfolio_id,
            command.instrument,
            command.horizon,
            command.style,
            command.thesis,
            command.target_quantity,
            record.plan.created_at,
            command.created_at,
            expiry_at=command.expiry_at,
            thesis_invalidation_reference=command.thesis_invalidation_reference,
            hard_stop=command.hard_stop,
            profit_targets=command.profit_targets,
            trailing_stop=command.trailing_stop,
            time_stop=command.time_stop,
            policy_version=command.policy_version,
        )
        await self._repository.save(replace(record, plan=plan))
        return plan

    async def activate(
        self, plan_id: TradePlanId, at: datetime, *, actor: str, source: str
    ) -> TradePlan:
        record = await self._required(plan_id)
        if record.plan.status is TradePlanStatus.ACTIVE:
            return record.plan
        active = await self._repository.get_active(
            record.plan.portfolio_id.value, record.plan.instrument.canonical_key
        )
        if active is not None and active.plan.plan_id != plan_id:
            raise TradePlanError(
                TradePlanErrorCode.DUPLICATE_ACTIVE_PLAN,
                "portfolio and instrument already have an active plan",
            )
        plan = record.plan.activate(at)
        revision = self._revision(plan, at, "ACTIVATED", actor, source)
        await self._repository.save(replace(record, plan=plan, revisions=(revision,)))
        return plan

    async def revise(self, plan_id: TradePlanId, change: PlanAmendment) -> TradePlan:
        record = await self._required(plan_id)
        plan = record.plan
        if plan.status is not TradePlanStatus.ACTIVE:
            raise TradePlanError(
                TradePlanErrorCode.TERMINAL_IMMUTABLE,
                "only active plans can be revised",
            )
        if change.expected_version != plan.version:
            raise TradePlanError(TradePlanErrorCode.STALE_VERSION, "stale plan version")
        if change.recorded_at < plan.updated_at:
            raise TradePlanError(TradePlanErrorCode.STALE_VERSION, "stale amendment time")
        if change.horizon is not None and change.horizon is not plan.horizon:
            raise TradePlanError(
                TradePlanErrorCode.PROTECTED_FIELD_MUTATION,
                "active horizon is immutable",
            )
        if change.style is not None and change.style is not plan.style:
            raise TradePlanError(
                TradePlanErrorCode.PROTECTED_FIELD_MUTATION,
                "active style is immutable",
            )
        at = change.recorded_at
        plan = replace(
            plan,
            hard_stop=change.hard_stop or plan.hard_stop,
            profit_targets=(
                plan.profit_targets if change.profit_targets is None else change.profit_targets
            ),
            trailing_stop=change.trailing_stop or plan.trailing_stop,
            time_stop=change.time_stop or plan.time_stop,
            thesis_invalidation_reference=(
                change.thesis_invalidation_reference or plan.thesis_invalidation_reference
            ),
            version=plan.version + 1,
            updated_at=at,
        )
        revision = self._revision(plan, at, change.reason, change.actor, change.source)
        await self._repository.save(
            replace(record, plan=plan, revisions=record.revisions + (revision,))
        )
        return plan

    async def evaluate(
        self, plan_id: TradePlanId, observation: PlanObservation, as_of: datetime
    ) -> TradePlanDirective:
        as_of = _trade_time(as_of, "as_of")
        record = await self._required(plan_id)
        plan = record.plan
        if plan.status is not TradePlanStatus.ACTIVE:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_TRANSITION, "only active plans can be evaluated"
            )
        if observation.event_at > as_of or observation.available_at > as_of:
            raise TradePlanError(
                TradePlanErrorCode.FUTURE_EVIDENCE, "observation is unavailable as_of"
            )
        visible_revisions = tuple(
            revision for revision in record.revisions if revision.effective_at <= as_of
        )
        if not visible_revisions:
            raise TradePlanError(
                TradePlanErrorCode.FUTURE_EVIDENCE,
                "no Trade Plan revision is available as_of",
            )
        revision = visible_revisions[-1]
        high_water = revision.trailing_high_water
        trailing_stop = revision.trailing_stop
        if (
            revision.version == plan.version
            and trailing_stop is not None
            and (high_water is None or observation.high > high_water)
        ):
            high_water = observation.high
            plan = replace(plan, version=plan.version + 1, updated_at=as_of)
            revision = self._revision(
                plan,
                as_of,
                "TRAILING_HIGH_WATER",
                "trade-plan-evaluator",
                observation.observation_id,
                high_water,
            )
            record = replace(record, plan=plan, revisions=record.revisions + (revision,))
            await self._repository.save(record)
        elif trailing_stop is not None and high_water is None:
            high_water = observation.high
        directive_type = DirectiveType.HOLD
        trigger = TriggerType.NO_TRIGGER
        quantity: Quantity | None = None
        terminal: TradePlanStatus | None = None
        if revision.expiry_at is not None and as_of >= revision.expiry_at:
            directive_type, trigger, terminal = (
                DirectiveType.EXIT,
                TriggerType.EXPIRY,
                TradePlanStatus.EXPIRED,
            )
        elif revision.time_stop is not None and as_of >= revision.time_stop.deadline:
            directive_type = revision.time_stop.action
            quantity = revision.time_stop.quantity
            trigger = TriggerType.TIME_STOP
        elif revision.hard_stop is not None and observation.close <= revision.hard_stop.price:
            directive_type = revision.hard_stop.action
            quantity = revision.hard_stop.quantity
            trigger = TriggerType.HARD_STOP
        elif (
            trailing_stop is not None
            and high_water is not None
            and observation.close <= high_water * (Decimal("1") - trailing_stop.distance_pct)
        ):
            directive_type = trailing_stop.action
            quantity = trailing_stop.quantity
            trigger = TriggerType.TRAILING_STOP
        else:
            target = next(
                (item for item in revision.profit_targets if observation.close >= item.price),
                None,
            )
            if target is not None:
                directive_type, quantity, trigger = (
                    target.action,
                    target.quantity,
                    TriggerType.PROFIT_TARGET,
                )
        directive = await self._new_directive(
            record,
            directive_type,
            quantity,
            trigger,
            as_of,
            observation.observation_id,
            plan_version=revision.version,
        )
        if terminal is not None and revision.version == plan.version:
            record = await self._required(plan_id)
            await self._repository.save(
                replace(
                    record,
                    plan=record.plan.transition(terminal, as_of, trigger.value),
                )
            )
        return directive

    async def record_thesis_invalidation(
        self,
        plan_id: TradePlanId,
        *,
        event_reference: str,
        as_of: datetime,
    ) -> TradePlanDirective:
        record = await self._required(plan_id)
        plan = record.plan
        if plan.status is not TradePlanStatus.ACTIVE:
            raise TradePlanError(TradePlanErrorCode.INVALID_TRANSITION, "plan is not active")
        if plan.thesis_invalidation_reference is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "no structured invalidation policy"
            )
        directive = await self._new_directive(
            record,
            DirectiveType.EXIT,
            None,
            TriggerType.THESIS_INVALIDATION,
            as_of,
            event_reference,
        )
        updated = await self._required(plan_id)
        await self._repository.save(
            replace(
                updated,
                plan=updated.plan.transition(
                    TradePlanStatus.INVALIDATED, as_of, f"THESIS_INVALIDATED:{event_reference}"
                ),
            )
        )
        return directive

    async def create_directive(
        self,
        plan_id: TradePlanId,
        directive_type: DirectiveType,
        quantity: Quantity | None,
        as_of: datetime,
        *,
        source_reference: str,
    ) -> TradePlanDirective:
        record = await self._required(plan_id)
        if record.plan.status is not TradePlanStatus.ACTIVE:
            raise TradePlanError(TradePlanErrorCode.INVALID_TRANSITION, "plan is not active")
        return await self._new_directive(
            record,
            directive_type,
            quantity,
            TriggerType.MANUAL,
            as_of,
            source_reference,
        )

    async def execute_directive(
        self,
        directive_id: str,
        state: ExecutionState,
        execution_at: datetime,
        *,
        position_quantity: Quantity | None = None,
        requested_price: Price | None = None,
        price_limit_band: PriceLimitBand | None = None,
    ) -> PlanExecutionEvidence:
        execution_at = _trade_time(execution_at, "execution_at")
        record, directive = await self._find_directive(directive_id)
        prior = next(
            (item for item in record.executions if item.directive_id == directive_id), None
        )
        if prior is not None:
            return prior
        if directive.directive_type is DirectiveType.HOLD:
            raise TradePlanError(
                TradePlanErrorCode.DIRECTIVE_NOT_EXECUTABLE, "HOLD never creates an order"
            )
        if directive.not_before is None or execution_at < directive.not_before:
            raise TradePlanError(
                TradePlanErrorCode.EXECUTION_TOO_EARLY, "execution precedes eligible open"
            )
        quantity = (
            position_quantity
            if directive.directive_type is DirectiveType.EXIT
            else directive.quantity
        )
        if quantity is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "execution quantity is unavailable"
            )
        side = (
            OrderSide.BUY
            if directive.directive_type in (DirectiveType.ENTRY, DirectiveType.SCALE_IN)
            else OrderSide.SELL
        )
        order_id = OrderId(stable_plan_id("order", directive_id))
        outcome = await self._execution.execute(
            state,
            ExecutionOrderIntent(record.plan.instrument, side, quantity, requested_price),
            order_id,
            execution_at,
            price_limit_band,
        )
        evidence = PlanExecutionEvidence(
            stable_plan_id("execution", directive_id),
            record.plan.plan_id,
            directive.plan_version,
            directive.directive_id,
            directive.directive_type,
            outcome.order.order_id.value,
            None if outcome.fill is None else outcome.fill.fill_id.value,
            execution_at,
            tuple(item.value for item in outcome.risk_decision.reason_codes),
        )
        updated = replace(record, executions=record.executions + (evidence,))
        if (
            outcome.risk_decision.decision is RiskDecisionType.ALLOW
            and directive.directive_type is DirectiveType.EXIT
            and updated.plan.status is TradePlanStatus.ACTIVE
        ):
            updated = replace(
                updated,
                plan=updated.plan.transition(
                    TradePlanStatus.COMPLETED, execution_at, "EXIT_FILLED"
                ),
            )
        await self._repository.save(updated)
        return evidence

    async def transition_terminal(
        self,
        plan_id: TradePlanId,
        status: TradePlanStatus,
        at: datetime,
        reason: str,
    ) -> TradePlan:
        record = await self._required(plan_id)
        plan = record.plan.transition(status, at, reason)
        await self._repository.save(replace(record, plan=plan))
        return plan

    async def active_plan(
        self, portfolio_id: PortfolioId, instrument: InstrumentIdentity
    ) -> TradePlan | None:
        value = await self._repository.get_active(portfolio_id.value, instrument.canonical_key)
        return None if value is None else value.plan

    async def history(
        self, portfolio_id: PortfolioId, instrument: InstrumentIdentity
    ) -> tuple[TradePlanRecord, ...]:
        return await self._repository.list_for_pair(portfolio_id.value, instrument.canonical_key)

    async def build_outcome(self, plan_id: TradePlanId, values: OutcomeInputs) -> TradePlanOutcome:
        record = await self._required(plan_id)
        plan = record.plan
        if plan.status in (TradePlanStatus.DRAFT, TradePlanStatus.ACTIVE):
            raise TradePlanError(
                TradePlanErrorCode.INVALID_TRANSITION, "outcome requires a terminal plan"
            )
        if record.outcome is not None:
            return record.outcome
        if plan.activated_at is None or plan.terminal_at is None or plan.terminal_reason is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "terminal evidence is incomplete"
            )
        triggers = {item.trigger for item in record.directives}
        filled_directives = {item.directive_id for item in record.executions if item.fill_id}
        executable_directives = {
            item.directive_id
            for item in record.directives
            if item.directive_type is not DirectiveType.HOLD
        }
        outcome = TradePlanOutcome(
            stable_plan_id("outcome", plan.plan_id.value),
            plan.plan_id,
            plan.portfolio_id,
            plan.instrument,
            plan.horizon,
            plan.style,
            plan.activated_at,
            plan.terminal_at,
            plan.terminal_reason,
            values.average_entry_price,
            values.remaining_quantity,
            values.realized_pnl,
            int((plan.terminal_at - plan.activated_at).total_seconds()),
            bool(
                triggers & {TriggerType.HARD_STOP, TriggerType.TRAILING_STOP, TriggerType.TIME_STOP}
            ),
            TriggerType.PROFIT_TARGET in triggers,
            plan.status is TradePlanStatus.EXPIRED,
            plan.status is TradePlanStatus.INVALIDATED,
            sum(item.directive_type is DirectiveType.SCALE_IN for item in record.directives),
            sum(item.directive_type is DirectiveType.REDUCE for item in record.directives),
            sum(bool(item.rejected_reason_codes) for item in record.executions),
            executable_directives <= filled_directives,
            len(record.revisions),
            tuple(item.evidence_id for item in record.executions),
        )
        await self._repository.save(replace(record, outcome=outcome))
        return outcome

    async def _new_directive(
        self,
        record: TradePlanRecord,
        directive_type: DirectiveType,
        quantity: Quantity | None,
        trigger: TriggerType,
        as_of: datetime,
        observation_id: str,
        *,
        plan_version: int | None = None,
    ) -> TradePlanDirective:
        as_of = _trade_time(as_of, "as_of")
        version = record.plan.version if plan_version is None else plan_version
        not_before = None
        if directive_type is not DirectiveType.HOLD:
            not_before = await self._calendar.next_open(record.plan.instrument, as_of)
        identity = stable_plan_id(
            "directive",
            record.plan.plan_id.value,
            version,
            directive_type.value,
            trigger.value,
            as_of.isoformat(),
            observation_id,
        )
        directive = TradePlanDirective(
            identity,
            record.plan.plan_id,
            version,
            directive_type,
            quantity,
            trigger,
            as_of,
            not_before,
            observation_id,
            as_of,
        )
        existing = next((item for item in record.directives if item.directive_id == identity), None)
        if existing is not None:
            if existing != directive:
                raise TradePlanError(
                    TradePlanErrorCode.DIRECTIVE_CONFLICT,
                    "directive id identifies different evidence",
                )
            return existing
        await self._repository.save(replace(record, directives=record.directives + (directive,)))
        return directive

    async def _required(self, plan_id: TradePlanId) -> TradePlanRecord:
        value = await self._repository.get(plan_id)
        if value is None:
            raise TradePlanError(TradePlanErrorCode.PLAN_NOT_FOUND, "plan not found")
        return value

    async def _find_directive(
        self, directive_id: str
    ) -> tuple[TradePlanRecord, TradePlanDirective]:
        # Repository intentionally exposes bounded plan history rather than a global scan.
        value = await self._repository.get_by_directive(directive_id)
        if value is None:
            raise TradePlanError(TradePlanErrorCode.PLAN_NOT_FOUND, "directive not found")
        record, directive = value
        if not isinstance(directive, TradePlanDirective):
            raise TradePlanError(TradePlanErrorCode.PLAN_NOT_FOUND, "directive not found")
        return record, directive

    @staticmethod
    def _revision(
        plan: TradePlan,
        at: datetime,
        reason: str,
        actor: str,
        source: str,
        high_water: Decimal | None = None,
    ) -> TradePlanRevision:
        return TradePlanRevision(
            plan.plan_id,
            plan.version,
            at,
            at,
            reason,
            actor,
            source,
            plan.thesis,
            plan.target_quantity,
            plan.expiry_at,
            plan.policy_version,
            plan.horizon,
            plan.style,
            plan.hard_stop,
            plan.profit_targets,
            plan.trailing_stop,
            plan.time_stop,
            plan.thesis_invalidation_reference,
            high_water,
        )
