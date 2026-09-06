import hashlib
from datetime import UTC, datetime

import pytest

from aic_dev_governance.artifacts import MEMORY_PATHS, ArtifactReader, build_context
from aic_dev_governance.bridges import ManualTriggerAdapter
from aic_dev_governance.models import (
    ArchitectureResult,
    EventType,
    GovernanceError,
    ReviewStatus,
    Stage,
)
from aic_dev_governance.orchestrator import Orchestrator
from aic_dev_governance.store import LocalFileStateStore


class Repository:
    def __init__(self, pr, ci):
        self.pr, self.checks = pr.model_copy(deep=True), ci.model_copy(deep=True)
        self.merges = []
        self.deleted = False
        self.merge_error = None
        self.read_error = None
        self.drift = False
        self.tree_mismatch = False
        self.cleanup_error = False
        self.ready_calls = 0

    def pull_request(self, number):
        if self.read_error:
            raise GovernanceError(self.read_error)
        assert number == self.pr.number
        return self.pr.model_copy(deep=True)

    def ci(self, pr, policy):
        return self.checks

    def changed_paths(self, number):
        return []

    def merge(self, number, expected_head_sha):
        self.merges.append((number, expected_head_sha))
        if self.drift:
            self.pr.head_sha = "d" * 40
            self.checks.head_sha = self.pr.head_sha
            self.checks.status = "PENDING"
        if self.merge_error:
            raise GovernanceError(self.merge_error)
        assert expected_head_sha == self.pr.head_sha
        self.pr.state, self.pr.merge_commit = "MERGED", "c" * 40
        return "c" * 40

    def tree(self, sha):
        return "e" * 40 if self.tree_mismatch and sha == "c" * 40 else "f" * 40

    def ref(self, branch):
        if branch == "main":
            return "c" * 40
        return None if self.deleted else self.pr.head_sha

    def delete_branch(self, branch, expected_sha):
        if self.cleanup_error:
            raise GovernanceError("BRANCH_DELETION_FAILED")
        assert branch == self.pr.branch and expected_sha == self.pr.head_sha
        self.deleted = True

    def mark_ready(self, number, expected_head_sha):
        self.ready_calls += 1
        assert number == self.pr.number and expected_head_sha == self.pr.head_sha
        self.pr.draft = False

    def mark_draft(self, number, expected_head_sha):
        assert expected_head_sha == self.pr.head_sha
        self.pr.draft = True


class Workspace:
    def __init__(self):
        self.calls = []

    def closeout(self, branch, head, merge_commit, main):
        self.calls.append((branch, head, merge_commit, main))


class Trigger:
    result = None
    usage = {}

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def trigger(self, task, context, content):
        self.calls.append(task)
        if self.error:
            raise GovernanceError(self.error)
        return "https://github.com/task/1"

    def trigger_engineering(self, task, pr_number):
        return self.trigger(task, None, None)


@pytest.fixture
def runtime(tmp_path, state, item, pr, policy):
    item.artifact_sha256 = hashlib.sha256(b"# Approved fixture\n").hexdigest()
    repo = Repository(pr, item.ci)
    store = LocalFileStateStore(tmp_path / "state")
    runtime = Orchestrator(store, repo, policy, "bot", now=lambda: datetime(2026, 9, 7, tzinfo=UTC))
    state.events = [runtime.event(item.work_item_id, EventType.TASK_RESERVED)]
    state.revision = 1
    store.save(state, None)
    return runtime, repo


def save(runtime, mutate):
    state, revision = runtime.store.load()
    mutate(state.work_items["SPEC-TEST"])
    state.events.append(runtime.event("SPEC-TEST", EventType.TASK_RESERVED))
    state.revision += 1
    runtime.store.save(state, revision)


def context(tmp_path, item):
    paths = set(MEMORY_PATHS) | {item.artifact_path, item.review_artifact}
    for path in paths:
        target = tmp_path / "repo" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Approved fixture\n", encoding="utf-8")
    item.artifact_sha256 = hashlib.sha256(b"# Approved fixture\n").hexdigest()
    reader = ArtifactReader(tmp_path / "repo", paths)
    manifest = build_context(reader, item, [], [], tests_summary="passed", coverage_summary="100%")
    return reader, manifest


