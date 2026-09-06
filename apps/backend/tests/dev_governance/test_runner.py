import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest

from aic_dev_governance.models import (
    ArchitectureResult,
    Event,
    EventType,
    GovernanceError,
    Stage,
    State,
)
from aic_dev_governance.runner import dispatch_command, initialize_state, run, spec_hash, tick


@pytest.fixture
def service(state, pr, item, policy):
    orchestrator = Mock()
    orchestrator.policy = policy
    orchestrator.store.load.return_value = (state, "rev")
    orchestrator.now.return_value = datetime(2026, 9, 7, tzinfo=UTC)

    def event(work, kind, head=None, **metadata):
        return Event(
            event_id="event1",
            event_type=kind,
            timestamp=orchestrator.now(),
            work_item_id=work,
            actor="bot",
            input_sha=head,
            metadata=metadata,
        )

    orchestrator.event.side_effect = event
    for name in ("handle", "register", "ready", "merge", "closeout", "dispatch", "reconcile"):
        getattr(orchestrator, name).return_value = state
    github = Mock()
    github.pull_request.return_value = pr
    github.ref.return_value = "a" * 40
    github.file.return_value = "# Artifact\n"
    github.pages.return_value = [
        {"filename": "module.py", "status": "modified"},
        {"filename": "removed.py", "status": "removed"},
    ]
    item.artifact_sha256 = hashlib.sha256(b"# Artifact\n").hexdigest()
    github.ci.return_value = item.ci
    return orchestrator, github


def test_command_register_review_attach_and_memory(service, item, tmp_path):
    orchestrator, github = service
    dispatch_command(
        orchestrator,
        github,
        tmp_path,
        "chairman",
        "register",
        {"work_item": item.model_dump(mode="json"), "approved_ref": "a" * 40},
    )
    orchestrator.register.assert_called_once()
    review = ArchitectureResult(
        work_item=item.work_item_id,
        review_id="ARCH-1",
        result="FINAL_APPROVED",
        reviewed_head_sha=item.head_sha,
        blocking_items=[],
        non_blocking_items=[],
        reviewed_at=orchestrator.now(),
        reviewer_role="CHIEF_INVESTMENT_ARCHITECT",
    )
    dispatch_command(
        orchestrator,
        github,
        tmp_path,
        "architect",
        "review",
        {"review": review.model_dump(mode="json")},
    )
    assert orchestrator.handle.call_args[0][0].actor == "architect"
    dispatch_command(
        orchestrator,
        github,
        tmp_path,
        "engineer",
        "attach-pr",
        {"pr_number": 12, "review_artifact": "REVIEW-TEST.md"},
    )
    assert orchestrator.handle.call_args[0][0].event_type == EventType.PR_CREATED
    dispatch_command(
        orchestrator,
        github,
        tmp_path,
        "architect",
        "memory-update",
        {"reason": "major_governance_incident"},
    )
    assert orchestrator.handle.call_args[0][0].event_type == EventType.MEMORY_UPDATE_REQUIRED
    with pytest.raises(GovernanceError, match="MEMORY_TRIGGER_INVALID"):
        dispatch_command(
            orchestrator, github, tmp_path, "architect", "memory-update", {"reason": "bugfix"}
        )


def test_authenticated_event_operations_and_forbidden_commands(service, tmp_path):
    orchestrator, github = service
    for command in ("ready", "merge", "closeout"):
        dispatch_command(orchestrator, github, tmp_path, "chairman", command, {})
        getattr(orchestrator, command).assert_called_once()
    dispatch_command(
        orchestrator,
        github,
        tmp_path,
        "architect",
        "event",
        {"event_type": "FIX_PUBLISHED", "metadata": {"fix_path": "FIX-1.md"}},
    )
    github.ref.return_value = None
    with pytest.raises(GovernanceError, match="MAIN_MISSING"):
        dispatch_command(
            orchestrator,
            github,
            tmp_path,
            "architect",
            "event",
            {"event_type": "FIX_PUBLISHED", "metadata": {"fix_path": "FIX-1.md"}},
        )
    dispatch_command(
        orchestrator, github, tmp_path, "engineer", "event", {"event_type": "CODEX_STARTED"}
    )
    with pytest.raises(GovernanceError, match="EVENT_COMMAND_NOT_ALLOWED"):
        dispatch_command(
            orchestrator,
            github,
            tmp_path,
            "engineer",
            "event",
            {"event_type": "ARCH_FINAL_APPROVED"},
        )
    with pytest.raises(GovernanceError, match="COMMAND_NOT_ALLOWLISTED"):
        dispatch_command(orchestrator, github, tmp_path, "chairman", "force-merge", {})
    with pytest.raises(GovernanceError, match="WORK_ITEM_UNKNOWN"):
        dispatch_command(orchestrator, github, tmp_path, "chairman", "event", {"work_item_id": "X"})


