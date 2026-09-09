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
from aic_backend.domain.execution import PriceLimitBand
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
        if (
            command.plan_id != plan_id
            or command.portfolio_id != record.plan.portfolio_id
            or command.instrument != record.plan.instrument
        ):
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
        revision = self._revision(
            plan,
            at,
            change.reason,
            change.actor,
            change.source,
            record.revisions[-1].trailing_high_water,
        )
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
        revision = self._visible_revision(record, as_of)
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
        elif trailing_stop is not None and high_water is None:
            high_water = observation.high
        directive_type = DirectiveType.HOLD
        trigger = TriggerType.NO_TRIGGER
        quantity: Quantity | None = None
        terminal: TradePlanStatus | None = None
        trigger_policy: object = None
        if revision.expiry_at is not None and as_of >= revision.expiry_at:
            directive_type, trigger, terminal = (
                DirectiveType.EXIT,
                TriggerType.EXPIRY,
                TradePlanStatus.EXPIRED,
            )
            trigger_policy = revision.expiry_at
        elif revision.time_stop is not None and as_of >= revision.time_stop.deadline:
            directive_type = revision.time_stop.action
            quantity = revision.time_stop.quantity
            trigger = TriggerType.TIME_STOP
            trigger_policy = revision.time_stop
        elif revision.hard_stop is not None and observation.close <= revision.hard_stop.price:
            directive_type = revision.hard_stop.action
            quantity = revision.hard_stop.quantity
            trigger = TriggerType.HARD_STOP
            trigger_policy = revision.hard_stop
        elif (
            trailing_stop is not None
            and high_water is not None
            and observation.close <= high_water * (Decimal("1") - trailing_stop.distance_pct)
        ):
            directive_type = trailing_stop.action
            quantity = trailing_stop.quantity
            trigger = TriggerType.TRAILING_STOP
            trigger_policy = trailing_stop
        else:
            target = None
            resolved = {
                item.directive_id for item in record.executions if item.executed_at <= as_of
            }
            for candidate in revision.profit_targets:
                if observation.close < candidate.price:
                    continue
                prior = self._trigger_directive(record, TriggerType.PROFIT_TARGET, candidate, as_of)
                if prior is None or prior.directive_id not in resolved:
                    target = candidate
                    break
            if target is not None:
                directive_type, quantity, trigger = (
                    target.action,
                    target.quantity,
                    TriggerType.PROFIT_TARGET,
                )
                trigger_policy = target
        trigger_key = None
        if trigger_policy is not None:
            prior = self._trigger_directive(record, trigger, trigger_policy, as_of)
            if prior is not None:
                return prior
            trigger_key = self._trigger_key(trigger, trigger_policy)
        # Validate the terminal transition before saving any revision or directive.
        terminal_plan = (
            plan.transition(terminal, as_of, trigger.value) if terminal is not None else plan
        )
        directive = await self._prepare_directive(
            record,
            directive_type,
            quantity,
            trigger,
            as_of,
            observation.observation_id,
            plan_version=revision.version,
            trigger_key=trigger_key,
        )
        await self._repository.save(
            replace(self._append_directive(record, directive), plan=terminal_plan)
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
        as_of = _trade_time(as_of, "as_of")
        revision = self._visible_revision(record, as_of)
        if revision.thesis_invalidation_reference is None:
            raise TradePlanError(
                TradePlanErrorCode.INVALID_FIELD, "no structured invalidation policy"
            )
        terminal_plan = plan.transition(
            TradePlanStatus.INVALIDATED, as_of, f"THESIS_INVALIDATED:{event_reference}"
        )
        directive = await self._prepare_directive(
            record,
            DirectiveType.EXIT,
            None,
            TriggerType.THESIS_INVALIDATION,
            as_of,
            event_reference,
            plan_version=revision.version,
        )
        await self._repository.save(
            replace(self._append_directive(record, directive), plan=terminal_plan)
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
        directive = await self._prepare_directive(
            record,
            directive_type,
            quantity,
            TriggerType.MANUAL,
            as_of,
            source_reference,
        )
        await self._repository.save(self._append_directive(record, directive))
        return directive

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
        if state.account.portfolio_id != record.plan.portfolio_id:
            raise TradePlanError(
                TradePlanErrorCode.POSITION_SEMANTICS, "execution account does not own the plan"
            )
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
        position = state.account.positions.get(record.plan.instrument.canonical_key)
        held = Decimal("0") if position is None else position.quantity
        kind = directive.directive_type
        if (
            (kind is DirectiveType.ENTRY and held != 0)
            or (
                kind in (DirectiveType.SCALE_IN, DirectiveType.REDUCE, DirectiveType.EXIT)
                and held <= 0
            )
            or (
                kind is DirectiveType.REDUCE
                and directive.quantity is not None
                and directive.quantity.value >= held
            )
            or (position_quantity is not None and position_quantity.value != held)
        ):
            raise TradePlanError(
                TradePlanErrorCode.POSITION_SEMANTICS,
                "directive conflicts with the authoritative remaining position",
            )
        quantity = Quantity(held) if kind is DirectiveType.EXIT else directive.quantity
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
            outcome.fill is not None
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
        resolved = {item.directive_id for item in record.executions}
        if any(
            item.directive_type is not DirectiveType.HOLD and item.directive_id not in resolved
            for item in record.directives
        ):
            raise TradePlanError(
                TradePlanErrorCode.OUTCOME_PENDING,
                "outcome requires every executable directive to have fill or rejection evidence",
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

    async def _prepare_directive(
        self,
        record: TradePlanRecord,
        directive_type: DirectiveType,
        quantity: Quantity | None,
        trigger: TriggerType,
        as_of: datetime,
        observation_id: str,
        *,
        plan_version: int | None = None,
        trigger_key: str | None = None,
    ) -> TradePlanDirective:
        as_of = _trade_time(as_of, "as_of")
        revision = self._visible_revision(record, as_of)
        version = revision.version
        if plan_version is not None and plan_version != version:
            raise TradePlanError(
                TradePlanErrorCode.FUTURE_EVIDENCE, "revision is not visible as_of"
            )
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
            trigger_key,
        )
        return directive

    @staticmethod
    def _append_directive(
        record: TradePlanRecord, directive: TradePlanDirective
    ) -> TradePlanRecord:
        identity = directive.directive_id
        existing = next((item for item in record.directives if item.directive_id == identity), None)
        if existing is not None:
            if existing != directive:
                raise TradePlanError(
                    TradePlanErrorCode.DIRECTIVE_CONFLICT,
                    "directive id identifies different evidence",
                )
            return record
        return replace(record, directives=record.directives + (directive,))

    @staticmethod
    def _visible_revision(record: TradePlanRecord, as_of: datetime) -> TradePlanRevision:
        as_of = _trade_time(as_of, "as_of")
        visible = [
            revision
            for revision in record.revisions
            if revision.effective_at <= as_of and revision.recorded_at <= as_of
        ]
        if not visible:
            raise TradePlanError(
                TradePlanErrorCode.FUTURE_EVIDENCE, "no Trade Plan revision is available as_of"
            )
        return visible[-1]

    @staticmethod
    def _trigger_key(trigger: TriggerType, policy: object) -> str:
        if isinstance(policy, datetime):
            return stable_plan_id("trigger", trigger.value, policy.isoformat())
        if isinstance(policy, (HardStopPolicy, ProfitTarget, TrailingStopPolicy, TimeStopPolicy)):
            value = (
                str(policy.price.normalize())
                if isinstance(policy, (HardStopPolicy, ProfitTarget))
                else str(policy.distance_pct.normalize())
                if isinstance(policy, TrailingStopPolicy)
                else policy.deadline.isoformat()
            )
            quantity = None if policy.quantity is None else str(policy.quantity.value.normalize())
            return stable_plan_id("trigger", trigger.value, value, policy.action.value, quantity)
        raise TradePlanError(TradePlanErrorCode.INVALID_FIELD, "unsupported trigger policy")

    @classmethod
    def _trigger_directive(
        cls, record: TradePlanRecord, trigger: TriggerType, policy: object, as_of: datetime
    ) -> TradePlanDirective | None:
        key = cls._trigger_key(trigger, policy)
        for directive in record.directives:
            if directive.trigger is not trigger:
                continue
            matches = directive.trigger_key == key
            if directive.trigger_key is None:
                # Backward-compatible consumption of pre-fix persisted directives.
                prior = record.revisions[directive.plan_version - 1]
                old_policy: object = {
                    TriggerType.HARD_STOP: prior.hard_stop,
                    TriggerType.TRAILING_STOP: prior.trailing_stop,
                    TriggerType.TIME_STOP: prior.time_stop,
                    TriggerType.EXPIRY: prior.expiry_at,
                }.get(trigger)
                if trigger is TriggerType.PROFIT_TARGET:
                    matches = policy in prior.profit_targets and (
                        directive.directive_type == getattr(policy, "action")
                        and directive.quantity == getattr(policy, "quantity")
                    )
                else:
                    matches = old_policy == policy
            if matches:
                if directive.decision_as_of > as_of or directive.created_at > as_of:
                    raise TradePlanError(
                        TradePlanErrorCode.FUTURE_EVIDENCE,
                        "trigger already has later evidence; historical write is unavailable",
                    )
                return directive
        return None

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