def test_e2e_happy_path_merge_expected_sha_closeout_and_restart(runtime):
    runtime, repo = runtime
    workspace = Workspace()
    merged = runtime.merge("SPEC-TEST")
    assert repo.merges == [(12, "a" * 40)]
    assert merged.work_items["SPEC-TEST"].status == Stage.MERGED
    # New orchestrator object with no chat context recovers exact review/HEAD/CI from durable state.
    recovered = Orchestrator(runtime.store, repo, runtime.policy, "bot", now=runtime.now)
    closed = recovered.closeout("SPEC-TEST", workspace)
    assert closed.work_items["SPEC-TEST"].status == Stage.CLOSED
    assert closed.work_items["SPEC-TEST"].next_spec_requested
    assert repo.deleted and len(workspace.calls) == 1
    assert recovered.closeout("SPEC-TEST", workspace) == closed
    assert len(workspace.calls) == 1


def test_e2e_full_spec_draft_review_merge(runtime, tmp_path):
    runtime, repo = runtime

    def reset(item):
        item.status, item.architecture_status = Stage.PLANNED, ReviewStatus.NOT_REVIEWED
        item.approved_head_sha, item.pr_number = None, None

    save(runtime, reset)
    for kind, actor in [
        (EventType.SPEC_PUBLISHED, "architect"),
        (EventType.CODEX_STARTED, "engineer"),
        (EventType.IMPLEMENTATION_COMPLETED, "engineer"),
    ]:
        event = runtime.event("SPEC-TEST", kind)
        event.actor = actor
        runtime.handle(event)
    repo.pr.draft = True
    runtime.handle(
        runtime.event(
            "SPEC-TEST", EventType.PR_CREATED, repo.pr.head_sha, review_artifact="REVIEW-TEST.md"
        ),
        pr=repo.pr,
    )
    state = runtime.reconcile("SPEC-TEST")
    reader, manifest = context(tmp_path, state.work_items["SPEC-TEST"])
    trigger = Trigger()
    runtime.dispatch(
        "SPEC-TEST", "ARCHITECTURE_REVIEW", architecture=trigger, reader=reader, manifest=manifest
    )
    event = runtime.event("SPEC-TEST", EventType.ARCH_REVIEW_STARTED, repo.pr.head_sha)
    event.actor = "architect"
    runtime.handle(event)
    review = ArchitectureResult(
        work_item="SPEC-TEST",
        review_id="ARCH-E2E",
        result="FINAL_APPROVED",
        reviewed_head_sha=repo.pr.head_sha,
        blocking_items=[],
        non_blocking_items=[],
        reviewed_at=runtime.now(),
        reviewer_role="CHIEF_INVESTMENT_ARCHITECT",
    )
    event = runtime.event("SPEC-TEST", EventType.ARCH_FINAL_APPROVED, repo.pr.head_sha)
    event.actor = "architect"
    runtime.handle(event, review=review)
    runtime.ready("SPEC-TEST")
    assert not repo.pr.draft and repo.ready_calls == 1
    assert runtime.merge("SPEC-TEST").work_items["SPEC-TEST"].status == Stage.MERGED


def test_e2e_old_sha_cannot_approve_fix_head(runtime):
    runtime, repo = runtime
    repo.pr.head_sha = "b" * 40
    repo.checks.head_sha, repo.checks.status = repo.pr.head_sha, "PENDING"
    state = runtime.reconcile("SPEC-TEST")
    item = state.work_items["SPEC-TEST"]
    assert item.head_sha == "b" * 40 and item.approved_head_sha is None
    assert item.architecture_status == ReviewStatus.REVIEW_REQUIRED
    with pytest.raises(GovernanceError):
        runtime.merge("SPEC-TEST")
    assert not repo.merges


