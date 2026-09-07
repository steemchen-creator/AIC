import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from aic_dev_governance.artifacts import MEMORY_PATHS, ArtifactReader
from aic_dev_governance.ci_gate import check_governance
from aic_dev_governance.deployment import (
    materialize_effective_policy,
    policy_fingerprint,
    validate_deployment_policy,
)
from aic_dev_governance.models import (
    CI,
    DeploymentPolicyConfig,
    DeploymentSetup,
    Event,
    EventType,
    GovernanceError,
    Policy,
    PullRequest,
    ReviewStatus,
    Role,
    Stage,
    State,
    WorkItem,
)
from aic_dev_governance.orchestrator import Orchestrator
from aic_dev_governance.runner import (
    complete_deployment_setup,
    dispatch_command,
    initialize_state,
    run_setup,
)
from aic_dev_governance.store import LocalFileStateStore

NOW = datetime(2026, 9, 7, tzinfo=UTC)


def safe_policy() -> Policy:
    return Policy(principals={Role.BOT: ["github-actions[bot]"]})


def deployment_policy(**updates) -> DeploymentPolicyConfig:
    values = {
        "policy_version": "DEPLOYMENT-V1",
        "mode": "MANUAL",
        "merge_enabled": False,
        "bridge_mode": "CHATGPT_WORK_EVENT_BRIDGE",
        "bridge_authorized": True,
        "standard_work_execution_authorization": "CHAIRMAN-DELEGATION-STANDARD-WORK-V1",
        "principals": {
            Role.CHAIRMAN: ["chairman"],
            Role.ARCHITECT: ["architect"],
            Role.ENGINEER: ["engineer"],
            Role.BOT: ["github-actions[bot]"],
        },
    }
    values.update(updates)
    return DeploymentPolicyConfig(**values)


def bootstrapped_state() -> State:
    item = WorkItem(
        work_item_id="DEV-GOV-001",
        kind="DEV_GOV",
        status=Stage.CLOSED,
        created_at=NOW,
        artifact_path="docs/specifications/DEV-GOV-001.md",
        artifact_sha256="a" * 64,
        target_branch="feature/dev-gov-001-autonomous-development-pipeline",
        execution_authorization="chairman-bootstrap",
        pr_number=12,
        head_sha="b" * 40,
        base_sha="a" * 40,
        review_artifact="REVIEW-DEV-GOV-001.md",
        architecture_status=ReviewStatus.FINAL_APPROVED,
        approved_head_sha="b" * 40,
        ci=CI(head_sha="b" * 40, status="PASSED"),
        merge_commit="c" * 40,
        closeout={"architecture": "ARCH-CLOSEOUT-DEV-GOV-001"},
    )
    return State(
        revision=1,
        current_work_item=item.work_item_id,
        work_items={item.work_item_id: item},
        events=[
            Event(
                event_id="bootstrap-complete",
                event_type=EventType.CLOSEOUT_COMPLETED,
                timestamp=NOW,
                work_item_id=item.work_item_id,
                actor="chairman",
                output_state=Stage.CLOSED,
            )
        ],
    )


def prepared_store(tmp_path) -> LocalFileStateStore:
    store = LocalFileStateStore(tmp_path / "state")
    store.save(bootstrapped_state(), None)
    return store


