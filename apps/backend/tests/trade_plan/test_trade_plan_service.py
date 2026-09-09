from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from aic_backend.application.execution import ExecutionState
from aic_backend.application.trade_plan import (
    CreateDraftPlan,
    OutcomeInputs,
    PlanAmendment,
    PointInTimeNextOpenCalendar,
    TradePlanService,
)
from aic_backend.domain.execution import (
    ExecutionOutcome,
    ExecutionPolicyVersions,
    RiskDecision,
    RiskDecisionType,
    RiskInputSummary,
    RiskReasonCode,
    TradingEligibility,
)
from aic_backend.domain.market_data import (
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
    TradingSessionDay,
    standard_a_share_session,
)
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
    Position,
    PositionKey,
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
    parse_investment_horizon,
    parse_trading_style,
)
from aic_backend.infrastructure.trade_plan_persistence import (
    InMemoryTradePlanRepository,
    _record_json,
    _stored_record,
)

NOW = datetime(2026, 9, 9, 8, tzinfo=UTC)
NEXT_OPEN = datetime(2026, 9, 10, 1, 30, tzinfo=UTC)
EQUITY = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)
DOMESTIC_ETF = InstrumentIdentity(Market.CN_SSE, "510300", InstrumentType.ETF)
NASDAQ_QDII_ETF = InstrumentIdentity(Market.CN_SZSE, "159941", InstrumentType.ETF)


class Calendar:
    async def next_open(self, instrument: InstrumentIdentity, decision_at: datetime) -> datetime:
        assert instrument.canonical_key
        assert decision_at < NEXT_OPEN
        return NEXT_OPEN


class Execution:
    async def reconcile(self, state: ExecutionState, order_id: OrderId, as_of: datetime):
        return None

    def __init__(self, rejected: bool = False) -> None:
        self.rejected = rejected
        self.calls = 0
        self.sides: list[OrderSide] = []

    async def execute(
        self,
        state: ExecutionState,
        intent: object,
        order_id: OrderId,
        as_of: datetime,
        price_limit_band: object,
    ) -> ExecutionOutcome:
        from aic_backend.application.execution import ExecutionOrderIntent

        assert isinstance(intent, ExecutionOrderIntent)
        self.calls += 1
        self.sides.append(intent.side)
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
        summary = RiskInputSummary(
            Money(Decimal("100000")),
            Money(Decimal("100000")),
            Money(Decimal("0")),
            Money(Decimal("1000")),
            Money(Decimal("1000")),
            Money(Decimal("99000")),
            0,
            0,
            Money(Decimal("0")),
        )
        reasons = (RiskReasonCode.INSUFFICIENT_CASH,) if self.rejected else ()
        decision = RiskDecision(
            f"risk-{order_id.value}",
            state.account.portfolio_id,
            order_id,
            as_of,
            RiskDecisionType.REJECT if self.rejected else RiskDecisionType.ALLOW,
            reasons,
            "risk/v1",
            summary,
        )
        fill = None
        if self.rejected:
            order = order.transition(OrderStatus.REJECTED)
        else:
            order = order.transition(OrderStatus.ACCEPTED).transition(OrderStatus.FILLED)
            fill = Fill(
                FillId(f"fill-{order_id.value}"),
                order_id,
                state.account.portfolio_id,
                intent.instrument,
                intent.side,
                intent.quantity,
                Price(Decimal("10")),
                as_of,
                Money(Decimal("0")),
                Money(Decimal("0")),
                Money(Decimal("0")),
                "execution/v1",
            )
            state.account.apply_fill(fill, (f"cash-{order_id.value}",))
        return ExecutionOutcome(
            order,
            TradingEligibility(True, True, False, False, True),
            decision,
            fill,
            (),
            None,
            None,
            None,
            ExecutionPolicyVersions("execution/v1", "lot/v1", "limit/v1", "t1/v1", "risk/v1"),
            (),
            {},
        )


def command(
    plan_id: str = "plan-1",
    *,
    portfolio: str = "champion",
    instrument: InstrumentIdentity = EQUITY,
    hard_stop: HardStopPolicy | None = None,
    profit_targets: tuple[ProfitTarget, ...] = (),
    trailing_stop: TrailingStopPolicy | None = None,
    time_stop: TimeStopPolicy | None = None,
    expiry_at: datetime | None = None,
    invalidation: str | None = None,
) -> CreateDraftPlan:
    return CreateDraftPlan(
        TradePlanId(plan_id),
        PortfolioId(portfolio),
        instrument,
        InvestmentHorizon.SHORT,
        TradingStyle.SWING,
        "Deterministic fixture thesis; never parsed as a signal.",
        Quantity(Decimal("100")),
        NOW,
        expiry_at,
        invalidation,
        hard_stop,
        profit_targets,
        trailing_stop,
        time_stop,
    )


async def active_service(
    value: CreateDraftPlan | None = None, *, rejected: bool = False
) -> tuple[TradePlanService, InMemoryTradePlanRepository, Execution]:
    repository = InMemoryTradePlanRepository()
    execution = Execution(rejected)
    service = TradePlanService(repository, Calendar(), execution)
    item = value or command()
    await service.create_draft(item)
    await service.activate(item.plan_id, NOW + timedelta(minutes=1), actor="cto", source="issue-18")
    return service, repository, execution


def observation(
    identity: str,
    close: str,
    *,
    high: str | None = None,
    available_at: datetime = NOW + timedelta(hours=1),
) -> PlanObservation:
    close_value = Decimal(close)
    high_value = Decimal(high or close)
    return PlanObservation(
        identity,
        NOW + timedelta(minutes=30),
        available_at,
        close_value,
        max(close_value, high_value),
        min(close_value, high_value),
        close_value,
    )