def test_e2e_premature_merge_blocks_closeout_and_next_spec(runtime):
    runtime, repo = runtime
    save(
        runtime, lambda item: setattr(item, "architecture_status", ReviewStatus.APPROVED_CANDIDATE)
    )
    repo.pr.state, repo.pr.merge_commit = "MERGED", "c" * 40
    state = runtime.reconcile("SPEC-TEST")
    item = state.work_items["SPEC-TEST"]
    assert state.paused and item.governance_exception and item.status == Stage.BLOCKED
    assert "PR_MERGED_EARLY" in item.blocked_reasons and not item.next_spec_requested
    with pytest.raises(GovernanceError):
        runtime.closeout("SPEC-TEST", Workspace())
    assert not repo.deleted


@pytest.mark.parametrize("reason", ["GITHUB_UNAVAILABLE", "GITHUB_HTTP_403"])
def test_remote_failure_blocks(runtime, reason):
    runtime, repo = runtime
    repo.read_error = reason
    state = runtime.reconcile("SPEC-TEST")
    assert state.work_items["SPEC-TEST"].blocked_reasons == [reason]


def test_closed_pr_and_missing_pr(runtime):
    runtime, repo = runtime
    repo.pr.state = "CLOSED"
    assert (
        "PR_CLOSED_UNEXPECTEDLY"
        in runtime.reconcile("SPEC-TEST").work_items["SPEC-TEST"].blocked_reasons
    )
    save(runtime, lambda item: setattr(item, "pr_number", None))
    with pytest.raises(GovernanceError, match="PR_MISSING"):
        runtime.reconcile("SPEC-TEST")


@pytest.mark.parametrize("drift", [False, True])
def test_merge_failure_and_head_drift(runtime, drift):
    runtime, repo = runtime
    repo.merge_error, repo.drift = "GITHUB_HTTP_409", drift
    state = runtime.merge("SPEC-TEST")
    item = state.work_items["SPEC-TEST"]
    assert item.status == (Stage.REVIEW_REQUIRED if drift else Stage.BLOCKED)
    if drift:
        assert item.approved_head_sha is None


def test_dry_run_and_bootstrap_never_merge(runtime):
    runtime, repo = runtime
    runtime.policy.mode = "DRY_RUN"
    assert runtime.merge("SPEC-TEST").work_items["SPEC-TEST"].status == Stage.MERGE_ELIGIBLE
    assert not repo.merges
    runtime.policy.mode = "MANUAL"
    with pytest.raises(GovernanceError, match="AUTO_MERGE_DISABLED"):
        runtime.merge("SPEC-TEST")


@pytest.mark.parametrize("failure", ["tree", "cleanup", "notmerged"])
def test_closeout_fail_closed(runtime, failure):
    runtime, repo = runtime
    if failure == "notmerged":
        with pytest.raises(GovernanceError, match="CLOSEOUT_NOT_ALLOWED"):
            runtime.closeout("SPEC-TEST", Workspace())
        return
    runtime.merge("SPEC-TEST")
    repo.tree_mismatch = failure == "tree"
    repo.cleanup_error = failure == "cleanup"
    state = runtime.closeout("SPEC-TEST", Workspace())
    assert state.work_items["SPEC-TEST"].status == Stage.BLOCKED
    assert not state.work_items["SPEC-TEST"].next_spec_requested


def test_ready_disabled_and_approval_missing(runtime):
    runtime, repo = runtime
    runtime.policy.auto_ready = False
    with pytest.raises(GovernanceError, match="AUTOMATIC_READY_DISABLED"):
        runtime.ready("SPEC-TEST")
    runtime.policy.auto_ready = True
    save(runtime, lambda item: setattr(item, "approved_head_sha", None))
    with pytest.raises(GovernanceError, match="APPROVAL_STALE"):
        runtime.ready("SPEC-TEST")
    assert repo.ready_calls == 0


