"""Chairman recovery traverses the real runner, repository boundary and durable reducer."""

from datetime import UTC, datetime, timedelta
from itertools import count
from unittest.mock import Mock

import httpx
import pytest

from aic_dev_governance.github import GitHubClient
from aic_dev_governance.models import CI, EventType, GovernanceError, ReviewStatus, Stage
from aic_dev_governance.orchestrator import Orchestrator
from aic_dev_governance.runner import dispatch_command
from aic_dev_governance.state_machine import apply_event
from aic_dev_governance.store import LocalFileStateStore

SENSITIVE = "SENSITIVE_DIFF:master_project_objective"
OLD_HEAD = "a" * 40
HEAD = "d" * 40


@pytest.fixture
def recovery(tmp_path, state, item, pr, policy):
    item.status = Stage.REVIEW_REQUIRED
    item.approved_head_sha = None
    item.architecture_status = ReviewStatus.REVIEW_REQUIRED
    pr.draft = True
    repository = Mock(spec=GitHubClient)
    repository.pull_request.side_effect = lambda number: pr.model_copy(deep=True)
    repository.changed_paths.return_value = ["docs/project/TECHNICAL_DEBT.md"]
    repository.ci.side_effect = lambda current, policy: CI(
        head_sha=current.head_sha, status="FAILED"
    )
    clock = count()
    runtime = Orchestrator(
        LocalFileStateStore(tmp_path / "state"),
        repository,
        policy,
        "bot",
        now=lambda: datetime(2026, 9, 9, tzinfo=UTC) + timedelta(seconds=next(clock)),
    )
    state.events.append(runtime.event(item.work_item_id, EventType.TASK_RESERVED))
    state.revision += 1
    runtime.store.save(state, None)
    escalated = runtime.reconcile(item.work_item_id)
    assert escalated.work_items[item.work_item_id].status == Stage.CHAIRMAN_DECISION_REQUIRED
    assert escalated.work_items[item.work_item_id].blocked_reasons == [SENSITIVE]
    assert escalated.work_items[item.work_item_id].chairman_required
    # Reproduce the historical read/CI failure, then reconciliation of the later clean HEAD.
    runtime.handle(
        runtime.event(item.work_item_id, EventType.CI_FAILED, OLD_HEAD),
        ci=CI(head_sha=OLD_HEAD, status="FAILED"),
    )
    pr.head_sha = HEAD
    repository.changed_paths.return_value = ["apps/backend/application/example.py"]
    runtime.reconcile(item.work_item_id)
    return runtime, repository, pr, item.work_item_id


def command(recovery, tmp_path, *, actor="chairman", head=HEAD, extra=None):
    runtime, github, _, work = recovery
    payload = {"work_item_id": work, "event_type": "SENSITIVE_DIFF_REVALIDATED", "head_sha": head}
    payload.update(extra or {})
    return dispatch_command(runtime, github, tmp_path, actor, "event", payload)


def persist(recovery, mutation):
    runtime, _, _, work = recovery
    state, revision = runtime.store.load()
    mutation(state.work_items[work])
    state.events.append(runtime.event(work, EventType.TASK_RESERVED))
    state.revision += 1
    runtime.store.save(state, revision)