def test_taxonomies_are_exact_and_unknown_values_fail_closed() -> None:
    assert [item.value for item in InvestmentHorizon] == [
        "T",
        "SHORT",
        "MEDIUM_SHORT",
        "MEDIUM",
        "MEDIUM_LONG",
        "LONG",
    ]
    assert [item.value for item in TradingStyle] == [
        "SWING",
        "TREND",
        "VALUE",
        "EVENT",
        "INDEX",
        "MEAN_REVERSION",
        "OTHER",
    ]
    with pytest.raises(ValueError):
        InvestmentHorizon("WEEKISH")
    with pytest.raises(ValueError):
        TradingStyle("MOMENTUM")
    for parser, value in (
        (parse_investment_horizon, "WEEKISH"),
        (parse_trading_style, "MOMENTUM"),
    ):
        with pytest.raises(TradePlanError) as error:
            parser(value)
        assert error.value.code is TradePlanErrorCode.INVALID_FIELD


@pytest.mark.asyncio
async def test_existing_pit_calendar_resolves_only_next_eligible_open() -> None:
    class PIT:
        empty = False

        async def list_calendar_as_of(self, *args: object) -> object:
            if self.empty:
                return SimpleNamespace(records=())
            day = NEXT_OPEN.date()
            return SimpleNamespace(
                records=(
                    TradingSessionDay(
                        Market.CN_SSE,
                        day,
                        True,
                        standard_a_share_session(day),
                        NOW,
                        DataProvenance(
                            "fixture",
                            None,
                            None,
                            NOW,
                            False,
                            0,
                            "0" * 64,
                            "fixture/v1",
                        ),
                    ),
                )
            )

    pit = PIT()
    calendar = PointInTimeNextOpenCalendar(pit, search_days=3)  # type: ignore[arg-type]
    assert await calendar.next_open(EQUITY, NOW) == NEXT_OPEN
    pit.empty = True
    with pytest.raises(TradePlanError) as error:
        await calendar.next_open(EQUITY, NOW)
    assert error.value.code is TradePlanErrorCode.FUTURE_EVIDENCE
    with pytest.raises(ValueError, match="search_days"):
        PointInTimeNextOpenCalendar(pit, search_days=0)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_activation_version_one_uniqueness_and_portfolio_isolation() -> None:
    service, repository, _ = await active_service()
    first = await repository.get(TradePlanId("plan-1"))
    assert first is not None
    assert first.plan.status is TradePlanStatus.ACTIVE
    assert first.plan.version == 1
    assert len(first.revisions) == 1
    assert first.revisions[0].reason == "ACTIVATED"

    await service.create_draft(command("duplicate"))
    with pytest.raises(TradePlanError) as error:
        await service.activate(
            TradePlanId("duplicate"), NOW + timedelta(minutes=2), actor="cto", source="test"
        )
    assert error.value.code is TradePlanErrorCode.DUPLICATE_ACTIVE_PLAN

    shadow = command("shadow-plan", portfolio="shadow-atlas")
    await service.create_draft(shadow)
    await service.activate(shadow.plan_id, NOW + timedelta(minutes=2), actor="cto", source="test")
    assert (await service.active_plan(PortfolioId("champion"), EQUITY)).plan_id == TradePlanId(
        "plan-1"
    )
    assert (await service.active_plan(PortfolioId("shadow-atlas"), EQUITY)).plan_id == TradePlanId(
        "shadow-plan"
    )


@pytest.mark.asyncio
async def test_draft_can_change_taxonomy_but_activation_freezes_it() -> None:
    repository = InMemoryTradePlanRepository()
    service = TradePlanService(repository, Calendar(), Execution())
    original = command("editable")
    await service.create_draft(original)
    edited = replace(
        original,
        horizon=InvestmentHorizon.MEDIUM,
        style=TradingStyle.VALUE,
        thesis="Edited before activation",
        created_at=NOW + timedelta(seconds=1),
    )
    draft = await service.edit_draft(original.plan_id, edited)
    assert (draft.horizon, draft.style, draft.thesis) == (
        InvestmentHorizon.MEDIUM,
        TradingStyle.VALUE,
        "Edited before activation",
    )
    await service.activate(original.plan_id, NOW + timedelta(minutes=1), actor="cto", source="test")
    with pytest.raises(TradePlanError) as error:
        await service.edit_draft(original.plan_id, original)
    assert error.value.code is TradePlanErrorCode.PROTECTED_FIELD_MUTATION


@pytest.mark.asyncio
async def test_recovery_projection_round_trip_preserves_immutable_types() -> None:
    _, repository, _ = await active_service()
    record = await repository.get(TradePlanId("plan-1"))
    assert record is not None
    assert _stored_record(_record_json(record)) == record


@pytest.mark.asyncio
async def test_append_only_revision_stale_version_and_anti_loss_relabel() -> None:
    service, repository, _ = await active_service()
    changed = await service.revise(
        TradePlanId("plan-1"),
        PlanAmendment(
            1,
            "tighten risk",
            "cto",
            "review",
            NOW + timedelta(minutes=2),
            hard_stop=HardStopPolicy(Decimal("8")),
        ),
    )
    assert changed.version == 2
    record = await repository.get(changed.plan_id)
    assert record is not None
    assert [item.version for item in record.revisions] == [1, 2]
    assert record.revisions[0].hard_stop is None
    assert record.revisions[1].hard_stop == HardStopPolicy(Decimal("8"))
    assert record.revisions[0].thesis == changed.thesis
    assert record.revisions[0].target_quantity == Quantity(Decimal("100"))
    assert record.revisions[0].policy_version == "trade-plan/v1"

    historical = await service.evaluate(
        changed.plan_id,
        replace(
            observation("before-revision", "7"),
            event_at=NOW + timedelta(seconds=30),
            available_at=NOW + timedelta(seconds=45),
        ),
        NOW + timedelta(minutes=1),
    )
    assert historical.directive_type is DirectiveType.HOLD
    assert historical.plan_version == 1

    for amendment in (
        PlanAmendment(
            2,
            "hide loss",
            "cto",
            "test",
            NOW + timedelta(minutes=3),
            horizon=InvestmentHorizon.LONG,
        ),
        PlanAmendment(
            2,
            "rename style",
            "cto",
            "test",
            NOW + timedelta(minutes=3),
            style=TradingStyle.VALUE,
        ),
    ):
        with pytest.raises(TradePlanError) as error:
            await service.revise(changed.plan_id, amendment)
        assert error.value.code is TradePlanErrorCode.PROTECTED_FIELD_MUTATION
    with pytest.raises(TradePlanError) as error:
        await service.revise(
            changed.plan_id,
            PlanAmendment(1, "stale", "cto", "test", NOW + timedelta(minutes=3)),
        )
    assert error.value.code is TradePlanErrorCode.STALE_VERSION

    await service.transition_terminal(
        changed.plan_id,
        TradePlanStatus.CANCELLED,
        NOW + timedelta(minutes=4),
        "ABANDONED",
    )
    with pytest.raises(TradePlanError) as error:
        await service.revise(
            changed.plan_id,
            PlanAmendment(2, "late", "cto", "test", NOW + timedelta(minutes=5)),
        )
    assert error.value.code is TradePlanErrorCode.TERMINAL_IMMUTABLE
    successor = replace(command("successor"), horizon=InvestmentHorizon.LONG)
    await service.create_draft(successor)
    await service.activate(
        successor.plan_id,
        NOW + timedelta(minutes=5),
        actor="cto",
        source="successor",
    )
    history = await service.history(PortfolioId("champion"), EQUITY)
    assert [item.plan.plan_id.value for item in history] == ["plan-1", "successor"]
    assert history[0].plan.horizon is InvestmentHorizon.SHORT
    assert history[1].plan.horizon is InvestmentHorizon.LONG


