from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aic_dev_governance.models import (
    CI,
    ArchitectureResult,
    Debt,
    Event,
    EventType,
    GovernanceError,
    Role,
    Stage,
)
from aic_dev_governance.state_machine import (
    CHAIRMAN_EVENTS,
    TRANSITIONS,
    apply_event,
    authenticate,
)


def event(kind, *, actor=None, sha="a" * 40, metadata=None, offset=0):
    role = TRANSITIONS.get(kind, (None, None, Role.BOT))[2]
    if kind in CHAIRMAN_EVENTS:
        role = Role.CHAIRMAN
    principal = {
        Role.BOT: "bot",
        Role.ARCHITECT: "architect",
        Role.ENGINEER: "engineer",
        Role.CHAIRMAN: "chairman",
    }[role]
    return Event(
        event_id=uuid4().hex,
        event_type=kind,
        work_item_id="SPEC-TEST",
        actor=actor or principal,
        input_sha=sha,
        timestamp=datetime(2026, 9, 7, tzinfo=UTC) + timedelta(minutes=offset),
        metadata=metadata or {},
    )


def result(kind="FINAL_APPROVED", **updates):
    return ArchitectureResult(
        work_item="SPEC-TEST",
        review_id=updates.pop("review_id", "ARCH-1"),
        result=kind,
        reviewed_head_sha=updates.pop("reviewed_head_sha", "a" * 40),
        blocking_items=updates.pop("blocking_items", []),
        non_blocking_items=[],
        reviewed_at=datetime(2026, 9, 7, tzinfo=UTC),
        reviewer_role="CHIEF_INVESTMENT_ARCHITECT",
        **updates,
    )


def test_authority_unknown_work_and_event_validation(state, policy):
    with pytest.raises(GovernanceError, match="ACTOR_NOT_AUTHORIZED"):
        apply_event(state, event(EventType.ARCH_FINAL_APPROVED, actor="engineer"), policy)
    policy.principals[Role.ARCHITECT].append("engineer")
    with pytest.raises(GovernanceError, match="SELF_ARCHITECTURE_APPROVAL"):
        authenticate(event(EventType.ARCH_FINAL_APPROVED, actor="engineer"), Role.ARCHITECT, policy)
    unknown = event(EventType.CI_STARTED)
    unknown.work_item_id = "MISSING"
    with pytest.raises(GovernanceError, match="WORK_ITEM_UNKNOWN"):
        apply_event(state, unknown, policy)
    with pytest.raises(ValidationError, match="TIMESTAMP_NOT_AWARE"):
        event(EventType.CI_STARTED).timestamp = datetime(2026, 9, 7)
    with pytest.raises(ValidationError, match="TIMESTAMP_NOT_AWARE"):
        result().reviewed_at = datetime(2026, 9, 7)


def test_legal_lifecycle_and_duplicate_stale_events(state, item, pr, policy):
    item.status = Stage.PLANNED
    for kind in (
        EventType.SPEC_PUBLISHED,
        EventType.CODEX_STARTED,
        EventType.IMPLEMENTATION_COMPLETED,
    ):
        state = apply_event(state, event(kind), policy)
    pr.draft = True
    created = event(EventType.PR_CREATED, metadata={"review_artifact": "REVIEW-TEST.md"})
    state = apply_event(state, created, policy, pr=pr)
    assert apply_event(state, created, policy, pr=pr) == state
    assert apply_event(state, event(EventType.PR_CREATED), policy, pr=pr) == state
    stale = event(EventType.CI_STARTED, offset=-1)
    with pytest.raises(GovernanceError, match="STALE_EVENT"):
        apply_event(state, stale, policy)
    state = apply_event(state, event(EventType.REVIEW_REQUESTED), policy)
    state = apply_event(state, event(EventType.ARCH_REVIEW_STARTED), policy)
    state = apply_event(state, event(EventType.ARCH_FINAL_APPROVED), policy, review=result())
    pr.draft = False
    state = apply_event(state, event(EventType.MERGE_GATE_PASSED), policy, pr=pr)
    state = apply_event(state, event(EventType.MERGE_STARTED), policy)
    pr.state, pr.merge_commit = "MERGED", "c" * 40
    state = apply_event(state, event(EventType.PR_MERGED), policy, pr=pr)
    state = apply_event(state, event(EventType.CLOSEOUT_STARTED), policy)
    state = apply_event(
        state,
        event(
            EventType.CLOSEOUT_COMPLETED,
            metadata={
                "merge_commit": "c" * 40,
                "tree_sha": "d" * 40,
                "main_sha": "c" * 40,
                "ci_head_sha": "a" * 40,
                "local_branch_deleted": "true",
                "remote_branch_deleted": "true",
                "workspace_clean": "true",
            },
        ),
        policy,
    )
    state = apply_event(state, event(EventType.NEXT_SPEC_REQUESTED), policy)
    assert state.work_items[item.work_item_id].status == Stage.CLOSED
    assert state.work_items[item.work_item_id].next_spec_requested
    assert len(state.events) == state.revision
    assert all(e.output_state for e in state.events)