def test_clean_head_preserves_latch_then_chairman_recovery_and_fresh_ci(recovery, tmp_path):
    runtime, github, _, work = recovery
    before, revision = runtime.store.load()
    item = before.work_items[work]
    assert item.head_sha == HEAD
    assert item.status == Stage.RECOVERABLE_FAILURE
    assert item.recovery_stage == Stage.REVIEW_REQUIRED
    assert item.recoverable_failures == ["CI_FAILED"]
    assert item.blocked_reasons == [SENSITIVE] and item.chairman_required
    assert any(
        e.event_type == EventType.CHAIRMAN_ESCALATION and e.input_sha == OLD_HEAD
        for e in before.events
    )
    github.reset_mock()
    recovered = command(recovery, tmp_path)
    current = recovered.work_items[work]
    assert current.blocked_reasons == [] and not current.chairman_required
    assert current.status == item.status
    assert current.recovery_stage == item.recovery_stage
    assert current.recoverable_failures == item.recoverable_failures
    assert current.ci == item.ci and current.ci.status == "FAILED"
    assert not current.approved_head_sha and not current.merge_eligible
    assert recovered.events[:-1] == before.events
    assert recovered.reviews == before.reviews and recovered.artifacts == before.artifacts
    event = recovered.events[-1]
    assert event.actor == "chairman" and event.input_sha == HEAD
    assert event.event_type == EventType.SENSITIVE_DIFF_REVALIDATED
    assert event.metadata["pr_number"] == "12"
    assert event.metadata["base_sha"] == "b" * 40
    assert len(event.metadata["changed_paths_sha256"]) == 64
    assert github.pull_request.call_count == 2
    github.changed_paths.assert_called_once_with(12)
    github.ci.assert_not_called()
    github.merge.assert_not_called()
    stored, new_revision = runtime.store.load()
    assert stored == recovered and new_revision != revision
    passed = runtime.handle(
        runtime.event(work, EventType.CI_PASSED, HEAD), ci=CI(head_sha=HEAD, status="PASSED")
    )
    assert passed.work_items[work].status == Stage.REVIEW_REQUIRED
    assert passed.work_items[work].recovery_stage is None
    assert passed.work_items[work].recoverable_failures == []
    assert passed.events[:-1] == recovered.events


@pytest.mark.parametrize("fix", [None, "fixes/FIX-TEST.md"])
def test_pure_chairman_state_returns_to_review_or_fix(recovery, tmp_path, fix):
    def pure(item):
        item.status = Stage.CHAIRMAN_DECISION_REQUIRED
        item.recovery_stage = None
        item.recoverable_failures = []
        item.unresolved_fix = fix

    persist(recovery, pure)
    result = command(recovery, tmp_path)
    item = result.work_items[recovery[3]]
    assert item.status == (Stage.FIXING if fix else Stage.REVIEW_REQUIRED)
    assert item.unresolved_fix == fix


@pytest.mark.parametrize("actor", ["engineer", "architect", "bot", "outsider"])
def test_only_chairman_can_request_or_directly_apply(recovery, tmp_path, actor):
    runtime, github, _, work = recovery
    before = runtime.store.load()
    github.reset_mock()
    with pytest.raises(GovernanceError, match="ACTOR_NOT_AUTHORIZED"):
        command(recovery, tmp_path, actor=actor)
    event = runtime.event(work, EventType.SENSITIVE_DIFF_REVALIDATED, HEAD)
    event.actor = actor
    with pytest.raises(GovernanceError, match="ACTOR_NOT_AUTHORIZED"):
        runtime.handle(event)
    assert runtime.store.load() == before
    github.pull_request.assert_not_called()


@pytest.mark.parametrize("head", [OLD_HEAD, "e" * 40])
def test_stale_requested_head_rejected(recovery, tmp_path, head):
    runtime = recovery[0]
    before = runtime.store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_STALE_HEAD"):
        command(recovery, tmp_path, head=head)
    assert runtime.store.load() == before


@pytest.mark.parametrize(
    "extra",
    [
        {"metadata": {"changed_paths": "[]"}},
        {"changed_paths": []},
        {"pr_number": 19},
        {"actor": "chairman"},
    ],
)
def test_untrusted_claims_rejected(recovery, tmp_path, extra):
    before = recovery[0].store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_PAYLOAD_INVALID"):
        command(recovery, tmp_path, extra=extra)
    assert recovery[0].store.load() == before


@pytest.mark.parametrize("head", [None, "", "not-a-sha", 19])
def test_explicit_valid_head_required(recovery, tmp_path, head):
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_HEAD_REQUIRED"):
        command(recovery, tmp_path, head=head)