@pytest.mark.asyncio
async def test_all_manual_directives_and_hold_never_execute() -> None:
    service, _, execution = await active_service()
    created: list[TradePlanDirective] = []
    for kind, quantity in (
        (DirectiveType.ENTRY, Quantity(Decimal("100"))),
        (DirectiveType.SCALE_IN, Quantity(Decimal("100"))),
        (DirectiveType.HOLD, None),
        (DirectiveType.REDUCE, Quantity(Decimal("100"))),
        (DirectiveType.EXIT, None),
    ):
        created.append(
            await service.create_directive(
                TradePlanId("plan-1"),
                kind,
                quantity,
                NOW + timedelta(minutes=2 + len(created)),
                source_reference=f"manual-{kind.value}",
            )
        )
    assert [item.directive_type for item in created] == list(DirectiveType)
    assert created[2].not_before is None
    with pytest.raises(TradePlanError) as error:
        await service.execute_directive(
            created[2].directive_id,
            ExecutionState.initialize(PortfolioId("champion"), Money(Decimal("100000")), NOW),
            NEXT_OPEN,
        )
    assert error.value.code is TradePlanErrorCode.DIRECTIVE_NOT_EXECUTABLE
    assert execution.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "side"),
    (
        (DirectiveType.ENTRY, OrderSide.BUY),
        (DirectiveType.SCALE_IN, OrderSide.BUY),
        (DirectiveType.REDUCE, OrderSide.SELL),
    ),
)
async def test_executable_directives_use_the_authoritative_gateway(
    kind: DirectiveType, side: OrderSide
) -> None:
    service, _, execution = await active_service()
    directive = await service.create_directive(
        TradePlanId("plan-1"),
        kind,
        Quantity(Decimal("100")),
        NOW + timedelta(hours=1),
        source_reference=kind.value,
    )
    state = ExecutionState.initialize(PortfolioId("champion"), Money(Decimal("100000")), NOW)
    if kind is not DirectiveType.ENTRY:
        state.account.positions[EQUITY.canonical_key] = Position(
            PositionKey(state.account.portfolio_id, EQUITY), Decimal("200"), Decimal("10")
        )
    evidence = await service.execute_directive(directive.directive_id, state, NEXT_OPEN)
    assert evidence.fill_id is not None
    assert execution.sides == [side]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan_command", "market_observation", "trigger", "directive"),
    (
        (
            command("hard", hard_stop=HardStopPolicy(Decimal("9"))),
            observation("hard-bar", "8"),
            TriggerType.HARD_STOP,
            DirectiveType.EXIT,
        ),
        (
            command(
                "hard-reduce",
                hard_stop=HardStopPolicy(
                    Decimal("9"), DirectiveType.REDUCE, Quantity(Decimal("100"))
                ),
            ),
            observation("hard-reduce-bar", "8"),
            TriggerType.HARD_STOP,
            DirectiveType.REDUCE,
        ),
        (
            command(
                "target",
                profit_targets=(
                    ProfitTarget(Decimal("12"), DirectiveType.REDUCE, Quantity(Decimal("100"))),
                ),
            ),
            observation("target-bar", "13"),
            TriggerType.PROFIT_TARGET,
            DirectiveType.REDUCE,
        ),
        (
            command("time", time_stop=TimeStopPolicy(NOW + timedelta(minutes=20))),
            observation("time-bar", "10"),
            TriggerType.TIME_STOP,
            DirectiveType.EXIT,
        ),
    ),
)
async def test_deterministic_stop_and_target_evaluation(
    plan_command: CreateDraftPlan,
    market_observation: PlanObservation,
    trigger: TriggerType,
    directive: DirectiveType,
) -> None:
    service, _, _ = await active_service(plan_command)
    result = await service.evaluate(
        plan_command.plan_id, market_observation, NOW + timedelta(hours=1)
    )
    assert (result.trigger, result.directive_type, result.not_before) == (
        trigger,
        directive,
        NEXT_OPEN,
    )


@pytest.mark.asyncio
async def test_trailing_high_water_is_audited_and_point_in_time() -> None:
    item = command("trailing", trailing_stop=TrailingStopPolicy(Decimal("0.10")))
    service, repository, _ = await active_service(item)
    hold = await service.evaluate(
        item.plan_id, observation("peak", "120", high="120"), NOW + timedelta(hours=1)
    )
    assert hold.directive_type is DirectiveType.HOLD
    record = await repository.get(item.plan_id)
    assert record is not None
    assert record.plan.version == 2
    assert record.revisions[-1].trailing_high_water == Decimal("120")
    stop = await service.evaluate(
        item.plan_id,
        observation("drawdown", "107", high="110"),
        NOW + timedelta(hours=2),
    )
    assert stop.trigger is TriggerType.TRAILING_STOP

    future = observation("future", "100", available_at=NOW + timedelta(days=1))
    with pytest.raises(TradePlanError) as error:
        await service.evaluate(item.plan_id, future, NOW + timedelta(hours=3))
    assert error.value.code is TradePlanErrorCode.FUTURE_EVIDENCE


