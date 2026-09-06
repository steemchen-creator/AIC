from datetime import UTC, datetime, timedelta

import pytest

from aic_dev_governance.budget import reserve_call
from aic_dev_governance.gates import (
    FORBIDDEN_AREAS,
    ChairmanGatePolicy,
    automatic_merge_reasons,
    evaluate_merge_eligibility,
    sha_ci_reasons,
)
from aic_dev_governance.models import (
    Check,
    GovernanceError,
    ReviewStatus,
    Stage,
)


def test_all_green_and_draft_ready_candidate(item, pr, state, policy):
    assert evaluate_merge_eligibility(item, pr, state, policy) == []
    assert automatic_merge_reasons(item, state, policy) == []
    pr.draft = True
    assert evaluate_merge_eligibility(item, pr, state, policy) == ["PR_DRAFT"]
    assert evaluate_merge_eligibility(item, pr, state, policy, ready_candidate=True) == []


@pytest.mark.parametrize(
    ("target", "field", "value", "reason"),
    [
        ("item", "head_sha", "c" * 40, "PR_HEAD_CHANGED"),
        ("item", "approved_head_sha", "c" * 40, "APPROVAL_STALE"),
        ("item", "architecture_status", ReviewStatus.APPROVED_CANDIDATE, "ARCHITECTURE_NOT_FINAL"),
        ("item", "status", Stage.BLOCKED, "WORK_ITEM_NOT_APPROVED_STAGE"),
        ("item", "blocked_reasons", ["FAILED"], "WORK_ITEM_BLOCKED"),
        ("item", "unresolved_fix", "FIX-1", "UNRESOLVED_CHANGES_REQUIRED"),
        ("item", "governance_exception", True, "GOVERNANCE_EXCEPTION"),
        ("item", "chairman_required", True, "CHAIRMAN_DECISION_REQUIRED"),
        ("item", "changed_areas", ["real_money"], "CHAIRMAN_DECISION_REQUIRED"),
        ("item", "previous_work_item", "MISSING", "PREVIOUS_WORK_ITEM_NOT_CLOSED"),
        ("item", "target_branch", "feature/wrong", "PR_IDENTITY_MISMATCH"),
        ("item", "pr_number", 99, "PR_IDENTITY_MISMATCH"),
        ("pr", "state", "CLOSED", "PR_NOT_OPEN"),
        ("pr", "head_repository", "outsider/fork", "PR_REPOSITORY_OR_BASE_INVALID"),
        ("pr", "base_branch", "other", "PR_REPOSITORY_OR_BASE_INVALID"),
        ("state", "paused", True, "PIPELINE_DISABLED_OR_PAUSED"),
        ("policy", "pipeline_enabled", False, "PIPELINE_DISABLED_OR_PAUSED"),
    ],
)
def test_each_merge_predicate_fails_closed(item, pr, state, policy, target, field, value, reason):
    setattr({"item": item, "pr": pr, "state": state, "policy": policy}[target], field, value)
    assert reason in evaluate_merge_eligibility(item, pr, state, policy)


def test_previous_not_closed_and_budget_unhealthy(item, pr, state, policy):
    state.work_items["PREVIOUS"].status = Stage.MERGED
    item.budget.budget_limit_hits = 1
    assert set(evaluate_merge_eligibility(item, pr, state, policy)) == {
        "PREVIOUS_WORK_ITEM_NOT_CLOSED",
        "BUDGET_UNHEALTHY",
    }


def test_ci_sha_discovery_status_extra_missing_failed_and_wrong_app(item, pr, policy):
    item.ci.head_sha = "b" * 40
    item.ci.status = "FAILED"
    item.ci.discovery_complete = False
    item.ci.required_checks = {"Additional": None, "External": 900}
    item.ci.checks[0].head_sha = "b" * 40
    item.ci.checks[1].conclusion = "failure"
    item.ci.checks[2].app_id = 900
    assert set(sha_ci_reasons(item, pr, policy)) == {
        "CI_STALE",
        "REQUIRED_CHECK_DISCOVERY_INCOMPLETE",
        "CI_NOT_PASSED",
        "REQUIRED_CHECK_FAILED_OR_STALE:Governance baseline",
        "REQUIRED_CHECK_FAILED_OR_STALE:Backend tests",
        "REQUIRED_CHECK_MISSING:Desktop build",
        "REQUIRED_CHECK_MISSING:Additional",
        "REQUIRED_CHECK_MISSING:External",
    }
    item.ci.required_checks = {"External": 900}
    item.ci.checks.append(
        Check(
            name="External",
            app_id=900,
            head_sha=pr.head_sha,
            conclusion="success",
            run_id=77,
            url="https://example.test/77",
        )
    )
    assert "REQUIRED_CHECK_MISSING:External" not in sha_ci_reasons(item, pr, policy)