def test_budget_limit_bridge_unavailable_and_no_duplicate_delivery(runtime, tmp_path):
    runtime, repo = runtime
    save(runtime, lambda item: setattr(item, "status", Stage.REVIEW_REQUIRED))
    state, _ = runtime.store.load()
    reader, manifest = context(tmp_path, state.work_items["SPEC-TEST"])
    waiting = runtime.dispatch(
        "SPEC-TEST",
        "ARCHITECTURE_REVIEW",
        architecture=ManualTriggerAdapter(),
        reader=reader,
        manifest=manifest,
    )
    assert waiting.work_items["SPEC-TEST"].status == Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE
    trigger = Trigger()
    duplicate = runtime.dispatch(
        "SPEC-TEST", "ARCHITECTURE_REVIEW", architecture=trigger, reader=reader, manifest=manifest
    )
    assert duplicate == waiting and not trigger.calls


def test_dispatch_success_failed_and_budget_escalation(runtime, tmp_path):
    runtime, repo = runtime
    save(runtime, lambda item: setattr(item, "status", Stage.REVIEW_REQUIRED))
    state, _ = runtime.store.load()
    reader, manifest = context(tmp_path, state.work_items["SPEC-TEST"])
    save(runtime, lambda item: setattr(item.budget, "review_loops", 3))
    trigger = Trigger()
    state = runtime.dispatch(
        "SPEC-TEST", "ARCHITECTURE_REVIEW", architecture=trigger, reader=reader, manifest=manifest
    )
    assert state.work_items["SPEC-TEST"].status == Stage.CHAIRMAN_DECISION_REQUIRED
    assert not trigger.calls


def test_engineering_task_and_failed_task(runtime, tmp_path):
    runtime, repo = runtime
    save(runtime, lambda item: setattr(item, "status", Stage.SPEC_READY))
    state, _ = runtime.store.load()
    reader, _ = context(tmp_path, state.work_items["SPEC-TEST"])
    trigger = Trigger(error="CODEX_TASK_FAILED")
    state = runtime.dispatch("SPEC-TEST", "ENGINEERING", engineering=trigger, reader=reader)
    assert state.work_items["SPEC-TEST"].status == Stage.BLOCKED
    assert len(trigger.calls) == 1
    assert list(state.tasks.values())[0].status == "FAILED"


def test_task_preconditions_and_kill_switch(runtime):
    runtime, repo = runtime
    for kind, reason in [
        ("ENGINEERING", "ENGINEERING_TASK_NOT_READY"),
        ("ARCHITECTURE_REVIEW", "ARCHITECTURE_TASK_NOT_READY"),
        ("WRONG", "TASK_KIND_INVALID"),
    ]:
        with pytest.raises(GovernanceError, match=reason):
            runtime.dispatch("SPEC-TEST", kind)
    runtime.policy.pipeline_enabled = False
    with pytest.raises(GovernanceError, match="PIPELINE_DISABLED_PAUSED_OR_BLOCKED"):
        runtime.dispatch("SPEC-TEST", "ENGINEERING")


def test_register_authority_hash_previous_and_no_self_approval(runtime, tmp_path):
    runtime, repo = runtime
    save(runtime, lambda item: setattr(item, "status", Stage.CLOSED))
    state, _ = runtime.store.load()
    item = state.work_items["SPEC-TEST"].model_copy(deep=True)
    item.work_item_id, item.previous_work_item, item.status = "NEW-SPEC", "SPEC-TEST", Stage.PLANNED
    item.approved_head_sha, item.merge_eligible = None, False
    reader, _ = context(tmp_path, item)
    from aic_dev_governance.models import CI

    item.architecture_status, item.pr_number, item.head_sha = ReviewStatus.NOT_REVIEWED, None, None
    item.ci = CI()
    with pytest.raises(GovernanceError, match="ACTOR_NOT_AUTHORIZED"):
        runtime.register(item, reader, "engineer")
    item.artifact_sha256 = "b" * 64
    with pytest.raises(GovernanceError, match="APPROVED_SPEC_HASH_MISMATCH"):
        runtime.register(item, reader, "chairman")
    item.artifact_sha256 = hashlib.sha256(b"# Approved fixture\n").hexdigest()
    state = runtime.register(item, reader, "chairman")
    assert state.current_work_item == "NEW-SPEC"
    assert state.work_items["NEW-SPEC"].status == Stage.PLANNED
    with pytest.raises(GovernanceError, match="WORK_ITEM_ALREADY_EXISTS"):
        runtime.register(item, reader, "chairman")