@pytest.mark.asyncio
async def test_expiry_and_thesis_invalidation_are_terminal_and_audited() -> None:
    expiring = command("expiry", expiry_at=NOW + timedelta(minutes=30))
    service, repository, _ = await active_service(expiring)
    directive = await service.evaluate(
        expiring.plan_id, observation("expiry-bar", "10"), NOW + timedelta(hours=1)
    )
    assert directive.trigger is TriggerType.EXPIRY
    assert (await repository.get(expiring.plan_id)).plan.status is TradePlanStatus.EXPIRED

    invalidated = command("invalidated", invalidation="earnings-event/v1")
    service, repository, _ = await active_service(invalidated)
    directive = await service.record_thesis_invalidation(
        invalidated.plan_id,
        event_reference="event-42",
        as_of=NOW + timedelta(hours=1),
    )
    assert directive.trigger is TriggerType.THESIS_INVALIDATION
    assert (await repository.get(invalidated.plan_id)).plan.status is TradePlanStatus.INVALIDATED


@pytest.mark.asyncio
async def test_next_open_lock_execution_link_rejection_and_outcome() -> None:
    service, repository, execution = await active_service(rejected=True)
    directive = await service.create_directive(
        TradePlanId("plan-1"),
        DirectiveType.ENTRY,
        Quantity(Decimal("100")),
        NOW + timedelta(hours=1),
        source_reference="entry",
    )
    state = ExecutionState.initialize(PortfolioId("champion"), Money(Decimal("100000")), NOW)
    with pytest.raises(TradePlanError) as error:
        await service.execute_directive(
            directive.directive_id, state, NEXT_OPEN - timedelta(seconds=1)
        )
    assert error.value.code is TradePlanErrorCode.EXECUTION_TOO_EARLY
    evidence = await service.execute_directive(directive.directive_id, state, NEXT_OPEN)
    assert evidence.fill_id is None
    assert evidence.rejected_reason_codes == (RiskReasonCode.INSUFFICIENT_CASH.value,)
    assert execution.calls == 1
    assert (await repository.get(TradePlanId("plan-1"))).plan.status is TradePlanStatus.ACTIVE

    await service.transition_terminal(
        TradePlanId("plan-1"),
        TradePlanStatus.CANCELLED,
        NEXT_OPEN + timedelta(hours=1),
        "RISK_REJECTED",
    )
    outcome = await service.build_outcome(
        TradePlanId("plan-1"),
        OutcomeInputs(None, Decimal("0"), Decimal("0")),
    )
    assert outcome.rejected_count == 1
    assert not outcome.adhered
    assert outcome.source_execution_ids == (evidence.evidence_id,)


@pytest.mark.asyncio
async def test_idempotency_conflicts_missing_records_and_terminal_guards() -> None:
    repository = InMemoryTradePlanRepository()
    service = TradePlanService(repository, Calendar(), Execution())
    item = command("guards")
    assert await service.create_draft(item) == await service.create_draft(item)
    with pytest.raises(TradePlanError) as error:
        await service.create_draft(replace(item, thesis="different evidence"))
    assert error.value.code is TradePlanErrorCode.DIRECTIVE_CONFLICT
    assert await service.active_plan(item.portfolio_id, item.instrument) is None
    assert await service.history(item.portfolio_id, item.instrument)
    with pytest.raises(TradePlanError) as error:
        await service.activate(TradePlanId("missing"), NOW, actor="cto", source="test")
    assert error.value.code is TradePlanErrorCode.PLAN_NOT_FOUND
    active = await service.activate(item.plan_id, NOW, actor="cto", source="test")
    assert await service.activate(item.plan_id, NOW, actor="cto", source="test") == active
    with pytest.raises(TradePlanError) as error:
        await service.revise(
            item.plan_id,
            PlanAmendment(
                1,
                "stale time",
                "cto",
                "test",
                NOW - timedelta(seconds=1),
            ),
        )
    assert error.value.code is TradePlanErrorCode.STALE_VERSION
    with pytest.raises(TradePlanError) as error:
        await service.record_thesis_invalidation(
            item.plan_id, event_reference="event", as_of=NOW + timedelta(minutes=1)
        )
    assert error.value.code is TradePlanErrorCode.INVALID_FIELD
    with pytest.raises(TradePlanError) as error:
        await service.build_outcome(item.plan_id, OutcomeInputs(None, Decimal("0"), Decimal("0")))
    assert error.value.code is TradePlanErrorCode.INVALID_TRANSITION
    await service.transition_terminal(
        item.plan_id,
        TradePlanStatus.CANCELLED,
        NOW + timedelta(minutes=2),
        "cancelled",
    )
    with pytest.raises(TradePlanError):
        await service.evaluate(
            item.plan_id,
            observation("terminal", "10"),
            NOW + timedelta(hours=1),
        )
    with pytest.raises(TradePlanError):
        await service.create_directive(
            item.plan_id,
            DirectiveType.HOLD,  # type: ignore[attr-defined]
            None,
            NOW + timedelta(minutes=3),
            source_reference="terminal",
        )
    with pytest.raises(TradePlanError):
        await service.record_thesis_invalidation(
            item.plan_id,
            event_reference="terminal",
            as_of=NOW + timedelta(minutes=3),
        )