@pytest.mark.parametrize("kind", list(TRANSITIONS))
def test_illegal_transitions_cannot_jump_out_of_blocked_state(state, item, policy, kind):
    item.status = Stage.BLOCKED
    with pytest.raises(GovernanceError, match="ILLEGAL_TRANSITION"):
        apply_event(state, event(kind), policy)


def test_closed_state_rollback_and_next_spec_blockers(state, item, policy):
    item.status = Stage.CLOSED
    with pytest.raises(GovernanceError, match="CLOSED_WORK_ITEM_IMMUTABLE"):
        apply_event(state, event(EventType.PR_HEAD_CHANGED), policy)
    for field in ("chairman_required", "governance_exception", "next_spec_requested"):
        setattr(item, field, True)
        with pytest.raises(GovernanceError, match="NEXT_SPEC_BLOCKED"):
            apply_event(state, event(EventType.NEXT_SPEC_REQUESTED), policy)
        setattr(item, field, False)


def test_pause_resume_disable_and_audited_recovery(state, item, policy):
    state = apply_event(state, event(EventType.PAUSE_PIPELINE), policy)
    assert state.paused
    with pytest.raises(GovernanceError, match="PIPELINE_DISABLED_OR_PAUSED"):
        apply_event(state, event(EventType.MERGE_GATE_PASSED), policy)
    state = apply_event(state, event(EventType.RESUME_PIPELINE), policy)
    assert not state.paused
    state = apply_event(state, event(EventType.DISABLE_AUTO_MERGE), policy)
    assert state.auto_merge_disabled
    state = apply_event(
        state, event(EventType.OPERATION_FAILED, metadata={"reason": "GITHUB"}), policy
    )
    state = apply_event(state, event(EventType.RECOVERY_AUTHORIZED), policy)
    assert state.work_items[item.work_item_id].status == Stage.REVIEW_REQUIRED
    assert state.work_items[item.work_item_id].approved_head_sha is None
    with pytest.raises(GovernanceError, match="RECOVERY_NOT_ALLOWED"):
        apply_event(state, event(EventType.RECOVERY_AUTHORIZED), policy)


@pytest.mark.parametrize(
    "kind",
    [
        EventType.CHAIRMAN_ESCALATION,
        EventType.BUDGET_LIMIT_REACHED,
        EventType.GOVERNANCE_EXCEPTION,
        EventType.TASK_FAILED,
        EventType.MERGE_GATE_BLOCKED,
    ],
)
def test_failure_classes_stop_pipeline(state, item, policy, kind):
    updated = apply_event(state, event(kind), policy)
    changed = updated.work_items[item.work_item_id]
    assert not changed.merge_eligible and changed.blocked_reasons
    if kind == EventType.GOVERNANCE_EXCEPTION:
        assert changed.governance_exception and updated.paused
    if kind in {EventType.CHAIRMAN_ESCALATION, EventType.BUDGET_LIMIT_REACHED}:
        assert changed.chairman_required and changed.status == Stage.CHAIRMAN_DECISION_REQUIRED


def test_ci_updates_and_stale_failure(state, item, policy):
    with pytest.raises(GovernanceError, match="CI_STALE"):
        apply_event(state, event(EventType.CI_FAILED), policy)
    failed = item.ci.model_copy(update={"status": "FAILED"})
    assert (
        apply_event(state, event(EventType.CI_FAILED), policy, ci=failed)
        .work_items[item.work_item_id]
        .status
        == Stage.RECOVERABLE_FAILURE
    )
    assert (
        apply_event(state, event(EventType.CI_PASSED), policy, ci=item.ci)
        .work_items[item.work_item_id]
        .ci.status
        == "PASSED"
    )
    assert apply_event(state, event(EventType.CI_STARTED), policy, ci=item.ci).revision == 1
    for ci in (None, CI(head_sha="b" * 40)):
        with pytest.raises(GovernanceError, match="CI_STALE_OR_WORK_ITEM_BLOCKED"):
            apply_event(state, event(EventType.CI_STARTED), policy, ci=ci)