def test_effective_policy_fingerprint_and_activation_are_reproducible():
    config = deployment_policy()
    setup = DeploymentSetup(
        authorized_by="chairman",
        setup_at=NOW,
        policy_fingerprint=policy_fingerprint(config),
        effective_policy=config,
    )
    state = State(deployment_setup=setup)
    inactive = materialize_effective_policy(safe_policy(), state, activated=False)
    active = materialize_effective_policy(safe_policy(), state, activated=True)
    assert policy_fingerprint(config) == policy_fingerprint(config.model_copy(deep=True))
    assert not inactive.pipeline_enabled and not inactive.bridge_authorized
    assert active.pipeline_enabled and active.bridge_authorized
    assert active.mode == "MANUAL" and not active.merge_enabled and not active.auto_ready
    assert active.principals[Role.ARCHITECT] == ["architect"]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda c: c.principals.pop(Role.ENGINEER), "DEPLOYMENT_PRINCIPALS_INVALID"),
        (lambda c: c.principals[Role.ENGINEER].clear(), "DEPLOYMENT_PRINCIPALS_INVALID"),
        (lambda c: c.principals[Role.ENGINEER].append(""), "DEPLOYMENT_PRINCIPALS_INVALID"),
        (
            lambda c: c.principals[Role.ENGINEER].append("engineer"),
            "DEPLOYMENT_PRINCIPALS_INVALID",
        ),
        (
            lambda c: c.principals.__setitem__(Role.CHAIRMAN, ["intruder"]),
            "DEPLOYMENT_CHAIRMAN_IDENTITY_INVALID",
        ),
        (
            lambda c: c.principals[Role.ENGINEER].append("architect"),
            "DEPLOYMENT_ROLE_SEPARATION_INVALID",
        ),
        (
            lambda c: c.principals[Role.CHAIRMAN].append("architect"),
            "DEPLOYMENT_ROLE_SEPARATION_INVALID",
        ),
        (
            lambda c: c.principals[Role.BOT].append("engineer"),
            "DEPLOYMENT_ROLE_SEPARATION_INVALID",
        ),
        (lambda c: c.principals[Role.BOT].clear(), "DEPLOYMENT_PRINCIPALS_INVALID"),
        (
            lambda c: c.principals[Role.BOT].__setitem__(0, "other-bot"),
            "DEPLOYMENT_ORCHESTRATOR_IDENTITY_MISSING",
        ),
    ],
)
def test_deployment_principal_validation_fails_closed(mutate, reason):
    config = deployment_policy()
    mutate(config)
    with pytest.raises(GovernanceError, match=reason):
        validate_deployment_policy(config, "chairman")


def test_deployment_policy_mode_and_bridge_validation():
    cases = [
        (deployment_policy(mode="DRY_RUN", merge_enabled=True), "DRY_RUN_MERGE_FORBIDDEN"),
        (
            deployment_policy(bridge_mode="OPENAI_API_BRIDGE", openai_model=None),
            "AUTHORIZED_API_MODEL_REQUIRED",
        ),
        (
            deployment_policy(openai_model="model-not-applicable"),
            "OPENAI_MODEL_WITHOUT_API_BRIDGE",
        ),
        (
            deployment_policy(bridge_mode="MANUAL_BRIDGE", bridge_authorized=True),
            "MANUAL_BRIDGE_AUTHORIZATION_INVALID",
        ),
    ]
    for config, reason in cases:
        with pytest.raises(GovernanceError, match=reason):
            validate_deployment_policy(config, "chairman")
    api = deployment_policy(bridge_mode="OPENAI_API_BRIDGE", openai_model="gpt-reviewed")
    validate_deployment_policy(api, "chairman")


def test_materialization_rejects_unset_tampered_or_mutable_privilege():
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_REQUIRED"):
        materialize_effective_policy(safe_policy(), State(), activated=True)
    assert not materialize_effective_policy(
        safe_policy(), State(), activated=False
    ).pipeline_enabled

    config = deployment_policy()
    setup = DeploymentSetup(
        authorized_by="chairman",
        setup_at=NOW,
        policy_fingerprint="0" * 64,
        effective_policy=config,
    )
    with pytest.raises(GovernanceError, match="DEPLOYMENT_POLICY_FINGERPRINT_MISMATCH"):
        materialize_effective_policy(safe_policy(), State(deployment_setup=setup), activated=True)

    for field, value in [
        ("pipeline_enabled", True),
        ("merge_enabled", True),
        ("auto_ready", True),
        ("bridge_authorized", True),
        ("mode", "AUTO"),
        ("bridge_mode", "CHATGPT_WORK_EVENT_BRIDGE"),
        ("openai_model", "unreviewed-model"),
        ("standard_work_execution_authorization", "unreviewed"),
    ]:
        static = safe_policy()
        setattr(static, field, value)
        with pytest.raises(GovernanceError, match="MUTABLE_DEPLOYMENT_POLICY_FORBIDDEN"):
            materialize_effective_policy(static, State(), activated=False)
    static = safe_policy()
    static.principals[Role.CHAIRMAN] = ["unreviewed"]
    with pytest.raises(GovernanceError, match="MUTABLE_DEPLOYMENT_POLICY_FORBIDDEN"):
        materialize_effective_policy(static, State(), activated=False)