@pytest.mark.asyncio
async def test_successful_exit_is_linked_completes_once_and_builds_adherence() -> None:
    service, repository, execution = await active_service()
    directive = await service.create_directive(
        TradePlanId("plan-1"),
        DirectiveType.EXIT,
        None,
        NOW + timedelta(hours=1),
        source_reference="full-exit",
    )
    state = ExecutionState.initialize(PortfolioId("champion"), Money(Decimal("100000")), NOW)
    with pytest.raises(TradePlanError) as error:
        await service.execute_directive(directive.directive_id, state, NEXT_OPEN)
    assert error.value.code is TradePlanErrorCode.POSITION_SEMANTICS
    state.account.positions[EQUITY.canonical_key] = Position(
        PositionKey(state.account.portfolio_id, EQUITY), Decimal("100"), Decimal("10")
    )
    evidence = await service.execute_directive(
        directive.directive_id,
        state,
        NEXT_OPEN,
        position_quantity=Quantity(Decimal("100")),
        requested_price=Price(Decimal("10")),
    )
    assert evidence.fill_id is not None
    assert (
        await service.execute_directive(
            directive.directive_id,
            state,
            NEXT_OPEN,
            position_quantity=Quantity(Decimal("100")),
        )
        == evidence
    )
    assert execution.calls == 1
    record = await repository.get(TradePlanId("plan-1"))
    assert record is not None and record.plan.status is TradePlanStatus.COMPLETED
    outcome = await service.build_outcome(
        record.plan.plan_id,
        OutcomeInputs(Decimal("9"), Decimal("0"), Decimal("100")),
    )
    assert outcome.adhered
    assert outcome.average_entry_price == Decimal("9")
    assert outcome.revision_count == 1
    assert (
        await service.build_outcome(
            record.plan.plan_id,
            OutcomeInputs(Decimal("99"), Decimal("99"), Decimal("99")),
        )
        == outcome
    )
    with pytest.raises(TradePlanError) as error:
        await service.execute_directive("missing-directive", state, NEXT_OPEN)
    assert error.value.code is TradePlanErrorCode.PLAN_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize("instrument", (EQUITY, DOMESTIC_ETF, NASDAQ_QDII_ETF))
async def test_equity_domestic_and_nasdaq_qdii_etf_share_owned_boundaries(
    instrument: InstrumentIdentity,
) -> None:
    item = command(f"asset-{instrument.symbol}", instrument=instrument)
    service, _, _ = await active_service(item)
    active = await service.active_plan(PortfolioId("champion"), instrument)
    assert active is not None
    assert active.instrument == instrument


def test_reference_index_and_direct_us_instrument_fail_closed() -> None:
    from aic_backend.domain.trade_plan import TradePlan

    index = InstrumentIdentity(Market.INDEX_REFERENCE, "000001", InstrumentType.INDEX)
    value = command("unsupported", instrument=index)
    with pytest.raises(TradePlanError) as error:
        TradePlan(
            value.plan_id,
            value.portfolio_id,
            value.instrument,
            value.horizon,
            value.style,
            value.thesis,
            value.target_quantity,
            value.created_at,
            value.created_at,
        )
    assert error.value.code is TradePlanErrorCode.NON_TRADABLE_INDEX
    with pytest.raises(ValueError):
        Market("US.NASDAQ")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(DirectiveType))
async def test_manual_directives_bind_only_to_visible_revision(kind: DirectiveType) -> None:
    service, repository, _ = await active_service()
    plan_id = TradePlanId("plan-1")
    await service.revise(
        plan_id,
        PlanAmendment(
            1,
            "future policy",
            "cto",
            "review",
            NOW + timedelta(hours=2),
            hard_stop=HardStopPolicy(Decimal("8")),
        ),
    )
    quantity = (
        None if kind in (DirectiveType.HOLD, DirectiveType.EXIT) else Quantity(Decimal("100"))
    )
    directive = await service.create_directive(
        plan_id, kind, quantity, NOW + timedelta(hours=1), source_reference="historical"
    )
    assert directive.plan_version == 1
    before = await repository.get(plan_id)
    with pytest.raises(TradePlanError) as error:
        await service.create_directive(
            plan_id, kind, quantity, NOW, source_reference="pre-activation"
        )
    assert error.value.code is TradePlanErrorCode.FUTURE_EVIDENCE
    assert await repository.get(plan_id) == before


@pytest.mark.asyncio
async def test_recorded_at_also_controls_revision_visibility() -> None:
    service, repository, _ = await active_service()
    record = await repository.get(TradePlanId("plan-1"))
    delayed = replace(record.revisions[0], recorded_at=NOW + timedelta(hours=2))
    # Model a previously stored revision with delayed availability in an independent repository.
    restored = InMemoryTradePlanRepository()
    await restored.save(replace(record, revisions=(delayed,)))
    service = TradePlanService(restored, Calendar(), Execution())
    with pytest.raises(TradePlanError) as error:
        await service.evaluate(
            record.plan.plan_id, observation("early", "10"), NOW + timedelta(hours=1)
        )
    assert error.value.code is TradePlanErrorCode.FUTURE_EVIDENCE
    assert (await restored.get(record.plan.plan_id)).directives == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_old_policy", [False, True])
async def test_stale_thesis_invalidation_cannot_leave_partial_evidence(
    has_old_policy: bool,
) -> None:
    service, repository, _ = await active_service(
        command(invalidation="old-policy" if has_old_policy else None)
    )
    plan_id = TradePlanId("plan-1")
    await service.revise(
        plan_id,
        PlanAmendment(
            1,
            "later invalidation policy",
            "cto",
            "review",
            NOW + timedelta(hours=2),
            thesis_invalidation_reference="future-policy",
        ),
    )
    before = await repository.get(plan_id)
    with pytest.raises(TradePlanError) as error:
        await service.record_thesis_invalidation(
            plan_id, event_reference="stale-event", as_of=NOW + timedelta(hours=1)
        )
    assert error.value.code is (
        TradePlanErrorCode.INVALID_TIMESTAMP if has_old_policy else TradePlanErrorCode.INVALID_FIELD
    )
    assert await repository.get(plan_id) == before


