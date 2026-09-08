from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from aic_dev_governance.deployment import (
    materialize_effective_policy,
    policy_fingerprint,
    resolve_deployment_policy,
)
from aic_dev_governance.models import (
    CI,
    DeploymentPolicyConfig,
    DeploymentPolicyRotation,
    DeploymentSetup,
    Event,
    EventType,
    GovernanceError,
    Policy,
    ReviewStatus,
    Role,
    Stage,
    State,
    WorkItem,
)
from aic_dev_governance.runner import (
    complete_deployment_policy_rotation,
    run_policy_rotation,
)
from aic_dev_governance.store import GitHubStateBranchStore, LocalFileStateStore

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def safe_policy() -> Policy:
    return Policy(principals={Role.BOT: ["github-actions[bot]"]})


def deployment_policy(**updates: object) -> DeploymentPolicyConfig:
    values: dict[str, object] = {
        "policy_version": "DEPLOYMENT-V1",
        "mode": "DRY_RUN",
        "merge_enabled": False,
        "bridge_mode": "CHATGPT_WORK_EVENT_BRIDGE",
        "bridge_authorized": True,
        "standard_work_execution_authorization": "CHAIRMAN-DELEGATION-AIC-STANDARD-WORK-V1",
        "principals": {
            Role.CHAIRMAN: ["steemchen-creator"],
            Role.ARCHITECT: ["aic-architect", "openai-architecture-bridge"],
            Role.ENGINEER: ["aic-codex-cto"],
            Role.BOT: ["github-actions[bot]"],
        },
    }
    values.update(updates)
    return DeploymentPolicyConfig(**values)


def state_with_setup() -> State:
    config = deployment_policy()
    item = WorkItem(
        work_item_id="DEV-GOV-001",
        kind="DEV_GOV",
        status=Stage.CLOSED,
        created_at=NOW,
        artifact_path="docs/specifications/DEV-GOV-001.md",
        artifact_sha256="a" * 64,
        target_branch="feature/dev-gov-001-autonomous-development-pipeline",
        execution_authorization="chairman-bootstrap",
        head_sha="b" * 40,
        architecture_status=ReviewStatus.FINAL_APPROVED,
        ci=CI(head_sha="b" * 40, status="PASSED"),
        merge_commit="c" * 40,
        closeout={"architecture": "complete"},
    )
    return State(
        revision=1,
        current_work_item=item.work_item_id,
        work_items={item.work_item_id: item},
        events=[
            Event(
                event_id="deployment-setup-complete",
                event_type=EventType.DEPLOYMENT_SETUP_COMPLETED,
                timestamp=NOW,
                work_item_id=item.work_item_id,
                actor="steemchen-creator",
                output_state=Stage.CLOSED,
            )
        ],
        deployment_setup=DeploymentSetup(
            authorized_by="steemchen-creator",
            setup_at=NOW,
            policy_fingerprint=policy_fingerprint(config),
            effective_policy=config,
        ),
    )


def prepared_store(tmp_path) -> LocalFileStateStore:
    store = LocalFileStateStore(tmp_path / "state")
    store.save(state_with_setup(), None)
    return store


def proposed_policy(*architects: str) -> DeploymentPolicyConfig:
    config = deployment_policy()
    config.principals[Role.ARCHITECT] = list(architects)
    return config


def rotate(
    store: LocalFileStateStore,
    proposed: DeploymentPolicyConfig,
    *,
    expected: str | None = None,
    actor: str = "steemchen-creator",
    pipeline_enabled: bool = False,
    now: datetime = NOW + timedelta(minutes=1),
) -> State:
    state, _ = store.load()
    resolved = resolve_deployment_policy(state)
    assert resolved is not None
    return complete_deployment_policy_rotation(
        store,
        safe_policy(),
        actor,
        expected or resolved[1],
        proposed,
        "Recover unavailable Architect identity without changing deployment behavior.",
        pipeline_enabled=pipeline_enabled,
        now=lambda: now,
    )