def test_api_result_publishes_fix_then_new_head_requires_new_final_review(runtime):
    from aic_dev_governance.runner import publish_architecture_result

    runtime, repo = runtime
    runtime.policy.architecture_bridge_actor = "architect"
    save(runtime, lambda item: setattr(item, "status", Stage.REVIEW_REQUIRED))
    repo.pr.draft = True
    result = ArchitectureResult(
        work_item="SPEC-TEST",
        review_id="ARCH-FIX",
        result="CHANGES_REQUIRED",
        reviewed_head_sha="a" * 40,
        blocking_items=["Fix state race"],
        non_blocking_items=[],
        reviewed_at=runtime.now(),
        reviewer_role="CHIEF_INVESTMENT_ARCHITECT",
    )
    state = publish_architecture_result(runtime, repo, "SPEC-TEST", result)
    item = state.work_items["SPEC-TEST"]
    assert item.status == Stage.FIX_READY and item.unresolved_fix in state.artifacts
    assert "Fix state race" in state.artifacts[item.unresolved_fix]
    assert publish_architecture_result(runtime, repo, "SPEC-TEST", result) == state
    started = runtime.event("SPEC-TEST", EventType.CODEX_STARTED)
    started.actor = "engineer"
    runtime.handle(started)
    repo.pr.head_sha = "b" * 40
    repo.checks.head_sha = repo.pr.head_sha
    for check in repo.checks.checks:
        check.head_sha = repo.pr.head_sha
    runtime.reconcile("SPEC-TEST")
    fixed = runtime.event("SPEC-TEST", EventType.FIX_IMPLEMENTED, repo.pr.head_sha)
    fixed.actor = "engineer"
    runtime.handle(fixed)
    with pytest.raises(GovernanceError, match="REVIEW_SHA_OR_IDENTITY_MISMATCH"):
        publish_architecture_result(runtime, repo, "SPEC-TEST", result)
    approved = result.model_copy(
        update={
            "review_id": "ARCH-B",
            "result": "FINAL_APPROVED",
            "reviewed_head_sha": repo.pr.head_sha,
            "blocking_items": [],
        }
    )
    state = publish_architecture_result(runtime, repo, "SPEC-TEST", approved)
    assert state.work_items["SPEC-TEST"].approved_head_sha == "b" * 40
    runtime.ready("SPEC-TEST")
    runtime.merge("SPEC-TEST")
    assert repo.merges == [(12, "b" * 40)]


def test_next_spec_proposal_requires_delegated_execution_and_preserves_memory(runtime):
    from aic_dev_governance.models import SpecificationResult
    from aic_dev_governance.runner import publish_architecture_result

    runtime, repo = runtime
    runtime.policy.architecture_bridge_actor = "architect"
    save(runtime, lambda item: setattr(item, "status", Stage.CLOSED))
    outcome = SpecificationResult(
        work_item_id="SPEC-NEXT",
        parent_work_item="SPEC-TEST",
        title="Next test work",
        scope="scope",
        non_scope="non scope",
        requirements=["requirement"],
        tests=["test"],
        quality_gates=["CI"],
        review_output_requirement="REVIEW",
        stop_condition="wait",
        markdown="# Proposed test SPEC\n" + "Scope, requirements and tests.\n" * 5,
    )
    state = publish_architecture_result(runtime, repo, "SPEC-TEST", outcome)
    assert "SPEC-NEXT" not in state.work_items
    runtime.policy.standard_work_execution_authorization = "Chairman-delegated-normal-engineering"
    state = publish_architecture_result(runtime, repo, "SPEC-TEST", outcome)
    assert state.work_items["SPEC-NEXT"].status == Stage.SPEC_READY
    assert state.work_items["SPEC-NEXT"].approved_head_sha is None
    assert publish_architecture_result(runtime, repo, "SPEC-TEST", outcome) == state
    altered = outcome.model_copy(update={"title": "changed"})
    with pytest.raises(GovernanceError, match="SPEC_ARTIFACT_ALREADY_EXISTS"):
        publish_architecture_result(runtime, repo, "SPEC-TEST", altered)


