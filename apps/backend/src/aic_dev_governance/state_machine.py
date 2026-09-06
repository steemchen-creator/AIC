"""Authenticated event reducer; callers persist its result with compare-and-swap."""

from datetime import timedelta

from .gates import ChairmanGatePolicy, evaluate_merge_eligibility
from .models import (
    CI,
    ArchitectureResult,
    Event,
    EventType,
    GovernanceError,
    Policy,
    PullRequest,
    ReviewStatus,
    Role,
    Stage,
    State,
)

TRANSITIONS: dict[EventType, tuple[set[Stage], Stage, Role]] = {
    EventType.SPEC_PUBLISHED: ({Stage.PLANNED}, Stage.SPEC_READY, Role.ARCHITECT),
    EventType.CODEX_STARTED: ({Stage.SPEC_READY}, Stage.IMPLEMENTING, Role.ENGINEER),
    EventType.IMPLEMENTATION_COMPLETED: (
        {Stage.IMPLEMENTING},
        Stage.IMPLEMENTATION_COMPLETE,
        Role.ENGINEER,
    ),
    EventType.PR_CREATED: (
        {Stage.IMPLEMENTATION_COMPLETE},
        Stage.REVIEW_REQUIRED,
        Role.BOT,
    ),
    EventType.REVIEW_REQUESTED: (
        {Stage.REVIEW_REQUIRED, Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE},
        Stage.REVIEW_REQUIRED,
        Role.BOT,
    ),
    EventType.ARCH_REVIEW_STARTED: (
        {Stage.REVIEW_REQUIRED, Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE},
        Stage.ARCHITECTURE_REVIEWING,
        Role.ARCHITECT,
    ),
    EventType.ARCH_CHANGES_REQUIRED: (
        {Stage.ARCHITECTURE_REVIEWING},
        Stage.CHANGES_REQUIRED,
        Role.ARCHITECT,
    ),
    EventType.ARCH_REVIEW_COMPLETED: (
        {Stage.ARCHITECTURE_REVIEWING},
        Stage.REVIEW_REQUIRED,
        Role.ARCHITECT,
    ),
    EventType.FIX_PUBLISHED: ({Stage.CHANGES_REQUIRED}, Stage.FIX_READY, Role.ARCHITECT),
    EventType.FIX_IMPLEMENTED: ({Stage.FIXING}, Stage.REVIEW_REQUIRED, Role.ENGINEER),
    EventType.ARCH_FINAL_APPROVED: (
        {Stage.ARCHITECTURE_REVIEWING},
        Stage.FINAL_APPROVED,
        Role.ARCHITECT,
    ),
    EventType.MERGE_GATE_PASSED: (
        {Stage.FINAL_APPROVED, Stage.MERGE_ELIGIBLE},
        Stage.MERGE_ELIGIBLE,
        Role.BOT,
    ),
    EventType.MERGE_STARTED: ({Stage.MERGE_ELIGIBLE}, Stage.MERGING, Role.BOT),
    EventType.CLOSEOUT_STARTED: ({Stage.MERGED}, Stage.CLOSEOUT, Role.BOT),
    EventType.CLOSEOUT_COMPLETED: ({Stage.CLOSEOUT}, Stage.CLOSED, Role.BOT),
    EventType.NEXT_SPEC_REQUESTED: ({Stage.CLOSED}, Stage.CLOSED, Role.BOT),
}
CHAIRMAN_EVENTS = {
    EventType.PAUSE_PIPELINE,
    EventType.RESUME_PIPELINE,
    EventType.DISABLE_AUTO_MERGE,
    EventType.RECOVERY_AUTHORIZED,
}
INFORMATION_EVENTS = {
    EventType.TASK_RESERVED,
    EventType.TASK_DELIVERED,
    EventType.MEMORY_UPDATE_REQUIRED,
}
FAILURE_EVENTS = {
    EventType.CI_FAILED,
    EventType.OPERATION_FAILED,
    EventType.TASK_FAILED,
    EventType.MERGE_GATE_BLOCKED,
    EventType.CHAIRMAN_ESCALATION,
    EventType.BUDGET_LIMIT_REACHED,
    EventType.GOVERNANCE_EXCEPTION,
}
RECOVERABLE_HEAD_STAGES = {
    Stage.IMPLEMENTING,
    Stage.IMPLEMENTATION_COMPLETE,
    Stage.REVIEW_REQUIRED,
    Stage.ARCHITECTURE_REVIEWING,
    Stage.CHANGES_REQUIRED,
    Stage.FIX_READY,
    Stage.FIXING,
    Stage.FINAL_APPROVED,
    Stage.MERGE_ELIGIBLE,
    Stage.MERGING,
    Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE,
}