def test_engineering_failure_and_retry_need_no_chairman(state, item, policy):
    item.status = Stage.IMPLEMENTING
    state = apply_event(
        state,
        event(EventType.ENGINEERING_FAILED, metadata={"reason": "TEST_FAILURE"}),
        policy,
    )
    failed = state.work_items[item.work_item_id]
    assert failed.status == Stage.RECOVERABLE_FAILURE
    assert failed.recovery_stage == Stage.IMPLEMENTING
    assert failed.recoverable_failures == ["TEST_FAILURE"]
    state = apply_event(state, event(EventType.ENGINEERING_RETRY), policy)
    assert state.work_items[item.work_item_id].status == Stage.IMPLEMENTING
    assert not state.work_items[item.work_item_id].recoverable_failures


def test_recoverable_failure_preserves_origin_and_normalizes_merge_stage(state, item, policy):
    item.status = Stage.MERGE_ELIGIBLE
    first = apply_event(
        state,
        event(
            EventType.OPERATION_FAILED,
            metadata={"reason": "GET_FAILED", "failure_class": "RECOVERABLE_READ"},
        ),
        policy,
    )
    current = first.work_items[item.work_item_id]
    assert current.status == Stage.RECOVERABLE_FAILURE
    assert current.recovery_stage == Stage.FINAL_APPROVED
    second = apply_event(
        first,
        event(
            EventType.OPERATION_FAILED,
            sha="b" * 40,
            metadata={"reason": "GET_FAILED_AGAIN", "failure_class": "RECOVERABLE_READ"},
        ),
        policy,
    )
    current = second.work_items[item.work_item_id]
    assert current.recovery_stage == Stage.FINAL_APPROVED
    assert current.recoverable_failures == ["GET_FAILED", "GET_FAILED_AGAIN"]


def test_engineering_bridge_unavailable_only_from_dispatchable_stage(state, item, policy):
    with pytest.raises(GovernanceError, match="ILLEGAL_TRANSITION"):
        apply_event(state, event(EventType.ENGINEERING_BRIDGE_UNAVAILABLE), policy)
    item.status = Stage.SPEC_READY
    updated = apply_event(state, event(EventType.ENGINEERING_BRIDGE_UNAVAILABLE), policy)
    assert updated.work_items[item.work_item_id].recovery_stage == Stage.SPEC_READY


def test_spec_authorization_previous_and_chairman_gate(state, item, policy):
    item.status = Stage.PLANNED
    item.execution_authorization = ""
    with pytest.raises(GovernanceError, match="EXECUTION_AUTHORIZATION_MISSING"):
        apply_event(state, event(EventType.SPEC_PUBLISHED), policy)
    item.execution_authorization = "owner"
    item.previous_work_item = None
    with pytest.raises(GovernanceError, match="PREVIOUS_WORK_ITEM_NOT_CLOSED"):
        apply_event(state, event(EventType.SPEC_PUBLISHED), policy)
    item.previous_work_item = "PREVIOUS"
    item.changed_areas = ["real_money"]
    updated = apply_event(state, event(EventType.SPEC_PUBLISHED), policy)
    assert updated.work_items[item.work_item_id].status == Stage.CHAIRMAN_DECISION_REQUIRED


def test_pr_must_be_draft_and_correct_identity(state, item, pr, policy):
    item.status = Stage.IMPLEMENTATION_COMPLETE
    for invalid in (None, pr):
        with pytest.raises(GovernanceError, match="PR_MUST_BE_OPEN_DRAFT"):
            apply_event(state, event(EventType.PR_CREATED), policy, pr=invalid)
    pr.draft = True
    pr.branch = "feature/wrong"
    with pytest.raises(GovernanceError, match="PR_IDENTITY_MISMATCH"):
        apply_event(state, event(EventType.PR_CREATED), policy, pr=pr)
    pr.branch = item.target_branch
    with pytest.raises(GovernanceError, match="REVIEW_ARTIFACT_MISSING"):
        apply_event(state, event(EventType.PR_CREATED), policy, pr=pr)