@pytest.mark.asyncio
async def test_calendar_failure_rolls_back_trailing_and_terminal_preparation() -> None:
    from unittest.mock import AsyncMock

    service, repository, _ = await active_service(
        command(
            expiry_at=NOW + timedelta(minutes=30), trailing_stop=TrailingStopPolicy(Decimal(".1"))
        )
    )
    before = await repository.get(TradePlanId("plan-1"))
    service._calendar = SimpleNamespace(
        next_open=AsyncMock(side_effect=RuntimeError("unavailable"))
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await service.evaluate(
            before.plan.plan_id, observation("expiry", "10"), NOW + timedelta(hours=1)
        )
    assert await repository.get(before.plan.plan_id) == before


def positioned_state(quantity: str, *, portfolio: str = "champion") -> ExecutionState:
    state = ExecutionState.initialize(PortfolioId(portfolio), Money(Decimal("100000")), NOW)
    if Decimal(quantity):
        state.account.positions[EQUITY.canonical_key] = Position(
            PositionKey(state.account.portfolio_id, EQUITY), Decimal(quantity), Decimal("10")
        )
    return state


class FollowingDayCalendar:
    async def next_open(self, instrument: InstrumentIdentity, decision_at: datetime) -> datetime:
        return decision_at.replace(hour=1, minute=30, second=0, microsecond=0) + timedelta(days=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,held,quantity,valid,remaining",
    [
        (DirectiveType.ENTRY, "0", "100", True, "100"),
        (DirectiveType.ENTRY, "100", "100", False, "100"),
        (DirectiveType.SCALE_IN, "0", "100", False, "0"),
        (DirectiveType.SCALE_IN, "100", "100", True, "200"),
        (DirectiveType.REDUCE, "0", "100", False, "0"),
        (DirectiveType.REDUCE, "100", "100", False, "100"),
        (DirectiveType.REDUCE, "100", "200", False, "100"),
        (DirectiveType.REDUCE, "200", "100", True, "100"),
        (DirectiveType.EXIT, "0", None, False, "0"),
        (DirectiveType.EXIT, "250", None, True, "0"),
    ],
)
async def test_position_semantics_against_authoritative_account(
    kind: DirectiveType, held: str, quantity: str | None, valid: bool, remaining: str
) -> None:
    service, repository, execution = await active_service()
    directive = await service.create_directive(
        TradePlanId("plan-1"),
        kind,
        None if quantity is None else Quantity(Decimal(quantity)),
        NOW + timedelta(hours=1),
        source_reference="position-semantics",
    )
    state = positioned_state(held)
    if valid:
        evidence = await service.execute_directive(directive.directive_id, state, NEXT_OPEN)
        assert evidence.fill_id is not None and execution.calls == 1
        assert await service.execute_directive(directive.directive_id, state, NEXT_OPEN) == evidence
        assert execution.calls == 1
    else:
        before = await repository.get(directive.plan_id)
        with pytest.raises(TradePlanError) as error:
            await service.execute_directive(directive.directive_id, state, NEXT_OPEN)
        assert error.value.code is TradePlanErrorCode.POSITION_SEMANTICS
        assert execution.calls == 0 and await repository.get(directive.plan_id) == before
    position = state.account.positions.get(EQUITY.canonical_key)
    assert (Decimal("0") if position is None else position.quantity) == Decimal(remaining)


@pytest.mark.asyncio
async def test_exit_cannot_use_caller_quantity_or_another_account() -> None:
    service, _, execution = await active_service()
    directive = await service.create_directive(
        TradePlanId("plan-1"),
        DirectiveType.EXIT,
        None,
        NOW + timedelta(hours=1),
        source_reference="exit",
    )
    for state, hint in (
        (positioned_state("200"), Quantity(Decimal("100"))),
        (positioned_state("200", portfolio="shadow"), None),
    ):
        with pytest.raises(TradePlanError) as error:
            await service.execute_directive(
                directive.directive_id, state, NEXT_OPEN, position_quantity=hint
            )
        assert error.value.code is TradePlanErrorCode.POSITION_SEMANTICS
    assert execution.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_kind", ["hard", "trailing", "time", "target"])
@pytest.mark.parametrize("rejected", [False, True])
async def test_automatic_trigger_is_not_reemitted_pending_or_consumed(
    policy_kind: str, rejected: bool
) -> None:
    reduce = DirectiveType.REDUCE
    quantity = Quantity(Decimal("100"))
    values = {
        "hard": command(hard_stop=HardStopPolicy(Decimal("9"), reduce, quantity)),
        "trailing": command(trailing_stop=TrailingStopPolicy(Decimal(".1"), reduce, quantity)),
        "time": command(time_stop=TimeStopPolicy(NOW + timedelta(minutes=30), reduce, quantity)),
        "target": command(profit_targets=(ProfitTarget(Decimal("12"), reduce, quantity),)),
    }
    service, repository, execution = await active_service(values[policy_kind], rejected=rejected)
    price = "13" if policy_kind == "target" else "8"
    first = await service.evaluate(
        TradePlanId("plan-1"), observation("one", price, high="10"), NOW + timedelta(hours=1)
    )
    # Restart must reconstruct pending/consumed state from persisted directives/evidence.
    restored = InMemoryTradePlanRepository()
    await restored.save(_stored_record(_record_json(await repository.get(first.plan_id))))
    service = TradePlanService(restored, Calendar(), execution)
    repeated = await service.evaluate(
        first.plan_id, observation("two", price, high="11"), NOW + timedelta(hours=2)
    )
    assert repeated.directive_id == first.directive_id
    state = positioned_state("500")
    await service.execute_directive(first.directive_id, state, NEXT_OPEN)
    # A later decision (new source/timestamp) cannot create another action for this policy.
    service._calendar = FollowingDayCalendar()
    after = await service.evaluate(
        first.plan_id, observation("three", price, high="12"), NEXT_OPEN + timedelta(hours=1)
    )
    record = await restored.get(first.plan_id)
    assert len([d for d in record.directives if d.directive_type is not DirectiveType.HOLD]) == 1
    assert after.directive_type is DirectiveType.HOLD or after.directive_id == first.directive_id
    assert execution.calls == 1


@pytest.mark.asyncio
async def test_targets_are_consumed_independently_and_equal_policy_revision_does_not_rearm() -> (
    None
):
    quantity = Quantity(Decimal("100"))
    service, repository, _ = await active_service(
        command(
            profit_targets=(
                ProfitTarget(Decimal("12"), DirectiveType.REDUCE, quantity),
                ProfitTarget(Decimal("14"), DirectiveType.REDUCE, quantity),
            )
        )
    )
    plan_id = TradePlanId("plan-1")
    state = positioned_state("500")
    first = await service.evaluate(
        plan_id, observation("target-one", "15"), NOW + timedelta(hours=1)
    )
    await service.execute_directive(first.directive_id, state, NEXT_OPEN)
    await service.revise(
        plan_id,
        PlanAmendment(
            1,
            "equivalent decimals",
            "cto",
            "review",
            NEXT_OPEN + timedelta(minutes=30),
            profit_targets=(
                ProfitTarget(Decimal("12.0"), DirectiveType.REDUCE, quantity),
                ProfitTarget(Decimal("14.0"), DirectiveType.REDUCE, quantity),
            ),
        ),
    )
    historical = await service.evaluate(
        plan_id, observation("before-fill", "15"), NOW + timedelta(hours=2)
    )
    assert historical == first
    service._calendar = FollowingDayCalendar()
    second = await service.evaluate(
        plan_id, observation("target-two", "15"), NEXT_OPEN + timedelta(hours=1)
    )
    assert second.trigger_key != first.trigger_key
    await service.execute_directive(second.directive_id, state, second.not_before)
    final = await service.evaluate(
        plan_id, observation("targets-used", "15"), second.not_before + timedelta(hours=1)
    )
    assert final.directive_type is DirectiveType.HOLD
    assert len((await repository.get(plan_id)).executions) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["expiry", "invalidation"])