def authenticate(event: Event, role: Role, policy: Policy) -> None:
    if event.actor not in policy.principals.get(role, []):
        raise GovernanceError("ACTOR_NOT_AUTHORIZED")
    # An engineering principal cannot also become its own architecture approver.
    if role == Role.ARCHITECT and event.actor in policy.principals.get(Role.ENGINEER, []):
        raise GovernanceError("SELF_ARCHITECTURE_APPROVAL_FORBIDDEN")


def apply_event(
    original: State,
    event: Event,
    policy: Policy,
    *,
    pr: PullRequest | None = None,
    ci: CI | None = None,
    review: ArchitectureResult | None = None,
) -> State:
    state = original.model_copy(deep=True)
    item = state.work_items.get(event.work_item_id)
    if item is None:
        raise GovernanceError("WORK_ITEM_UNKNOWN")
    role = TRANSITIONS.get(event.event_type, (set(), Stage.BLOCKED, Role.BOT))[2]
    if event.event_type in CHAIRMAN_EVENTS:
        role = Role.CHAIRMAN
    if event.event_type == EventType.CODEX_STARTED and item.status == Stage.FIX_READY:
        role = Role.ENGINEER
    authenticate(event, role, policy)
    events = [e for e in state.events if e.work_item_id == item.work_item_id]
    if any(e.event_id == event.event_id for e in state.events):
        return state
    if events and event.timestamp < events[-1].timestamp:
        raise GovernanceError("STALE_EVENT")
    window = timedelta(minutes=policy.duplicate_event_window_minutes)
    if event.event_type not in CHAIRMAN_EVENTS | INFORMATION_EVENTS and any(
        e.event_type == event.event_type
        and e.output_state == item.status
        and e.input_sha == event.input_sha
        and event.timestamp - e.timestamp <= window
        for e in events
    ):
        return state
    if item.status == Stage.CLOSED and event.event_type not in (
        CHAIRMAN_EVENTS
        | {
            EventType.NEXT_SPEC_REQUESTED,
            EventType.BRIDGE_UNAVAILABLE,
            EventType.TASK_FAILED,
            EventType.BUDGET_LIMIT_REACHED,
            EventType.OPERATION_FAILED,
        }
        | INFORMATION_EVENTS
    ):
        raise GovernanceError("CLOSED_WORK_ITEM_IMMUTABLE")
    if item.status == Stage.CLOSED and event.event_type in {
        EventType.BRIDGE_UNAVAILABLE,
        EventType.TASK_FAILED,
        EventType.BUDGET_LIMIT_REACHED,
        EventType.OPERATION_FAILED,
    }:
        # Failure to request the NEXT item must never reopen a completed predecessor.
        state.project_blocked_reasons = [event.metadata.get("reason", event.event_type.value)]
        state.paused = event.event_type != EventType.BRIDGE_UNAVAILABLE
    elif event.event_type in CHAIRMAN_EVENTS:
        if event.event_type == EventType.RECOVERY_AUTHORIZED:
            if (
                item.status != Stage.BLOCKED
                or item.governance_exception
                or item.chairman_required
                or item.merge_commit
            ):
                raise GovernanceError("RECOVERY_NOT_ALLOWED")
            item.status = Stage.FIXING if item.unresolved_fix else Stage.REVIEW_REQUIRED
            item.blocked_reasons = []
            item.approved_head_sha = None
            item.architecture_status = ReviewStatus.REVIEW_REQUIRED
            item.merge_eligible = False
        elif event.event_type == EventType.DISABLE_AUTO_MERGE:
            state.auto_merge_disabled = True
        else:
            state.paused = event.event_type == EventType.PAUSE_PIPELINE
    elif event.event_type in FAILURE_EVENTS:
        reason = event.metadata.get("reason", event.event_type.value)
        item.blocked_reasons = sorted(set(item.blocked_reasons + [reason]))
        item.merge_eligible = False
        item.status = Stage.BLOCKED
        if event.event_type in {EventType.CHAIRMAN_ESCALATION, EventType.BUDGET_LIMIT_REACHED}:
            item.status = Stage.CHAIRMAN_DECISION_REQUIRED
            item.chairman_required = True
        if event.event_type == EventType.GOVERNANCE_EXCEPTION:
            item.governance_exception = True
            state.paused = True
        if event.event_type == EventType.CI_FAILED:
            if ci is None or ci.head_sha != item.head_sha:
                raise GovernanceError("CI_STALE")
            item.ci = ci
    elif event.event_type == EventType.PR_MERGED:
        if pr is None or pr.state != "MERGED" or pr.number != item.pr_number:
            raise GovernanceError("MERGE_NOT_VERIFIED")
        if (
            item.architecture_status != ReviewStatus.FINAL_APPROVED
            or item.approved_head_sha != pr.head_sha
            or not item.merge_eligible
            or item.status not in {Stage.MERGE_ELIGIBLE, Stage.MERGING}
            or not pr.merge_commit
            or evaluate_merge_eligibility(
                item, pr.model_copy(update={"state": "OPEN", "draft": False}), state, policy
            )
        ):
            item.governance_exception = True
            item.merge_eligible = False
            item.status = Stage.BLOCKED
            item.blocked_reasons = ["PR_MERGED_EARLY", "GOVERNANCE_EXCEPTION"]
            state.paused = True
        else:
            item.merge_commit = pr.merge_commit
            item.status = Stage.MERGED
    elif event.event_type == EventType.PR_HEAD_CHANGED:
        if item.status not in RECOVERABLE_HEAD_STAGES:
            raise GovernanceError("HEAD_CHANGE_WHILE_BLOCKED_OR_CLOSED")
        if pr is None or pr.number != item.pr_number or event.input_sha != pr.head_sha:
            raise GovernanceError("PR_IDENTITY_MISMATCH")
        item.head_sha = pr.head_sha
        item.approved_head_sha = None
        item.architecture_status = ReviewStatus.REVIEW_REQUIRED
        item.merge_eligible = False
        item.merge_expected_sha = None
        item.ci = CI()
        item.status = Stage.FIXING if item.unresolved_fix else Stage.REVIEW_REQUIRED
    elif event.event_type in {EventType.CI_STARTED, EventType.CI_PASSED}:
        if (
            ci is None
            or ci.head_sha != item.head_sha
            or event.input_sha != item.head_sha
            or item.status in {Stage.BLOCKED, Stage.CHAIRMAN_DECISION_REQUIRED}
        ):
            raise GovernanceError("CI_STALE_OR_WORK_ITEM_BLOCKED")
        item.ci = ci
        if ci.status != "PASSED":
            item.merge_eligible = False
            if item.status == Stage.MERGE_ELIGIBLE:
                item.status = Stage.FINAL_APPROVED
    elif event.event_type == EventType.BRIDGE_UNAVAILABLE:
        if item.status not in {Stage.REVIEW_REQUIRED, Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE}:
            raise GovernanceError("ILLEGAL_TRANSITION")
        item.status = Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE
    elif event.event_type in INFORMATION_EVENTS:
        if event.event_type == EventType.MEMORY_UPDATE_REQUIRED:
            item.memory_update_required = True
    elif event.event_type == EventType.CODEX_STARTED and item.status == Stage.FIX_READY:
        _enabled(state, policy)
        item.status = Stage.FIXING
    else:
        transition = TRANSITIONS.get(event.event_type)
        if transition is None or item.status not in transition[0]:
            raise GovernanceError("ILLEGAL_TRANSITION")
        _enabled(state, policy)
        item.status = transition[1]
        if event.event_type == EventType.SPEC_PUBLISHED:
            if not item.execution_authorization:
                raise GovernanceError("EXECUTION_AUTHORIZATION_MISSING")
            previous = state.work_items.get(item.previous_work_item or "")
            if previous is None or previous.status != Stage.CLOSED:
                raise GovernanceError("PREVIOUS_WORK_ITEM_NOT_CLOSED")
            if ChairmanGatePolicy().reasons(item):
                item.chairman_required = True
                item.status = Stage.CHAIRMAN_DECISION_REQUIRED
                item.blocked_reasons = ["CHAIRMAN_DECISION_REQUIRED"]
        elif event.event_type == EventType.PR_CREATED:
            if pr is None or not pr.draft or pr.state != "OPEN":
                raise GovernanceError("PR_MUST_BE_OPEN_DRAFT")
            if pr.branch != item.target_branch or pr.head_repository != policy.repository:
                raise GovernanceError("PR_IDENTITY_MISMATCH")
            item.pr_number, item.head_sha, item.base_sha = pr.number, pr.head_sha, pr.base_sha
            item.review_artifact = event.metadata.get("review_artifact")
            if not item.review_artifact:
                raise GovernanceError("REVIEW_ARTIFACT_MISSING")
        elif event.event_type in {
            EventType.ARCH_CHANGES_REQUIRED,
            EventType.ARCH_FINAL_APPROVED,
            EventType.ARCH_REVIEW_COMPLETED,
        }:
            if (
                review is None
                or review.work_item != item.work_item_id
                or review.reviewed_head_sha != item.head_sha
                or event.input_sha != item.head_sha
                or review.reviewed_at != event.timestamp
            ):
                raise GovernanceError("REVIEW_SHA_OR_IDENTITY_MISMATCH")
            expected = (
                review.result
                if event.event_type == EventType.ARCH_REVIEW_COMPLETED
                else "FINAL_APPROVED"
                if event.event_type == EventType.ARCH_FINAL_APPROVED
                else "CHANGES_REQUIRED"
            )
            if event.event_type == EventType.ARCH_REVIEW_COMPLETED and expected not in {
                "APPROVED_CANDIDATE",
                "APPROVED_WITH_NON_BLOCKING_DEBT",
            }:
                raise GovernanceError("REVIEW_RESULT_INVALID")
            if review.result != expected or (
                expected == "FINAL_APPROVED" and review.blocking_items
            ):
                raise GovernanceError("REVIEW_RESULT_INVALID")
            if review.review_id in state.reviews:
                raise GovernanceError("REVIEW_ID_ALREADY_USED")
            item.review_id = review.review_id
            state.reviews[review.review_id] = review
            for debt in review.non_blocking_items:
                if debt.blocking or debt.origin_spec != item.work_item_id:
                    raise GovernanceError("INVALID_NON_BLOCKING_DEBT")
                existing = state.technical_debt.get(debt.debt_id)
                if existing is not None and existing != debt:
                    raise GovernanceError("DEBT_ID_CONFLICT")
                state.technical_debt[debt.debt_id] = debt
            item.architecture_status = ReviewStatus(expected)
            item.approved_head_sha = item.head_sha if expected == "FINAL_APPROVED" else None
            if expected == "CHANGES_REQUIRED":
                item.unresolved_fix = review.review_id
                item.merge_eligible = False
            elif expected == "FINAL_APPROVED" and item.unresolved_fix:
                raise GovernanceError("UNRESOLVED_CHANGES_REQUIRED")
        elif event.event_type == EventType.FIX_PUBLISHED:
            path = event.metadata.get("fix_path")
            if not path:
                raise GovernanceError("FIX_ARTIFACT_MISSING")
            item.unresolved_fix = path
        elif event.event_type == EventType.FIX_IMPLEMENTED:
            item.unresolved_fix = None
            item.architecture_status = ReviewStatus.REVIEW_REQUIRED
        elif event.event_type == EventType.MERGE_GATE_PASSED:
            if pr is None:
                raise GovernanceError("PR_MISSING")
            reasons = evaluate_merge_eligibility(item, pr, state, policy)
            if reasons:
                raise GovernanceError(reasons[0])
            item.merge_eligible = True
        elif event.event_type == EventType.MERGE_STARTED:
            if not item.merge_eligible:
                raise GovernanceError("MERGE_NOT_ELIGIBLE")
            item.merge_expected_sha = item.approved_head_sha
        elif event.event_type == EventType.CLOSEOUT_COMPLETED:
            required = {
                "merge_commit",
                "tree_sha",
                "main_sha",
                "ci_head_sha",
                "local_branch_deleted",
                "remote_branch_deleted",
                "workspace_clean",
            }
            if not required.issubset(event.metadata):
                raise GovernanceError("CLOSEOUT_EVIDENCE_MISSING")
            if (
                event.metadata["merge_commit"] != item.merge_commit
                or event.metadata["ci_head_sha"] != item.approved_head_sha
                or any(
                    event.metadata[key] != "true"
                    for key in ("local_branch_deleted", "remote_branch_deleted", "workspace_clean")
                )
            ):
                raise GovernanceError("CLOSEOUT_EVIDENCE_INVALID")
            item.closeout = dict(event.metadata)
        elif event.event_type == EventType.NEXT_SPEC_REQUESTED:
            if item.chairman_required or item.governance_exception or item.next_spec_requested:
                raise GovernanceError("NEXT_SPEC_BLOCKED")
            item.next_spec_requested = True
    recorded = event.model_copy(update={"output_state": item.status})
    state.events.append(recorded)
    state.revision += 1
    return state


def _enabled(state: State, policy: Policy) -> None:
    if not policy.pipeline_enabled or state.paused:
        raise GovernanceError("PIPELINE_DISABLED_OR_PAUSED")