def test_head_change_invalidates_approval_and_old_ci(state, item, pr, policy):
    pr.head_sha = "b" * 40
    with pytest.raises(GovernanceError, match="PR_IDENTITY_MISMATCH"):
        apply_event(state, event(EventType.PR_HEAD_CHANGED), policy, pr=pr)
    updated = apply_event(state, event(EventType.PR_HEAD_CHANGED, sha=pr.head_sha), policy, pr=pr)
    changed = updated.work_items[item.work_item_id]
    assert changed.status == Stage.REVIEW_REQUIRED and changed.approved_head_sha is None
    assert changed.ci.status == "UNKNOWN" and not changed.merge_eligible
    item.unresolved_fix = "FIX-1"
    assert (
        apply_event(state, event(EventType.PR_HEAD_CHANGED, sha=pr.head_sha), policy, pr=pr)
        .work_items[item.work_item_id]
        .status
        == Stage.FIXING
    )
    item.status = Stage.BLOCKED
    with pytest.raises(GovernanceError, match="HEAD_CHANGE_WHILE_BLOCKED_OR_CLOSED"):
        apply_event(state, event(EventType.PR_HEAD_CHANGED, sha=pr.head_sha), policy, pr=pr)


def test_fix_loop_and_candidate_is_not_final(state, item, policy):
    item.status = Stage.ARCHITECTURE_REVIEWING
    state = apply_event(
        state,
        event(EventType.ARCH_CHANGES_REQUIRED),
        policy,
        review=result("CHANGES_REQUIRED", blocking_items=["fix race"]),
    )
    with pytest.raises(GovernanceError, match="FIX_ARTIFACT_MISSING"):
        apply_event(state, event(EventType.FIX_PUBLISHED), policy)
    state = apply_event(
        state, event(EventType.FIX_PUBLISHED, metadata={"fix_path": "FIX-1.md"}), policy
    )
    state = apply_event(state, event(EventType.CODEX_STARTED), policy)
    assert state.work_items[item.work_item_id].status == Stage.FIXING
    state = apply_event(state, event(EventType.FIX_IMPLEMENTED), policy)
    assert state.work_items[item.work_item_id].unresolved_fix is None
    state.work_items[item.work_item_id].status = Stage.ARCHITECTURE_REVIEWING
    state = apply_event(
        state,
        event(EventType.ARCH_REVIEW_COMPLETED),
        policy,
        review=result("APPROVED_CANDIDATE", review_id="ARCH-2"),
    )
    assert state.work_items[item.work_item_id].approved_head_sha is None


@pytest.mark.parametrize(
    ("review", "reason"),
    [
        (None, "REVIEW_SHA_OR_IDENTITY_MISMATCH"),
        (result(reviewed_head_sha="b" * 40), "REVIEW_SHA_OR_IDENTITY_MISMATCH"),
        (result("CHANGES_REQUIRED"), "REVIEW_RESULT_INVALID"),
        (result(blocking_items=["block"]), "REVIEW_RESULT_INVALID"),
    ],
)
def test_review_rejects_missing_stale_or_nonfinal(state, item, policy, review, reason):
    item.status = Stage.ARCHITECTURE_REVIEWING
    with pytest.raises(GovernanceError, match=reason):
        apply_event(state, event(EventType.ARCH_FINAL_APPROVED), policy, review=review)


def test_review_debt_uniqueness_and_unresolved_fix(state, item, policy):
    item.status = Stage.ARCHITECTURE_REVIEWING
    review = result()
    state.reviews[review.review_id] = review
    with pytest.raises(GovernanceError, match="REVIEW_ID_ALREADY_USED"):
        apply_event(state, event(EventType.ARCH_FINAL_APPROVED), policy, review=review)
    state.reviews = {}
    debt = Debt(
        debt_id="D-1",
        origin_spec=item.work_item_id,
        description="setup",
        severity="LOW",
        blocking=False,
        target_phase="setup",
    )
    review.non_blocking_items = [debt]
    updated = apply_event(state, event(EventType.ARCH_FINAL_APPROVED), policy, review=review)
    assert updated.technical_debt["D-1"] == debt
    state.technical_debt = {"D-1": debt.model_copy(update={"description": "different"})}
    with pytest.raises(GovernanceError, match="DEBT_ID_CONFLICT"):
        apply_event(state, event(EventType.ARCH_FINAL_APPROVED), policy, review=review)
    state.technical_debt = {}
    debt.blocking = True
    with pytest.raises(GovernanceError, match="INVALID_NON_BLOCKING_DEBT"):
        apply_event(state, event(EventType.ARCH_FINAL_APPROVED), policy, review=review)
    debt.blocking = False
    item.unresolved_fix = "FIX-OPEN"
    with pytest.raises(GovernanceError, match="UNRESOLVED_CHANGES_REQUIRED"):
        apply_event(state, event(EventType.ARCH_FINAL_APPROVED), policy, review=review)
    with pytest.raises(GovernanceError, match="REVIEW_RESULT_INVALID"):
        apply_event(state, event(EventType.ARCH_REVIEW_COMPLETED), policy, review=review)