@pytest.mark.parametrize("rejected", [False, True])
async def test_outcome_waits_for_terminal_exit_settlement(terminal: str, rejected: bool) -> None:
    value = (
        command(expiry_at=NOW + timedelta(minutes=30))
        if terminal == "expiry"
        else command(invalidation="explicit-policy")
    )
    service, repository, _ = await active_service(value, rejected=rejected)
    directive = (
        await service.evaluate(value.plan_id, observation("expiry", "10"), NOW + timedelta(hours=1))
        if terminal == "expiry"
        else await service.record_thesis_invalidation(
            value.plan_id, event_reference="event", as_of=NOW + timedelta(hours=1)
        )
    )
    before = await repository.get(value.plan_id)
    inputs = OutcomeInputs(Decimal("10"), Decimal("0"), Decimal("0"))
    with pytest.raises(TradePlanError) as error:
        await service.build_outcome(value.plan_id, inputs)
    assert error.value.code is TradePlanErrorCode.OUTCOME_PENDING
    assert await repository.get(value.plan_id) == before
    execution = await service.execute_directive(
        directive.directive_id, positioned_state("100"), NEXT_OPEN
    )
    settled_inputs = replace(
        inputs, remaining_quantity=Decimal("100") if rejected else Decimal("0")
    )
    outcome = await service.build_outcome(value.plan_id, settled_inputs)
    assert outcome.source_execution_ids == (execution.evidence_id,)
    assert outcome.adhered is not rejected
    assert outcome.rejected_count == int(rejected)
    assert await service.build_outcome(value.plan_id, settled_inputs) == outcome


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["stop", "target"])
async def test_legacy_trigger_evidence_survives_restart_without_rearming(trigger: str) -> None:
    quantity = Quantity(Decimal("100"))
    value = (
        command(hard_stop=HardStopPolicy(Decimal("11"), DirectiveType.REDUCE, quantity))
        if trigger == "stop"
        else command(profit_targets=(ProfitTarget(Decimal("9"), DirectiveType.REDUCE, quantity),))
    )
    service, repository, execution = await active_service(value)
    first = await service.evaluate(
        value.plan_id, observation("first", "10"), NOW + timedelta(hours=1)
    )
    payload = _record_json(await repository.get(value.plan_id))
    for directive in payload["directives"]:
        directive.pop("trigger_key", None)
    restored = InMemoryTradePlanRepository()
    await restored.save(_stored_record(payload))
    service = TradePlanService(restored, Calendar(), execution)
    repeated = await service.evaluate(
        value.plan_id, observation("repeat", "10"), NOW + timedelta(hours=2)
    )
    assert repeated.directive_id == first.directive_id
    before = await restored.get(value.plan_id)
    with pytest.raises(TradePlanError) as error:
        await service.evaluate(
            value.plan_id, observation("historical", "10"), NOW + timedelta(minutes=30)
        )
    assert error.value.code is TradePlanErrorCode.FUTURE_EVIDENCE
    assert await restored.get(value.plan_id) == before
    await service.execute_directive(repeated.directive_id, positioned_state("300"), NEXT_OPEN)
    service._calendar = FollowingDayCalendar()
    after = await service.evaluate(
        value.plan_id, observation("consumed", "10"), NEXT_OPEN + timedelta(hours=1)
    )
    assert after.directive_type is DirectiveType.HOLD if trigger == "target" else after == repeated
    assert execution.calls == 1
    assert len((await restored.get(value.plan_id)).executions) == 1


@pytest.mark.asyncio
async def test_draft_identity_is_immutable_at_service_and_repository_boundaries() -> None:
    from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode

    repository = InMemoryTradePlanRepository()
    service = TradePlanService(repository, Calendar(), Execution())
    original = command()
    await service.create_draft(original)
    before = await repository.get(original.plan_id)
    for changed in (
        replace(original, instrument=DOMESTIC_ETF),
        replace(original, portfolio_id=PortfolioId("shadow")),
    ):
        with pytest.raises(TradePlanError) as error:
            await service.edit_draft(original.plan_id, changed)
        assert error.value.code is TradePlanErrorCode.PROTECTED_FIELD_MUTATION
        with pytest.raises(PersistenceError) as persisted:
            await repository.save(
                replace(
                    before,
                    plan=replace(
                        before.plan,
                        portfolio_id=changed.portfolio_id,
                        instrument=changed.instrument,
                    ),
                )
            )
        assert persisted.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
        assert await repository.get(original.plan_id) == before
    edited = await service.edit_draft(
        original.plan_id,
        replace(
            original,
            horizon=InvestmentHorizon.LONG,
            style=TradingStyle.VALUE,
            thesis="valid edit",
            hard_stop=HardStopPolicy(Decimal("7")),
        ),
    )
    assert edited.instrument == original.instrument and edited.portfolio_id == original.portfolio_id
    assert edited.horizon is InvestmentHorizon.LONG and edited.thesis == "valid edit"