def test_rotation_adds_architect_and_complete_audit_without_rewriting_setup(tmp_path):
    store = prepared_store(tmp_path)
    before, _ = store.load()
    original_setup = (
        before.deployment_setup.model_copy(deep=True) if before.deployment_setup else None
    )
    proposed = proposed_policy(
        "aic-architect", "aic-architect-2", "openai-architecture-bridge"
    )

    state = rotate(store, proposed)

    assert state.deployment_setup == original_setup
    assert len(state.deployment_policy_rotations) == 1
    rotation = state.deployment_policy_rotations[0]
    assert rotation.previous_policy_fingerprint == original_setup.policy_fingerprint
    assert rotation.new_policy_fingerprint == policy_fingerprint(proposed)
    assert rotation.authorized_by == "steemchen-creator"
    assert rotation.rotated_at == NOW + timedelta(minutes=1)
    assert rotation.new_effective_policy == proposed
    event = state.events[-1]
    assert event.event_type == EventType.DEPLOYMENT_POLICY_ROTATED
    assert event.actor == "steemchen-creator"
    assert event.metadata["previous_policy_fingerprint"] == rotation.previous_policy_fingerprint
    assert event.metadata["new_policy_fingerprint"] == rotation.new_policy_fingerprint


def test_rotation_fingerprint_chain_is_ordered_and_fails_closed_when_tampered(tmp_path):
    store = prepared_store(tmp_path)
    first = rotate(
        store,
        proposed_policy("aic-architect", "aic-architect-2", "openai-architecture-bridge"),
    )
    first_fingerprint = first.deployment_policy_rotations[-1].new_policy_fingerprint
    second = rotate(
        store,
        proposed_policy(
            "aic-architect",
            "aic-architect-2",
            "aic-architect-3",
            "openai-architecture-bridge",
        ),
        expected=first_fingerprint,
        now=NOW + timedelta(minutes=2),
    )
    assert second.deployment_policy_rotations[1].previous_policy_fingerprint == first_fingerprint
    second.deployment_policy_rotations[1].previous_policy_fingerprint = "0" * 64
    with pytest.raises(GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_CHAIN_MISMATCH"):
        resolve_deployment_policy(second)


def test_rotation_chain_rejects_missing_setup_bad_new_fingerprint_and_no_change(tmp_path):
    proposed = proposed_policy(
        "aic-architect", "aic-architect-2", "openai-architecture-bridge"
    )
    rotation = DeploymentPolicyRotation(
        previous_policy_fingerprint=policy_fingerprint(deployment_policy()),
        new_policy_fingerprint="0" * 64,
        authorized_by="steemchen-creator",
        rotated_at=NOW,
        reason="Identity recovery",
        new_effective_policy=proposed,
    )
    with pytest.raises(GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_WITHOUT_SETUP"):
        resolve_deployment_policy(State(deployment_policy_rotations=[rotation]))
    state = state_with_setup()
    state.deployment_policy_rotations.append(rotation)
    with pytest.raises(
        GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_FINGERPRINT_MISMATCH"
    ):
        resolve_deployment_policy(state)
    with pytest.raises(GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_NO_CHANGE"):
        rotate(prepared_store(tmp_path), deployment_policy())

    empty_store = Mock()
    empty_store.load.return_value = (State(), "revision")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_REQUIRED"):
        complete_deployment_policy_rotation(
            empty_store,
            safe_policy(),
            "steemchen-creator",
            "0" * 64,
            proposed,
            "Identity recovery",
            pipeline_enabled=False,
        )


def test_state_store_rejects_deployment_setup_and_rotation_rewrites(tmp_path):
    store = prepared_store(tmp_path)
    rotated = rotate(
        store,
        proposed_policy("aic-architect", "aic-architect-2", "openai-architecture-bridge"),
    )
    _, revision = store.load()
    assert rotated.deployment_setup is not None
    rotated.deployment_setup.authorized_by = "different-chairman"
    rotated.events.append(
        Event(
            event_id="attempted-setup-rewrite",
            event_type=EventType.OPERATION_FAILED,
            timestamp=NOW + timedelta(minutes=2),
            work_item_id="DEV-GOV-001",
            actor="intruder",
        )
    )
    rotated.revision += 1
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_REWRITE_PROHIBITED"):
        store.save(rotated, revision)

    unchanged, revision = store.load()
    unchanged.deployment_policy_rotations[0].reason = "rewritten"
    unchanged.events.append(
        Event(
            event_id="attempted-rotation-rewrite",
            event_type=EventType.OPERATION_FAILED,
            timestamp=NOW + timedelta(minutes=3),
            work_item_id="DEV-GOV-001",
            actor="intruder",
        )
    )
    unchanged.revision += 1
    with pytest.raises(
        GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_REWRITE_PROHIBITED"
    ):
        store.save(unchanged, revision)


def test_github_store_writes_one_immutable_rotation_artifact(tmp_path):
    local = prepared_store(tmp_path)
    rotated = rotate(
        local,
        proposed_policy("aic-architect", "aic-architect-2", "openai-architecture-bridge"),
    )
    previous = state_with_setup()
    github = Mock()
    github.tree.return_value = "existing-tree"
    github.request.side_effect = [
        {"sha": "new-tree"},
        {"sha": "d" * 40},
        {},
    ]
    store = GitHubStateBranchStore(github)
    store.load = Mock(return_value=(previous, "a" * 40))

    store.save(rotated, "a" * 40)

    tree_payload = github.request.call_args_list[0].args[2]
    paths = {entry["path"] for entry in tree_payload["tree"]}
    fingerprint = rotated.deployment_policy_rotations[0].new_policy_fingerprint
    assert f"state/deployment-policy-rotations/0001-{fingerprint}.json" in paths
    assert any(path.startswith("state/events/") for path in paths)


def test_rotation_rejects_non_chairman(tmp_path):
    with pytest.raises(
        GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_CHAIRMAN_NOT_AUTHORIZED"
    ):
        rotate(
            prepared_store(tmp_path),
            proposed_policy("aic-architect", "aic-architect-2", "openai-architecture-bridge"),
            actor="aic-codex-cto",
        )


def test_rotation_rejects_active_pipeline(tmp_path):
    with pytest.raises(GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_REQUIRES_PIPELINE_OFF"):
        rotate(
            prepared_store(tmp_path),
            proposed_policy("aic-architect", "aic-architect-2", "openai-architecture-bridge"),
            pipeline_enabled=True,
        )


def test_rotation_rejects_non_principal_change(tmp_path):
    proposed = proposed_policy(
        "aic-architect", "aic-architect-2", "openai-architecture-bridge"
    )
    proposed.mode = "MANUAL"
    with pytest.raises(
        GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_NON_PRINCIPAL_CHANGE"
    ):
        rotate(prepared_store(tmp_path), proposed)


def test_rotation_rejects_role_overlap(tmp_path):
    proposed = proposed_policy(
        "aic-architect", "aic-architect-2", "openai-architecture-bridge"
    )
    proposed.principals[Role.ARCHITECT].append("aic-codex-cto")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_ROLE_SEPARATION_INVALID"):
        rotate(prepared_store(tmp_path), proposed)


def test_rotation_rejects_stale_expected_fingerprint(tmp_path):
    with pytest.raises(
        GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_STALE_FINGERPRINT"
    ):
        rotate(
            prepared_store(tmp_path),
            proposed_policy("aic-architect", "aic-architect-2", "openai-architecture-bridge"),
            expected="0" * 64,
        )


def test_materialization_uses_latest_valid_rotation(tmp_path):
    state = rotate(
        prepared_store(tmp_path),
        proposed_policy("aic-architect", "aic-architect-2", "openai-architecture-bridge"),
    )
    inactive = materialize_effective_policy(safe_policy(), state, activated=False)
    active = materialize_effective_policy(safe_policy(), state, activated=True)
    expected = ["aic-architect", "aic-architect-2", "openai-architecture-bridge"]
    assert inactive.principals[Role.ARCHITECT] == expected
    assert not inactive.pipeline_enabled and not inactive.bridge_authorized
    assert active.principals[Role.ARCHITECT] == expected
    assert active.pipeline_enabled and active.bridge_authorized


def test_policy_rotation_entrypoint_and_workflow_are_protected(tmp_path, monkeypatch):
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
    proposed = proposed_policy(
        "aic-architect", "aic-architect-2", "openai-architecture-bridge"
    )
    monkeypatch.setenv("GH_TOKEN", "placeholder")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "steemchen-creator")
    monkeypatch.setenv("AIC_SETUP_CHAIRMAN", "steemchen-creator")
    monkeypatch.setenv("AIC_PIPELINE_ENABLED", "false")
    monkeypatch.setenv("AIC_DEPLOYMENT_POLICY", proposed.model_dump_json())
    monkeypatch.setenv(
        "AIC_PREVIOUS_POLICY_FINGERPRINT", policy_fingerprint(deployment_policy())
    )
    monkeypatch.setenv("AIC_POLICY_ROTATION_REASON", "Recover Architect identity")

    output = run_policy_rotation(tmp_path)

    state, _ = store.load()
    assert "Previous deployment policy:" in output
    assert state.deployment_policy_rotations[-1].new_effective_policy == proposed
    github.merge.assert_not_called()
    github.publish_task.assert_not_called()

    root = __import__("pathlib").Path(__file__).parents[4]
    workflow = (root / ".github/workflows/dev-governance-policy-rotation.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "environment: aic-development-governance-setup" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert "ref: main" in workflow and "persist-credentials: false" in workflow
    assert "AIC_PIPELINE_ENABLED: ${{ vars.AIC_PIPELINE_ENABLED }}" in workflow
    assert "python -m aic_dev_governance rotate-policy" in workflow
    assert "python -m aic_dev_governance run" not in workflow


@pytest.mark.parametrize(
    ("name", "value", "reason"),
    [
        ("GH_TOKEN", None, "GITHUB_AUTHORIZATION_MISSING"),
        ("GITHUB_EVENT_NAME", "push", "MANUAL_WORKFLOW_REQUIRED"),
        ("GITHUB_ACTOR", "intruder", "DEPLOYMENT_POLICY_ROTATION_CHAIRMAN_NOT_AUTHORIZED"),
        ("AIC_PIPELINE_ENABLED", "true", "DEPLOYMENT_POLICY_ROTATION_REQUIRES_PIPELINE_OFF"),
        ("AIC_PIPELINE_ENABLED", "", "DEPLOYMENT_POLICY_ROTATION_REQUIRES_PIPELINE_OFF"),
        ("GITHUB_REF", "refs/heads/feature/untrusted", "TRUSTED_MAIN_REQUIRED"),
        ("AIC_PREVIOUS_POLICY_FINGERPRINT", "invalid", "FINGERPRINT_REQUIRED"),
        ("AIC_DEPLOYMENT_POLICY", "", "DEPLOYMENT_POLICY_REQUIRED"),
        ("AIC_POLICY_ROTATION_REASON", "", "ROTATION_REASON_REQUIRED"),
    ],
)
def test_policy_rotation_entrypoint_fails_closed(name, value, reason, tmp_path, monkeypatch):
    config_path = tmp_path / "configs/dev-governance.json"
    config_path.parent.mkdir()
    config_path.write_text(safe_policy().model_dump_json())
    event_path = tmp_path / "event.json"
    event_path.write_text("{}")
    monkeypatch.setenv("GH_TOKEN", "placeholder")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "steemchen-creator")
    monkeypatch.setenv("AIC_SETUP_CHAIRMAN", "steemchen-creator")
    monkeypatch.setenv("AIC_PIPELINE_ENABLED", "false")
    monkeypatch.setenv("AIC_DEPLOYMENT_POLICY", deployment_policy().model_dump_json())
    monkeypatch.setenv("AIC_PREVIOUS_POLICY_FINGERPRINT", "a" * 64)
    monkeypatch.setenv("AIC_POLICY_ROTATION_REASON", "Recover Architect identity")
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(GovernanceError, match=reason):
        run_policy_rotation(tmp_path)


@pytest.mark.parametrize("event_content", ["not-json", "[]"])
def test_policy_rotation_entrypoint_rejects_invalid_event(
    event_content, tmp_path, monkeypatch
):
    config_path = tmp_path / "configs/dev-governance.json"
    config_path.parent.mkdir()
    config_path.write_text(safe_policy().model_dump_json())
    event_path = tmp_path / "event.json"
    event_path.write_text(event_content)
    monkeypatch.setenv("GH_TOKEN", "placeholder")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_ACTOR", "steemchen-creator")
    monkeypatch.setenv("AIC_SETUP_CHAIRMAN", "steemchen-creator")
    monkeypatch.setenv("AIC_PIPELINE_ENABLED", "false")
    with pytest.raises(GovernanceError, match="DEPLOYMENT_POLICY_ROTATION_EVENT_INVALID"):
        run_policy_rotation(tmp_path)