@pytest.mark.parametrize(
    "path",
    [
        "docs/project/TECHNICAL_DEBT.md",
        ".github/workflows/ci.yml",
        "apps/backend/src/aic_backend/domain/portfolio/policies.py",
    ],
)
def test_any_current_sensitive_area_rejected(recovery, tmp_path, path):
    runtime, github, _, _ = recovery
    github.changed_paths.return_value = [path]
    before = runtime.store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_STILL_PRESENT"):
        command(recovery, tmp_path)
    assert runtime.store.load() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("number", 99),
        ("branch", "feature/another"),
        ("head_repository", "other/AIC"),
        ("base_branch", "other"),
        ("state", "CLOSED"),
        ("state", "MERGED"),
        ("head_sha", OLD_HEAD),
    ],
)
def test_actual_pr_identity_must_match(recovery, tmp_path, field, value):
    runtime, _, pr, _ = recovery
    setattr(pr, field, value)
    before = runtime.store.load()
    reason = "STALE_HEAD" if field == "head_sha" else "PR_IDENTITY_MISMATCH"
    with pytest.raises(GovernanceError, match=reason):
        command(recovery, tmp_path)
    assert runtime.store.load() == before


@pytest.mark.parametrize(
    "field,value", [("head_sha", OLD_HEAD), ("base_sha", "f" * 40), ("state", "CLOSED")]
)
def test_pr_changes_during_diff_read_abort(recovery, tmp_path, field, value):
    runtime, github, pr, _ = recovery
    github.pull_request.side_effect = [pr, pr.model_copy(update={field: value})]
    before = runtime.store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_PR_CHANGED"):
        command(recovery, tmp_path)
    assert runtime.store.load() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("governance_exception", True),
        ("merge_commit", "f" * 40),
        ("merge_expected_sha", "f" * 40),
        ("status", Stage.CLOSED),
        ("status", Stage.BLOCKED),
        ("status", Stage.MERGING),
    ],
)
def test_incidents_and_unsupported_states_rejected(recovery, tmp_path, field, value):
    persist(recovery, lambda item: setattr(item, field, value))
    before = recovery[0].store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_NOT_ALLOWED"):
        command(recovery, tmp_path)
    assert recovery[0].store.load() == before


@pytest.mark.parametrize(
    "reason",
    [
        "BUDGET_LIMIT_REACHED",
        "MERGE_OUTCOME_UNKNOWN",
        "SECURITY_POLICY_CHANGE",
        "OTHER_CHAIRMAN_CAUSE",
    ],
)
def test_unrelated_blockers_preserved_by_rejecting_mixed_recovery(recovery, tmp_path, reason):
    persist(recovery, lambda item: item.blocked_reasons.append(reason))
    before = recovery[0].store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_OTHER_BLOCKERS"):
        command(recovery, tmp_path)
    assert recovery[0].store.load() == before


@pytest.mark.parametrize(
    "kind",
    [
        EventType.BUDGET_LIMIT_REACHED,
        EventType.CHAIRMAN_ESCALATION,
        EventType.GOVERNANCE_EXCEPTION,
        EventType.MERGE_STARTED,
        EventType.PR_MERGED,
    ],
)
def test_other_historical_chairman_or_merge_cause_cannot_be_cleared(recovery, tmp_path, kind):
    runtime, _, _, work = recovery
    state, revision = runtime.store.load()
    state.events.append(runtime.event(work, kind, HEAD, reason="UNRELATED_INCIDENT"))
    state.revision += 1
    runtime.store.save(state, revision)
    before = runtime.store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_OTHER_BLOCKERS"):
        command(recovery, tmp_path)
    assert runtime.store.load() == before


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("blocked_reasons", [], "SENSITIVE_DIFF_BLOCKER_MISSING"),
        (
            "blocked_reasons",
            ["SENSITIVE_DIFF:unknown"],
            "SENSITIVE_DIFF_ESCALATION_EVIDENCE_REQUIRED",
        ),
        ("changed_areas", ["real_money"], "SENSITIVE_DIFF_REVALIDATION_OTHER_BLOCKERS"),
        ("pr_number", None, "PR_IDENTITY_MISMATCH"),
        ("head_sha", None, "SENSITIVE_DIFF_REVALIDATION_STALE_HEAD"),
    ],
)
def test_ambiguous_or_missing_durable_evidence_rejected(recovery, tmp_path, field, value, reason):
    persist(recovery, lambda item: setattr(item, field, value))
    before = recovery[0].store.load()
    with pytest.raises(GovernanceError, match=reason):
        command(recovery, tmp_path)
    assert recovery[0].store.load() == before