def test_domain_value_objects_reject_invalid_and_ambiguous_evidence() -> None:
    with pytest.raises(TradePlanError):
        TradePlanId(" ")
    for factory in (
        lambda: HardStopPolicy(Decimal("0")),
        lambda: HardStopPolicy(Decimal("1"), DirectiveType.HOLD),
        lambda: HardStopPolicy(Decimal("1"), DirectiveType.REDUCE),
        lambda: HardStopPolicy(Decimal("1"), DirectiveType.EXIT, Quantity(Decimal("1"))),
        lambda: ProfitTarget(Decimal("0"), DirectiveType.EXIT),
        lambda: ProfitTarget(Decimal("10"), DirectiveType.HOLD),
        lambda: ProfitTarget(Decimal("10"), DirectiveType.REDUCE),
        lambda: ProfitTarget(Decimal("10"), DirectiveType.EXIT, Quantity(Decimal("1"))),
        lambda: TrailingStopPolicy(Decimal("0")),
        lambda: TrailingStopPolicy(Decimal("1")),
        lambda: TrailingStopPolicy(Decimal(".1"), DirectiveType.HOLD),
        lambda: TrailingStopPolicy(Decimal(".1"), DirectiveType.REDUCE),
        lambda: TrailingStopPolicy(Decimal(".1"), DirectiveType.EXIT, Quantity(Decimal("1"))),
        lambda: TimeStopPolicy(NOW, DirectiveType.HOLD),
        lambda: TimeStopPolicy(NOW, DirectiveType.REDUCE),
        lambda: TimeStopPolicy(NOW, DirectiveType.EXIT, Quantity(Decimal("1"))),
    ):
        with pytest.raises(TradePlanError):
            factory()
    with pytest.raises(TradePlanError) as error:
        TimeStopPolicy(datetime(2026, 9, 9))
    assert error.value.code is TradePlanErrorCode.INVALID_TIMESTAMP

    base = TradePlan(
        TradePlanId("domain-plan"),
        PortfolioId("champion"),
        EQUITY,
        InvestmentHorizon.SHORT,
        TradingStyle.SWING,
        "thesis",
        Quantity(Decimal("100")),
        NOW,
        NOW,
    )
    invalid_replacements = (
        {"instrument": InstrumentIdentity(Market.CN_SSE, "CNY", InstrumentType.CASH)},
        {
            "profit_targets": (
                ProfitTarget(Decimal("12"), DirectiveType.EXIT),
                ProfitTarget(Decimal("11"), DirectiveType.EXIT),
            )
        },
        {"expiry_at": NOW},
        {"updated_at": NOW - timedelta(seconds=1)},
        {"time_stop": TimeStopPolicy(NOW)},
        {"version": 1},
        {"status": TradePlanStatus.ACTIVE, "version": 0},
    )
    for values in invalid_replacements:
        with pytest.raises(TradePlanError):
            replace(base, **values)
    with pytest.raises(TradePlanError):
        base.activate(NOW - timedelta(seconds=1))
    active = base.activate(NOW)
    with pytest.raises(TradePlanError):
        active.activate(NOW)
    terminal = active.transition(TradePlanStatus.CANCELLED, NOW, "cancel")
    with pytest.raises(TradePlanError):
        terminal.transition(TradePlanStatus.ACTIVE, NOW, "reactivate")
    with pytest.raises(TradePlanError):
        active.transition(TradePlanStatus.CANCELLED, NOW - timedelta(seconds=1), "stale")
    with pytest.raises(TradePlanError):
        active.transition(TradePlanStatus.CANCELLED, NOW, " ")

    valid_revision = TradePlanRevision(
        base.plan_id,
        1,
        NOW,
        NOW,
        "activation",
        "cto",
        "issue",
        base.thesis,
        base.target_quantity,
        base.expiry_at,
        base.policy_version,
        base.horizon,
        base.style,
        None,
        (),
        None,
        None,
        None,
    )
    for values in (
        {"version": 0},
        {"effective_at": NOW + timedelta(seconds=1)},
        {"trailing_high_water": Decimal("0")},
    ):
        with pytest.raises(TradePlanError):
            replace(valid_revision, **values)

    valid_observation = observation("domain-observation", "10")
    with pytest.raises(TradePlanError):
        replace(valid_observation, close=Decimal("0"))
    with pytest.raises(TradePlanError):
        replace(
            valid_observation,
            open=Decimal("10"),
            high=Decimal("9"),
            low=Decimal("8"),
            close=Decimal("10"),
        )

    hold = TradePlanDirective(
        "hold",
        base.plan_id,
        1,
        DirectiveType.HOLD,
        None,
        TriggerType.NO_TRIGGER,
        NOW,
        None,
        None,
        NOW,
    )
    for values in (
        {"plan_version": 0},
        {"quantity": Quantity(Decimal("1"))},
        {"directive_type": DirectiveType.EXIT},
        {"directive_type": DirectiveType.ENTRY},
    ):
        with pytest.raises(TradePlanError):
            replace(hold, **values)
    exit_directive = replace(
        hold,
        directive_type=DirectiveType.EXIT,
        not_before=NEXT_OPEN,
    )
    with pytest.raises(TradePlanError):
        replace(exit_directive, quantity=Quantity(Decimal("1")))
    with pytest.raises(TradePlanError):
        replace(exit_directive, not_before=NOW)

    with pytest.raises(TradePlanError):
        PlanExecutionEvidence(
            "evidence",
            base.plan_id,
            1,
            "directive",
            DirectiveType.ENTRY,
            "order",
            None,
            NOW,
        )
    with pytest.raises(TradePlanError):
        TradePlanOutcome(
            "outcome",
            base.plan_id,
            base.portfolio_id,
            base.instrument,
            base.horizon,
            base.style,
            NOW,
            NOW - timedelta(seconds=1),
            "bad",
            None,
            Decimal("-1"),
            Decimal("0"),
            0,
            False,
            False,
            False,
            False,
            0,
            0,
            0,
            False,
            1,
            (),
        )