def test_real_bridge_result_durable_ack_and_safe_wait_resume(runtime, tmp_path):
    runtime, repo = runtime
    save(runtime, lambda item: setattr(item, "status", Stage.REVIEW_REQUIRED))
    state, _ = runtime.store.load()
    reader, manifest = context(tmp_path, state.work_items["SPEC-TEST"])
    runtime.dispatch(
        "SPEC-TEST",
        "ARCHITECTURE_REVIEW",
        architecture=ManualTriggerAdapter(),
        reader=reader,
        manifest=manifest,
    )
    runtime.policy.bridge_authorized = True
    runtime.policy.bridge_mode = "OPENAI_API_BRIDGE"
    trigger = Trigger()
    trigger.usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    trigger.result = ArchitectureResult(
        work_item="SPEC-TEST",
        review_id="ARCH-DURABLE",
        result="FINAL_APPROVED",
        reviewed_head_sha="a" * 40,
        blocking_items=[],
        non_blocking_items=[],
        reviewed_at=runtime.now(),
        reviewer_role="CHIEF_INVESTMENT_ARCHITECT",
    )
    state = runtime.dispatch(
        "SPEC-TEST", "ARCHITECTURE_REVIEW", architecture=trigger, reader=reader, manifest=manifest
    )
    assert len(trigger.calls) == 1
    assert any(path.startswith("results/") for path in state.artifacts)
    assert state.work_items["SPEC-TEST"].budget.architecture_calls_used == 1
    from aic_dev_governance.observability import metrics

    assert metrics(state, "SPEC-TEST")["total_tokens"] == 120
    assert any('"status": "DELIVERED"' in value for value in state.artifacts.values())


def test_two_orchestrators_only_one_reserves_and_delivers(runtime, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    runtime, repo = runtime
    save(runtime, lambda item: setattr(item, "status", Stage.REVIEW_REQUIRED))
    state, _ = runtime.store.load()
    reader, manifest = context(tmp_path, state.work_items["SPEC-TEST"])
    backing = runtime.store
    barrier = Barrier(2)

    class ConcurrentStore:
        def load(self):
            snapshot = backing.load()
            barrier.wait(timeout=5)
            return snapshot

        def save(self, state, expected_revision):
            return backing.save(state, expected_revision)

    trigger = Trigger()

    def execute():
        concurrent = Orchestrator(ConcurrentStore(), repo, runtime.policy, "bot", now=runtime.now)
        try:
            concurrent.dispatch(
                "SPEC-TEST",
                "ARCHITECTURE_REVIEW",
                architecture=trigger,
                reader=reader,
                manifest=manifest,
            )
            return "delivered"
        except GovernanceError as error:
            return error.reason

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: execute(), range(2)))
    assert sorted(results) == ["STATE_CONFLICT", "delivered"]
    assert len(trigger.calls) == 1
    assert len(backing.load()[0].tasks) == 1


def test_e2e_repeated_fix_reviews_hit_loop_limit_without_another_model_call(runtime, tmp_path):
    runtime, repo = runtime
    trigger = Trigger()
    for index in range(4):

        def next_head(item):
            item.status = Stage.REVIEW_REQUIRED
            item.head_sha = str(index + 1) * 40

        save(runtime, next_head)
        state, _ = runtime.store.load()
        reader, manifest = context(tmp_path, state.work_items["SPEC-TEST"])
        state = runtime.dispatch(
            "SPEC-TEST",
            "ARCHITECTURE_REVIEW",
            architecture=trigger,
            reader=reader,
            manifest=manifest,
        )
    assert len(trigger.calls) == 3
    assert state.work_items["SPEC-TEST"].status == Stage.CHAIRMAN_DECISION_REQUIRED
    assert state.work_items["SPEC-TEST"].blocked_reasons == ["REVIEW_LOOP_LIMIT"]
