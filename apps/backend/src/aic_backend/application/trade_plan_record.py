"""Aggregate persistence record owned by the Trade Plan application layer."""

from dataclasses import dataclass

from aic_backend.domain.trade_plan import (
    PlanExecutionEvidence,
    TradePlan,
    TradePlanDirective,
    TradePlanOutcome,
    TradePlanRevision,
)


@dataclass(frozen=True, slots=True)
class TradePlanRecord:
    plan: TradePlan
    revisions: tuple[TradePlanRevision, ...] = ()
    directives: tuple[TradePlanDirective, ...] = ()
    executions: tuple[PlanExecutionEvidence, ...] = ()
    outcome: TradePlanOutcome | None = None

    def __post_init__(self) -> None:
        if any(value.plan_id != self.plan.plan_id for value in self.revisions):
            raise ValueError("revision belongs to another plan")
        if any(value.plan_id != self.plan.plan_id for value in self.directives):
            raise ValueError("directive belongs to another plan")
        if any(value.plan_id != self.plan.plan_id for value in self.executions):
            raise ValueError("execution evidence belongs to another plan")
        versions = tuple(value.version for value in self.revisions)
        if versions != tuple(range(1, len(versions) + 1)):
            raise ValueError("revision versions must be contiguous and ordered")
        if self.plan.version != len(self.revisions):
            raise ValueError("plan version must match revision history")
        if self.outcome is not None and self.outcome.plan_id != self.plan.plan_id:
            raise ValueError("outcome belongs to another plan")