def test_setup_records_complete_audit_and_is_one_time(tmp_path):
    store = prepared_store(tmp_path)
    config = deployment_policy()
    state = complete_deployment_setup(store, safe_policy(), "chairman", config, now=lambda: NOW)
    assert state.deployment_setup is not None
    assert state.deployment_setup.effective_policy == config
    assert state.deployment_setup.policy_fingerprint == policy_fingerprint(config)
    event = state.events[-1]
    assert event.event_type == EventType.DEPLOYMENT_SETUP_COMPLETED
    assert event.actor == "chairman" and event.timestamp == NOW
    assert event.metadata == {
        "policy_version": "DEPLOYMENT-V1",
        "policy_fingerprint": policy_fingerprint(config),
        "mode": "MANUAL",
        "bridge_mode": "CHATGPT_WORK_EVENT_BRIDGE",
        "merge_enabled": "false",
        "auto_ready": "false",
        "principals_configured": "true",
        "setup_completed": "true",
    }
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_ALREADY_COMPLETE"):
        complete_deployment_setup(store, safe_policy(), "chairman", config)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: setattr(state, "current_work_item", None),
        lambda state: setattr(state.work_items["DEV-GOV-001"], "status", Stage.CLOSEOUT),
        lambda state: setattr(
            state.work_items["DEV-GOV-001"], "architecture_status", ReviewStatus.CHANGES_REQUIRED
        ),
        lambda state: setattr(state.work_items["DEV-GOV-001"].ci, "status", "FAILED"),
        lambda state: setattr(state.work_items["DEV-GOV-001"], "merge_commit", None),
        lambda state: state.work_items["DEV-GOV-001"].closeout.clear(),
        lambda state: setattr(state.work_items["DEV-GOV-001"], "next_spec_requested", True),
    ],
)
def test_setup_requires_formal_bootstrap_closeout(mutate):
    state = bootstrapped_state()
    mutate(state)
    store = Mock()
    store.load.return_value = (state, "revision")
    with pytest.raises(GovernanceError, match="BOOTSTRAP_CLOSEOUT_STATE_REQUIRED"):
        complete_deployment_setup(store, safe_policy(), "chairman", deployment_policy())


def test_setup_rejects_secret_like_policy_content():
    config = deployment_policy(standard_work_execution_authorization="ghp_" + "a" * 40)
    store = Mock()
    store.load.return_value = (bootstrapped_state(), "revision")
    with pytest.raises(GovernanceError, match="ARTIFACT_SECRET_OR_BINARY"):
        complete_deployment_setup(store, safe_policy(), "chairman", config)


def test_protected_setup_entrypoint_rejects_wrong_actor_missing_inputs_and_active_pipeline(
    tmp_path, monkeypatch
):
    import aic_dev_governance.runner as module

    config_path = tmp_path / "configs/dev-governance.json"
    config_path.parent.mkdir()
    config_path.write_text(safe_policy().model_dump_json())
    event_path = tmp_path / "event.json"
    event_path.write_text("{}")
    monkeypatch.setenv("GH_TOKEN", "placeholder")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_ACTOR", "intruder")
    monkeypatch.setenv("AIC_SETUP_CHAIRMAN", "chairman")
    monkeypatch.setenv("AIC_DEPLOYMENT_POLICY", deployment_policy().model_dump_json())
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_CHAIRMAN_NOT_AUTHORIZED"):
        run_setup(tmp_path)
    monkeypatch.setenv("GITHUB_ACTOR", "chairman")
    monkeypatch.setenv("AIC_PIPELINE_ENABLED", "true")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_REQUIRES_PIPELINE_OFF"):
        run_setup(tmp_path)
    monkeypatch.setenv("AIC_PIPELINE_ENABLED", "false")
    event_path.write_text("not-json")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_EVENT_INVALID"):
        run_setup(tmp_path)
    event_path.write_text("[]")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_EVENT_INVALID"):
        run_setup(tmp_path)
    event_path.write_text("{}")
    monkeypatch.delenv("AIC_DEPLOYMENT_POLICY")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_POLICY_REQUIRED"):
        run_setup(tmp_path)
    monkeypatch.delenv("GH_TOKEN")
    with pytest.raises(GovernanceError, match="GITHUB_AUTHORIZATION_MISSING"):
        run_setup(tmp_path)
    monkeypatch.setenv("GH_TOKEN", "placeholder")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_MANUAL_WORKFLOW_REQUIRED"):
        run_setup(tmp_path)
    assert not hasattr(module, "enable_pipeline")