def test_initialize_after_manual_closeout_only(service, pr, item, state, tmp_path):
    orchestrator, github = service
    payload = {"pr_number": 12, "architecture_closeout_reference": "External Chief signed review"}
    with pytest.raises(GovernanceError, match="STATE_ALREADY_INITIALIZED"):
        initialize_state(orchestrator, github, "chairman", payload)
    orchestrator.store.load.return_value = (State(), None)
    with pytest.raises(GovernanceError, match="EXTERNAL_ARCHITECTURE_CLOSEOUT_REFERENCE_REQUIRED"):
        initialize_state(orchestrator, github, "chairman", {"pr_number": 12})
    with pytest.raises(GovernanceError, match="BOOTSTRAP_CLOSEOUT_NOT_COMPLETE"):
        initialize_state(orchestrator, github, "chairman", payload)
    pr.state, pr.merge_commit = "MERGED", "c" * 40
    pr.branch = "feature/dev-gov-001-autonomous-development-pipeline"
    github.ref.side_effect = lambda branch: "c" * 40 if branch == "main" else None
    github.tree.side_effect = ["tree1", "tree2"]
    with pytest.raises(GovernanceError, match="MERGE_TREE_REVIEW_REQUIRED"):
        initialize_state(orchestrator, github, "chairman", payload)
    github.tree.side_effect = None
    github.tree.return_value = "tree"
    github.ref.side_effect = lambda branch: "b" * 40 if branch == "main" else None
    with pytest.raises(GovernanceError, match="BOOTSTRAP_MAIN_MISMATCH"):
        initialize_state(orchestrator, github, "chairman", payload)
    github.ref.side_effect = lambda branch: "c" * 40 if branch == "main" else None
    item.ci.status = "PENDING"
    with pytest.raises(GovernanceError, match="BOOTSTRAP_CI_NOT_PASSED"):
        initialize_state(orchestrator, github, "chairman", payload)
    item.ci.status = "PASSED"
    github.file.side_effect = lambda path, ref: (
        json.dumps({"spec_path": item.artifact_path, "review_path": item.review_artifact})
        if path.endswith("work-item.json")
        else "# SPEC"
    )
    imported = dispatch_command(orchestrator, github, tmp_path, "chairman", "initialize", payload)
    assert imported.work_items["DEV-GOV-001"].status == Stage.CLOSED
    assert not imported.work_items["DEV-GOV-001"].next_spec_requested
    orchestrator.store.save.assert_called_once()


def test_tick_empty_blocked_bootstrap_and_nontriggering_stages(service, state, item):
    orchestrator, github = service
    state.current_work_item = None
    assert tick(orchestrator, github, httpx.Client()) == state
    state.current_work_item = item.work_item_id
    for stage in (Stage.BLOCKED, Stage.CHAIRMAN_DECISION_REQUIRED, Stage.IMPLEMENTING):
        item.status = stage
        assert tick(orchestrator, github, httpx.Client()) == state
    item.status = Stage.REVIEW_REQUIRED
    orchestrator.policy.pipeline_enabled = False
    assert tick(orchestrator, github, httpx.Client()) == state
    orchestrator.policy.pipeline_enabled = True
    item.work_item_id = "DEV-GOV-001"
    state.work_items = {item.work_item_id: item}
    state.current_work_item = item.work_item_id
    assert tick(orchestrator, github, httpx.Client()) == state
    orchestrator.dispatch.assert_not_called()


def test_tick_engineering_review_closed_and_missing_evidence(service, item):
    orchestrator, github = service
    for stage in (
        Stage.SPEC_READY,
        Stage.FIX_READY,
        Stage.REVIEW_REQUIRED,
        Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE,
    ):
        item.status = stage
        item.unresolved_fix = "FIX-1.md" if stage == Stage.FIX_READY else None
        tick(orchestrator, github, httpx.Client())
    assert orchestrator.dispatch.call_count == 4
    item.status, item.next_spec_requested = Stage.CLOSED, False
    tick(orchestrator, github, httpx.Client())
    assert orchestrator.dispatch.call_count == 4
    item.next_spec_requested = True
    tick(orchestrator, github, httpx.Client())
    assert orchestrator.dispatch.call_args[0][1] == "NEXT_SPEC"
    item.status, item.review_artifact = Stage.REVIEW_REQUIRED, None
    with pytest.raises(GovernanceError, match="REVIEW_ARTIFACT_MISSING"):
        tick(orchestrator, github, httpx.Client())
    item.head_sha = None
    github.ref.return_value = None
    with pytest.raises(GovernanceError, match="MAIN_MISSING"):
        tick(orchestrator, github, httpx.Client())


def test_tick_auto_ready_manual_gate_and_closeout(service, item, tmp_path):
    orchestrator, github = service
    item.status = Stage.FINAL_APPROVED
    orchestrator.merge.side_effect = GovernanceError("AUTO_MERGE_DISABLED")
    tick(orchestrator, github, httpx.Client(), tmp_path)
    orchestrator.ready.assert_called_once()
    orchestrator.policy.auto_ready = False
    orchestrator.merge.side_effect = GovernanceError("OTHER_FAILURE")
    with pytest.raises(GovernanceError, match="OTHER_FAILURE"):
        tick(orchestrator, github, httpx.Client(), tmp_path)
    item.status = Stage.MERGED
    tick(orchestrator, github, httpx.Client(), tmp_path)
    orchestrator.closeout.assert_called_once()


def test_run_protected_dispatch_then_bounded_tick(service, tmp_path, monkeypatch, policy):
    import aic_dev_governance.runner as module

    orchestrator, github = service
    config = tmp_path / "configs/dev-governance.json"
    config.parent.mkdir()
    config.write_text(policy.model_dump_json())
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "inputs": {
                    "command": "event",
                    "payload": json.dumps({"event_type": "PAUSE_PIPELINE"}),
                }
            }
        )
    )
    monkeypatch.setenv("GH_TOKEN", "placeholder-test-token")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_ACTOR", "chairman")
    monkeypatch.setattr(module, "GitHubClient", lambda *args, **kwargs: github)
    monkeypatch.setattr(module, "GitHubStateBranchStore", lambda *args: orchestrator.store)
    monkeypatch.setattr(module, "Orchestrator", lambda *args: orchestrator)
    monkeypatch.setattr(module, "tick", Mock(return_value=orchestrator.store.load()[0]))
    assert "AIC Development Status" in run(tmp_path)
    assert orchestrator.handle.call_args[0][0].actor == "chairman"
    event.write_text("{}")
    run(tmp_path)
    assert spec_hash(config) == hashlib.sha256(config.read_text().encode()).hexdigest()