def test_merge_gate_and_closeout_missing_evidence(state, item, pr, policy):
    with pytest.raises(GovernanceError, match="PR_MISSING"):
        apply_event(state, event(EventType.MERGE_GATE_PASSED), policy)
    pr.draft = True
    with pytest.raises(GovernanceError, match="PR_DRAFT"):
        apply_event(state, event(EventType.MERGE_GATE_PASSED), policy, pr=pr)
    item.status = Stage.MERGE_ELIGIBLE
    with pytest.raises(GovernanceError, match="MERGE_NOT_ELIGIBLE"):
        apply_event(state, event(EventType.MERGE_STARTED), policy)
    with pytest.raises(GovernanceError, match="MERGE_NOT_VERIFIED"):
        apply_event(state, event(EventType.PR_MERGED), policy)
    pr.state, pr.merge_commit = "MERGED", "c" * 40
    updated = apply_event(state, event(EventType.PR_MERGED), policy, pr=pr)
    assert updated.paused and updated.work_items[item.work_item_id].governance_exception
    assert not updated.work_items[item.work_item_id].next_spec_requested
    item.status = Stage.CLOSEOUT
    with pytest.raises(GovernanceError, match="CLOSEOUT_EVIDENCE_MISSING"):
        apply_event(state, event(EventType.CLOSEOUT_COMPLETED), policy)
    bad = {
        "merge_commit": "wrong",
        "tree_sha": "x",
        "main_sha": "y",
        "ci_head_sha": "z",
        "local_branch_deleted": "true",
        "remote_branch_deleted": "false",
        "workspace_clean": "true",
    }
    with pytest.raises(GovernanceError, match="CLOSEOUT_EVIDENCE_INVALID"):
        apply_event(state, event(EventType.CLOSEOUT_COMPLETED, metadata=bad), policy)


def test_bridge_wait_memory_and_kill_switch(state, item, policy):
    with pytest.raises(GovernanceError, match="ILLEGAL_TRANSITION"):
        apply_event(state, event(EventType.BRIDGE_UNAVAILABLE), policy)
    item.status = Stage.REVIEW_REQUIRED
    state = apply_event(state, event(EventType.BRIDGE_UNAVAILABLE), policy)
    assert (
        state.work_items[item.work_item_id].status == Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE
    )
    state = apply_event(state, event(EventType.MEMORY_UPDATE_REQUIRED), policy)
    assert state.work_items[item.work_item_id].memory_update_required
    state = apply_event(state, event(EventType.TASK_DELIVERED), policy)
    policy.pipeline_enabled = False
    with pytest.raises(GovernanceError, match="PIPELINE_DISABLED_OR_PAUSED"):
        apply_event(state, event(EventType.REVIEW_REQUESTED), policy)


def test_ci_rerun_invalidates_merge_gate_without_invalidating_same_sha_review(state, item, policy):
    item.status, item.merge_eligible = Stage.MERGE_ELIGIBLE, True
    ci = item.ci.model_copy(update={"status": "PENDING"})
    updated = apply_event(state, event(EventType.CI_STARTED), policy, ci=ci)
    current = updated.work_items[item.work_item_id]
    assert current.status == Stage.FINAL_APPROVED and not current.merge_eligible
    assert current.approved_head_sha == item.head_sha


@pytest.mark.parametrize("kind", [EventType.BRIDGE_UNAVAILABLE, EventType.BUDGET_LIMIT_REACHED])
def test_next_spec_failure_does_not_reopen_closed_predecessor(state, item, policy, kind):
    item.status = Stage.CLOSED
    updated = apply_event(state, event(kind), policy)
    assert updated.work_items[item.work_item_id].status == Stage.CLOSED
    assert updated.project_blocked_reasons
