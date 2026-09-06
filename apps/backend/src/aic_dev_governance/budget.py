"""Persistent reservation before external delivery; duplicates never spend another call."""

from datetime import UTC, datetime

from .models import GovernanceError, Policy, State, WorkItem


def reserve_call(
    state: State,
    item: WorkItem,
    policy: Policy,
    key: str,
    now: datetime,
    *,
    new_spec: bool = False,
    review: bool = False,
) -> bool:
    budget = item.budget
    if key in budget.reserved_requests:
        budget.duplicate_calls_avoided += 1
        return False
    day = now.astimezone(UTC).date().isoformat()
    reason = None
    if budget.architecture_calls_used >= policy.max_architecture_calls_per_work_item:
        reason = "ARCHITECTURE_CALL_LIMIT"
    if review and budget.review_loops >= policy.max_architecture_review_loops_per_work_item:
        reason = "REVIEW_LOOP_LIMIT"
    if new_spec and state.new_specs_by_day.get(day, 0) >= policy.max_new_specs_per_day:
        reason = "DAILY_SPEC_LIMIT"
    if reason:
        budget.budget_limit_hits += 1
        raise GovernanceError(reason)
    budget.reserved_requests.append(key)
    budget.architecture_calls_used += 1
    if review:
        budget.review_loops += 1
    if new_spec:
        state.new_specs_by_day[day] = state.new_specs_by_day.get(day, 0) + 1
    return True