def test_budget_counter_and_existing_controls_remain_intact(recovery, tmp_path):
    persist(recovery, lambda item: setattr(item.budget, "budget_limit_hits", 1))
    before = recovery[0].store.load()
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_OTHER_BLOCKERS"):
        command(recovery, tmp_path)
    assert recovery[0].store.load() == before


def test_raw_event_metadata_cannot_substitute_for_repository_evidence(recovery):
    runtime, _, pr, work = recovery
    state, _ = runtime.store.load()
    event = runtime.event(
        work, EventType.SENSITIVE_DIFF_REVALIDATED, HEAD, changed_paths="[]", sensitive_areas="[]"
    )
    event.actor = "chairman"
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_EVIDENCE_REQUIRED"):
        apply_event(state, event, runtime.policy, pr=pr)
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_STILL_PRESENT"):
        apply_event(
            state,
            event,
            runtime.policy,
            pr=pr,
            revalidated_paths=["docs/project/TECHNICAL_DEBT.md"],
        )
    with pytest.raises(GovernanceError, match="SENSITIVE_DIFF_REVALIDATION_STALE_HEAD"):
        apply_event(
            state,
            event.model_copy(update={"input_sha": OLD_HEAD}),
            runtime.policy,
            pr=pr,
            revalidated_paths=[],
        )


def test_repository_failure_and_concurrent_state_write_fail_closed(recovery, tmp_path):
    runtime, github, _, _ = recovery
    before = runtime.store.load()
    github.changed_paths.side_effect = GovernanceError("GITHUB_UNAVAILABLE")
    with pytest.raises(GovernanceError, match="GITHUB_UNAVAILABLE"):
        command(recovery, tmp_path)
    assert runtime.store.load() == before

    def race(number):
        persist(recovery, lambda item: item.blocked_reasons.append("NEW_INCIDENT"))
        return []

    github.changed_paths.side_effect = race
    with pytest.raises(GovernanceError, match="STATE_CONFLICT"):
        command(recovery, tmp_path)
    current = runtime.store.load()[0]
    assert current.work_items[recovery[3]].blocked_reasons == [SENSITIVE, "NEW_INCIDENT"]
    assert current.work_items[recovery[3]].chairman_required
    assert all(e.event_type != EventType.SENSITIVE_DIFF_REVALIDATED for e in current.events)


def test_github_diff_includes_renamed_source_and_all_pages():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.url.path.endswith("/pulls/19/files")
        entries = (
            [{"filename": f"module-{i}.py"} for i in range(100)]
            if request.url.params["page"] == "1"
            else [
                {
                    "filename": "docs/renamed.md",
                    "previous_filename": "docs/project/TECHNICAL_DEBT.md",
                    "status": "renamed",
                }
            ]
        )
        return httpx.Response(200, json=entries)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        paths = GitHubClient(transport, "steemchen-creator/AIC").changed_paths(19)
    assert len(calls) == 2
    assert "docs/project/TECHNICAL_DEBT.md" in paths and "docs/renamed.md" in paths
    assert len(paths) == 102


def test_github_diff_ceiling_fails_closed():
    github = GitHubClient(Mock(), "steemchen-creator/AIC")
    github.pages = Mock(return_value=[{"filename": "module.py"}] * 3000)
    with pytest.raises(GovernanceError, match="GITHUB_DIFF_INCOMPLETE"):
        github.changed_paths(19)