def test_protected_setup_entrypoint_records_policy_without_activation(tmp_path, monkeypatch):
    import aic_dev_governance.runner as module

    config_path = tmp_path / "configs/dev-governance.json"
    config_path.parent.mkdir()
    config_path.write_text(safe_policy().model_dump_json())
    event_path = tmp_path / "event.json"
    event_path.write_text("{}")
    store = prepared_store(tmp_path)
    github = Mock()
    monkeypatch.setattr(module, "GitHubClient", lambda *args, **kwargs: github)
    monkeypatch.setattr(module, "GitHubStateBranchStore", lambda *args: store)
    monkeypatch.setenv("GH_TOKEN", "placeholder")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_ACTOR", "chairman")
    monkeypatch.setenv("AIC_SETUP_CHAIRMAN", "chairman")
    monkeypatch.setenv("AIC_DEPLOYMENT_POLICY", deployment_policy().model_dump_json())
    monkeypatch.setenv("AIC_PIPELINE_ENABLED", "false")
    output = run_setup(tmp_path)
    state, _ = store.load()
    assert "Stage: CLOSED" in output
    assert f"Deployment policy: {policy_fingerprint(deployment_policy())}" in output
    assert state.deployment_setup is not None
    assert not safe_policy().pipeline_enabled
    github.merge.assert_not_called()
    github.publish_task.assert_not_called()


def test_bootstrap_setup_first_work_item_and_engineering_delivery(tmp_path):
    store = LocalFileStateStore(tmp_path / "state")
    static = safe_policy()
    bootstrap_policy = static.model_copy(deep=True)
    bootstrap_policy.principals[Role.CHAIRMAN] = ["chairman"]
    github = Mock()
    bootstrap_spec = "# DEV-GOV-001 approved specification\n"
    bootstrap_review = "# DEV-GOV-001 final Architecture Closeout\n"
    bootstrap_head = "b" * 40
    merge_commit = "c" * 40
    github.pull_request.return_value = PullRequest(
        number=12,
        head_sha=bootstrap_head,
        base_sha="a" * 40,
        branch="feature/dev-gov-001-autonomous-development-pipeline",
        state="MERGED",
        draft=False,
        head_repository=static.repository,
        merge_commit=merge_commit,
    )
    github.ref.side_effect = lambda branch: "d" * 40 if branch == "main" else None
    github.tree.return_value = "reviewed-tree"
    github.contains_commit.return_value = True
    github.ci.return_value = CI(head_sha=bootstrap_head, status="PASSED")
    descriptor = {
        "work_item_id": "DEV-GOV-001",
        "spec_path": "docs/specifications/DEV-GOV-001.md",
        "review_path": "REVIEW-DEV-GOV-001.md",
        "spec_sha256": hashlib.sha256(bootstrap_spec.encode()).hexdigest(),
    }
    github.file.side_effect = lambda path, ref: (
        json.dumps(descriptor)
        if path == ".github/dev-governance/work-item.json"
        else bootstrap_spec
        if path == descriptor["spec_path"]
        else bootstrap_review
    )
    bootstrap_orchestrator = Orchestrator(
        store,
        github,
        bootstrap_policy,
        "github-actions[bot]",
        now=lambda: NOW,
    )
    initialized = initialize_state(
        bootstrap_orchestrator,
        github,
        "chairman",
        {
            "pr_number": 12,
            "reviewed_head_sha": bootstrap_head,
            "architecture_closeout_reference": "ARCH-CLOSEOUT-DEV-GOV-001",
        },
    )
    assert initialized.work_items["DEV-GOV-001"].status == Stage.CLOSED
    config = deployment_policy()
    complete_deployment_setup(store, static, "chairman", config, now=lambda: NOW)
    state, _ = store.load()
    effective = materialize_effective_policy(static, state, activated=True)
    spec = "# Synthetic approved next specification\n"
    github.file.side_effect = None
    github.file.return_value = spec
    orchestrator = Orchestrator(
        store,
        github,
        effective,
        "github-actions[bot]",
        now=lambda: NOW,
    )
    item = WorkItem(
        work_item_id="SYNTHETIC-SPEC-010",
        kind="SPEC",
        previous_work_item="DEV-GOV-001",
        created_at=NOW,
        artifact_path="docs/specifications/SYNTHETIC-SPEC-010.md",
        artifact_sha256=hashlib.sha256(spec.encode()).hexdigest(),
        target_branch="feature/synthetic-spec-010",
        execution_authorization=config.standard_work_execution_authorization,
    )
    registered = dispatch_command(
        orchestrator,
        github,
        tmp_path,
        "architect",
        "register",
        {"work_item": item.model_dump(mode="json"), "approved_ref": "d" * 40},
    )
    assert registered.work_items[item.work_item_id].status == Stage.SPEC_READY
    assert registered.current_work_item == item.work_item_id

    allowed = {*MEMORY_PATHS, item.artifact_path}
    for path in allowed:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec if path == item.artifact_path else "# Memory\n")
    engineering = Mock()
    engineering.trigger_engineering.return_value = "https://github.test/task/1"
    delivered = orchestrator.dispatch(
        item.work_item_id,
        "ENGINEERING",
        reader=ArtifactReader(tmp_path, allowed),
        engineering=engineering,
    )
    task = next(task for task in delivered.tasks.values() if task.work_item_id == item.work_item_id)
    assert task.status == "DELIVERED"
    assert task.delivery_reference == "https://github.test/task/1"
    assert not delivered.work_items[item.work_item_id].chairman_required
    assert not delivered.work_items[item.work_item_id].governance_exception
    assert all(event.event_type != EventType.RECOVERY_AUTHORIZED for event in delivered.events)

    for event_type in (EventType.CODEX_STARTED, EventType.IMPLEMENTATION_COMPLETED):
        dispatch_command(
            orchestrator,
            github,
            tmp_path,
            "engineer",
            "event",
            {"event_type": event_type},
        )
    review_path = "REVIEW-SYNTHETIC-SPEC-010.md"
    review_file = tmp_path / review_path
    review_file.write_text("# Synthetic review package\n")
    pr = PullRequest(
        number=13,
        head_sha="e" * 40,
        base_sha="d" * 40,
        branch=item.target_branch,
        state="OPEN",
        draft=True,
        head_repository=static.repository,
    )
    github.pull_request.return_value = pr
    dispatch_command(
        orchestrator,
        github,
        tmp_path,
        "engineer",
        "attach-pr",
        {"pr_number": pr.number, "review_artifact": review_path},
    )
    descriptor_file = tmp_path / ".github/dev-governance/work-item.json"
    descriptor_file.parent.mkdir(parents=True)
    descriptor_file.write_text('{"bootstrap_only":"unchanged"}')
    descriptor_before = descriptor_file.read_text()
    final_state, _ = store.load()
    check_governance(tmp_path, pr, final_state, effective)
    assert descriptor_file.read_text() == descriptor_before