@pytest.mark.parametrize("area", sorted(FORBIDDEN_AREAS))
def test_every_chairman_area(item, area):
    item.changed_areas = [area, "ordinary_fix"]
    assert ChairmanGatePolicy().reasons(item) == [area]


@pytest.mark.parametrize(
    ("target", "field", "value", "reason"),
    [
        ("item", "work_item_id", "DEV-GOV-001", "BOOTSTRAP_MANUAL_MERGE_ONLY"),
        ("policy", "merge_enabled", False, "AUTO_MERGE_DISABLED"),
        ("policy", "mode", "MANUAL", "AUTO_MERGE_DISABLED"),
        ("state", "auto_merge_disabled", True, "AUTO_MERGE_DISABLED"),
    ],
)
def test_auto_merge_extra_authority(item, state, policy, target, field, value, reason):
    setattr({"item": item, "state": state, "policy": policy}[target], field, value)
    assert reason in automatic_merge_reasons(item, state, policy)


def test_normal_two_calls_duplicate_fix_and_daily_reset(state, item, policy):
    now = datetime(2026, 9, 7, tzinfo=UTC)
    assert reserve_call(state, item, policy, "spec", now, new_spec=True)
    assert reserve_call(state, item, policy, "review", now, review=True)
    assert item.budget.architecture_calls_used == 2
    assert not reserve_call(state, item, policy, "review", now, review=True)
    assert item.budget.duplicate_calls_avoided == 1
    assert reserve_call(state, item, policy, "fix-review", now, review=True)
    assert reserve_call(state, item, policy, "next", now + timedelta(days=1), new_spec=True)
    assert state.new_specs_by_day == {"2026-09-07": 1, "2026-09-08": 1}


@pytest.mark.parametrize(
    ("limit", "new_spec", "review", "reason"),
    [
        ("calls", False, False, "ARCHITECTURE_CALL_LIMIT"),
        ("loops", False, True, "REVIEW_LOOP_LIMIT"),
        ("daily", True, False, "DAILY_SPEC_LIMIT"),
    ],
)
def test_budget_limits(state, item, policy, limit, new_spec, review, reason):
    if limit == "calls":
        item.budget.architecture_calls_used = policy.max_architecture_calls_per_work_item
    elif limit == "loops":
        item.budget.review_loops = policy.max_architecture_review_loops_per_work_item
    else:
        state.new_specs_by_day["2026-09-07"] = policy.max_new_specs_per_day
    with pytest.raises(GovernanceError, match=reason):
        reserve_call(
            state,
            item,
            policy,
            "new",
            datetime(2026, 9, 7, tzinfo=UTC),
            new_spec=new_spec,
            review=review,
        )
    assert item.budget.budget_limit_hits == 1
    assert "new" not in item.budget.reserved_requests


def test_ci_workflow_head_and_completion_are_verified(item, pr, policy):
    from aic_dev_governance.models import WorkflowRun

    item.ci.workflow_runs = [
        WorkflowRun(
            run_id=1,
            head_sha=pr.head_sha,
            status="completed",
            conclusion="success",
            attempt=1,
            url="https://run.test",
        )
    ]
    assert sha_ci_reasons(item, pr, policy) == []
    item.ci.workflow_runs[0].head_sha = "b" * 40
    assert "CI_WORKFLOW_STALE_OR_FAILED" in sha_ci_reasons(item, pr, policy)


def test_missing_branch_protection_is_activation_blocker(item, pr, state, policy):
    item.ci.branch_protection_enabled = False
    assert "ADMIN_SETUP_REQUIRED" in evaluate_merge_eligibility(item, pr, state, policy)