def test_protected_setup_workflow_is_manual_trusted_and_nonactivating():
    root = __import__("pathlib").Path(__file__).parents[4]
    text = (root / ".github/workflows/dev-governance-setup.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "environment: aic-development-governance-setup" in text
    assert "if: github.ref == 'refs/heads/main' && vars.AIC_PIPELINE_ENABLED != 'true'" in text
    assert "ref: main" in text
    assert "python -m aic_dev_governance setup" in text
    assert "AIC_PIPELINE_ENABLED: ${{ vars.AIC_PIPELINE_ENABLED }}" in text
    assert "python -m aic_dev_governance run" not in text
    guide = (root / "SETUP-DEV-GOV-001-CHAIRMAN.md").read_text()
    ordered = [
        "1. Receive Chief Investment Architect Final Approval",
        "2. Human-merge PR #12",
        "3. Create protected environment `aic-development-governance-bootstrap`",
        "4. Run `AIC Development Governance Bootstrap`",
        "5. Apply the main branch-protection checklist",
        "6. Create protected environment `aic-development-governance-setup`",
        "7. Run `AIC Development Governance Setup`",
        "8. Verify an ordinary registered fixture PR",
        "9. Set repository variable `AIC_PIPELINE_ENABLED=true`",
        "10. Have the authorized Architect register",
        "11. Connect an external ChatGPT Work/Codex consumer",
        "12. Consider AUTO/Auto Merge only in a separate",
    ]
    positions = [guide.index(step) for step in ordered]
    assert positions == sorted(positions)
