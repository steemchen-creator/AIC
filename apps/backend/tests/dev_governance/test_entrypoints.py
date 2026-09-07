import hashlib
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aic_dev_governance.ci_gate import (
    BOOTSTRAP_BASE,
    BOOTSTRAP_BRANCH,
    check_governance,
    resolve_work_item,
)
from aic_dev_governance.coverage_gate import TARGETS, verify_coverage
from aic_dev_governance.gates import classify_changed_paths
from aic_dev_governance.models import GovernanceError, ReviewStatus, Stage, State
from aic_dev_governance.runner import (
    GitHubArtifactReader,
    run,
)
from aic_dev_governance.workspace import GitWorkspace


@pytest.fixture
def gate_root(tmp_path, item):
    paths = [item.artifact_path, item.review_artifact]
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("approved spec", encoding="utf-8")
    item.artifact_sha256 = hashlib.sha256(b"approved spec").hexdigest()
    descriptor = {
        "work_item_id": item.work_item_id,
        "spec_path": item.artifact_path,
        "review_path": item.review_artifact,
        "spec_sha256": item.artifact_sha256,
    }
    target = tmp_path / ".github/dev-governance/work-item.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(descriptor), encoding="utf-8")
    return tmp_path, descriptor, target


def test_readonly_governance_gate_and_bootstrap(gate_root, item, pr, state, policy):
    root, descriptor, target = gate_root
    check_governance(root, pr, state, policy)
    descriptor["work_item_id"] = "DEV-GOV-001"
    target.write_text(json.dumps(descriptor), encoding="utf-8")
    with pytest.raises(GovernanceError, match="STATE_MISSING_OR_BOOTSTRAP_SCOPE_INVALID"):
        check_governance(root, pr, State(), policy)
    pr.branch, pr.base_sha, pr.draft = BOOTSTRAP_BRANCH, BOOTSTRAP_BASE, True
    policy.merge_enabled = False
    check_governance(root, pr, State(), policy)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("head_sha", "b" * 40, "STATE_PR_IDENTITY_MISMATCH"),
        ("status", Stage.CLOSED, "ILLEGAL_MERGE_STATE"),
        ("governance_exception", True, "WORK_ITEM_BLOCKED"),
        ("architecture_status", ReviewStatus.APPROVED_CANDIDATE, "READY_BEFORE_FINAL_APPROVAL"),
        ("approved_head_sha", "b" * 40, "READY_BEFORE_FINAL_APPROVAL"),
    ],
)
def test_governance_gate_rejects(gate_root, item, pr, state, policy, field, value, reason):
    root, _, _ = gate_root
    setattr(item, field, value)
    with pytest.raises(GovernanceError, match=reason):
        check_governance(root, pr, state, policy)


def test_governance_gate_descriptor_spec_stale_and_foreign(gate_root, item, pr, state, policy):
    root, descriptor, target = gate_root
    descriptor["extra"] = True
    target.write_text(json.dumps(descriptor))
    with pytest.raises(GovernanceError, match="WORK_ITEM_DESCRIPTOR_INVALID"):
        check_governance(root, pr, State(), policy)
    descriptor.pop("extra")
    descriptor["spec_sha256"] = "a" * 64
    target.write_text(json.dumps(descriptor))
    with pytest.raises(GovernanceError, match="APPROVED_SPEC_HASH_MISMATCH"):
        check_governance(root, pr, State(), policy)
    descriptor["spec_sha256"] = item.artifact_sha256
    target.write_text(json.dumps(descriptor))
    pr.head_repository = "outsider/fork"
    with pytest.raises(GovernanceError, match="PR_NOT_OPEN_OR_FOREIGN"):
        check_governance(root, pr, state, policy)
    pr.head_repository, pr.draft = policy.repository, True
    item.approved_head_sha = "b" * 40
    with pytest.raises(GovernanceError, match="APPROVAL_STALE"):
        check_governance(root, pr, state, policy)


def test_future_spec_uses_state_identity_without_mutating_bootstrap_descriptor(
    gate_root, item, pr, state, policy
):
    root, descriptor, target = gate_root
    descriptor["work_item_id"] = "DEV-GOV-001"
    original_descriptor = json.dumps(descriptor)
    target.write_text(original_descriptor)
    item.work_item_id = "SPEC-010"
    item.target_branch = "feature/spec010-implementation"
    item.status = Stage.REVIEW_REQUIRED
    item.architecture_status = ReviewStatus.REVIEW_REQUIRED
    item.approved_head_sha = None
    pr.branch = item.target_branch
    pr.draft = True
    state.current_work_item = item.work_item_id
    state.work_items = {"DEV-GOV-001": state.work_items["PREVIOUS"], item.work_item_id: item}
    check_governance(root, pr, state, policy)
    assert target.read_text() == original_descriptor
    assert resolve_work_item(pr, state) is item
    assert classify_changed_paths(["apps/backend/src/risk_report.py", "tests/test_risk.py"]) == []


def test_state_identity_mismatch_and_ambiguity_fail_closed(item, pr, state):
    unrelated = state.work_items.pop(item.work_item_id)
    with pytest.raises(GovernanceError, match="WORK_ITEM_NOT_RESOLVED"):
        resolve_work_item(pr, state)
    state.work_items[item.work_item_id] = unrelated
    pr.branch = "feature/wrong"
    with pytest.raises(GovernanceError, match="STATE_PR_IDENTITY_MISMATCH"):
        resolve_work_item(pr, state)


def test_governance_gate_validates_state_owned_spec(gate_root, item, pr, state, policy):
    root, _, _ = gate_root
    (root / item.artifact_path).unlink()
    state.artifacts[item.artifact_path] = "approved spec"
    check_governance(root, pr, state, policy)

    state.artifacts[item.artifact_path] = "changed spec"
    with pytest.raises(GovernanceError, match="APPROVED_SPEC_HASH_MISMATCH"):
        check_governance(root, pr, state, policy)

    state.artifacts[item.artifact_path] = "token=" + "ghp_" + "a" * 40
    with pytest.raises(GovernanceError, match="ARTIFACT_SECRET_OR_BINARY"):
        check_governance(root, pr, state, policy)
    pr.branch = item.target_branch
    duplicate = item.model_copy(update={"work_item_id": "SPEC-OTHER", "pr_number": 99})
    state.work_items[duplicate.work_item_id] = duplicate
    with pytest.raises(GovernanceError, match="WORK_ITEM_IDENTITY_AMBIGUOUS"):
        resolve_work_item(pr, state)


def test_coverage_targets_missing_branch_or_below(tmp_path):
    path = tmp_path / "coverage.json"
    data = {
        "meta": {"branch_coverage": True},
        "files": {
            "apps\\backend\\src\\aic_dev_governance\\" + name: {"summary": {"percent_covered": 100}}
            for name in TARGETS
        },
    }
    path.write_text(json.dumps(data))
    assert all(value == 100 for value in verify_coverage(path).values())
    data["meta"]["branch_coverage"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(GovernanceError, match="COVERAGE_EVIDENCE_MISSING"):
        verify_coverage(path)
    data["meta"]["branch_coverage"] = True
    list(data["files"].values())[0]["summary"]["percent_covered"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(GovernanceError, match="COVERAGE_BELOW_TARGET"):
        verify_coverage(path)


class WorkspaceFixture(GitWorkspace):
    def __init__(self, root, failure=None, local=True):
        super().__init__(root)
        self.failure, self.local, self.calls = failure, local, []

    def _git(self, *args):
        self.calls.append(args)
        if args == ("status", "--porcelain"):
            return "dirty" if self.failure == "dirty" else ""
        if args == ("rev-parse", "origin/main"):
            return "wrong" if self.failure == "remote" else "c" * 40
        if args == ("rev-parse", "HEAD"):
            return "wrong" if self.failure == "localmain" else "c" * 40
        if args[0] == "rev-parse":
            return "wrong" if self.failure == "tree" and args[1].startswith("a") else "f" * 40
        if args[0] == "show-ref":
            sha = "b" * 40 if self.failure == "branch" else "a" * 40
            return (
                "c" * 40
                + " refs/heads/main\n"
                + (sha + " refs/heads/feature/spec-test" if self.local else "")
            )
        if args[0] == "update-ref":
            if self.failure != "delete":
                self.local = False
        return ""


@pytest.mark.parametrize("local", [True, False])
def test_workspace_closeout_expected_old_sha_and_idempotent(tmp_path, local):
    workspace = WorkspaceFixture(tmp_path, local=local)
    workspace.closeout("feature/spec-test", "a" * 40, "c" * 40, "c" * 40)
    assert not workspace.local
    if local:
        assert ("update-ref", "-d", "refs/heads/feature/spec-test", "a" * 40) in workspace.calls


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("dirty", "WORKSPACE_DIRTY"),
        ("remote", "REMOTE_MAIN_CHANGED"),
        ("localmain", "LOCAL_MAIN_MISMATCH"),
        ("tree", "MERGE_TREE_REVIEW_REQUIRED"),
        ("branch", "BRANCH_HAS_UNMERGED_WORK"),
        ("delete", "LOCAL_BRANCH_DELETION_FAILED"),
    ],
)
def test_workspace_failures(tmp_path, failure, reason):
    with pytest.raises(GovernanceError, match=reason):
        WorkspaceFixture(tmp_path, failure).closeout(
            "feature/spec-test", "a" * 40, "c" * 40, "c" * 40
        )


def test_workspace_safe_subprocess_boundary(tmp_path, monkeypatch):
    workspace = GitWorkspace(tmp_path)
    with pytest.raises(GovernanceError, match="COMMAND_NOT_ALLOWLISTED"):
        workspace._git("reset", "--hard")
    with pytest.raises(GovernanceError, match="BRANCH_DELETION_NOT_ALLOWED"):
        workspace.closeout("main", "a" * 40, "c" * 40, "c" * 40)
    with pytest.raises(GovernanceError, match="SHA_INVALID"):
        workspace.closeout("feature/spec-test", "--evil", "c" * 40, "c" * 40)

    def success(arguments, **kwargs):
        assert kwargs["shell"] is False and kwargs["timeout"] == 60
        return SimpleNamespace(stdout=" clean \n")

    monkeypatch.setattr(subprocess, "run", success)
    assert workspace._git("status", "--porcelain") == "clean"

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 60)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(GovernanceError, match="WORKSPACE_GIT_FAILED"):
        workspace._git("fetch", "origin")


def test_actual_diff_classification_not_pr_claim():
    assert classify_changed_paths(["normal.py"]) == []
    assert classify_changed_paths(
        [
            "AGENTS.md",
            "PROJECT_ROADMAP.md",
            "docs/project/memory.md",
            ".github/workflows/policy.yml",
            "configs/dev-governance.json",
            "app/shared/config.py",
            "app/dev_governance/policy.py",
            "broker.py",
            "leverage.py",
            "live_trading.py",
            "configs/risk-hard-caps.yml",
            "domain/portfolio/policies.py",
        ]
    ) == [
        "broker",
        "leverage_permission",
        "master_project_objective",
        "platform_risk_hard_cap",
        "production_trading",
        "secret_permission_model",
    ]
    assert (
        classify_changed_paths(
            [
                "apps/backend/src/risk.py",
                "apps/backend/src/risk_report.py",
                "apps/backend/tests/test_risk.py",
                "docs/architecture/risk-model.md",
            ]
        )
        == []
    )
    assert classify_changed_paths(
        [".github/workflows/dev-governance-setup.yml", "configs/dev-governance.json"]
    ) == ["secret_permission_model"]


def test_remote_artifact_allowlist_and_limits():
    github = Mock()
    github.file.return_value = "data"
    reader = GitHubArtifactReader(github, {"spec.md"}, "a" * 40)
    assert reader.read("spec.md") == "data"
    with pytest.raises(GovernanceError, match="ARTIFACT_NOT_ALLOWLISTED"):
        reader.read("comment.md")
    github.file.return_value = "x" * 200001
    with pytest.raises(GovernanceError, match="ARTIFACT_TOO_LARGE_OR_BINARY"):
        reader.read("spec.md")


def test_run_disabled_missing_auth_and_event(tmp_path, monkeypatch, policy):
    config = tmp_path / "configs/dev-governance.json"
    config.parent.mkdir()
    policy.pipeline_enabled = False
    config.write_text(policy.model_dump_json())
    assert "PIPELINE_DISABLED" in run(tmp_path)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(GovernanceError, match="GITHUB_AUTHORIZATION_MISSING"):
        run(tmp_path, gate_only=True)
    monkeypatch.setenv("GH_TOKEN", "placeholder-test-token")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    with pytest.raises(GovernanceError, match="AUTHENTICATED_EVENT_REQUIRED"):
        run(tmp_path, gate_only=True)


def test_run_gate_checks_actual_head_without_writes(gate_root, monkeypatch, policy, pr, state):
    import aic_dev_governance.runner as module

    root, _, _ = gate_root
    config = root / "configs/dev-governance.json"
    config.parent.mkdir()
    config.write_text(policy.model_dump_json())
    event = root / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 12}}))
    github = Mock()
    github.pull_request.return_value = pr
    store = Mock()
    store.load.return_value = (state, "revision")
    monkeypatch.setattr(module, "GitHubClient", lambda *args, **kwargs: github)
    monkeypatch.setattr(module, "GitHubStateBranchStore", lambda *args: store)
    monkeypatch.setenv("GH_TOKEN", "placeholder-test-token")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("AIC_EXPECTED_HEAD", pr.head_sha)
    assert "PASSED" in run(root, gate_only=True)
    store.save.assert_not_called()
    monkeypatch.setenv("AIC_EXPECTED_HEAD", "b" * 40)
    with pytest.raises(GovernanceError, match="CI_CHECKOUT_HEAD_STALE"):
        run(root, gate_only=True)
    event.write_text("{}")
    assert "MAIN_PUBLICATION_CHECK" in run(root, gate_only=True)


def test_cli_status_metrics_error_and_run(tmp_path, monkeypatch, capsys):
    import aic_dev_governance.__main__ as module

    for command in ("status", "metrics"):
        monkeypatch.setattr(
            "sys.argv", ["aic_dev_governance", command, "--state-dir", str(tmp_path)]
        )
        assert module.main() == 0
    monkeypatch.setattr("sys.argv", ["aic_dev_governance", "run"])
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: "DISABLED")
    assert module.main() == 0 and "DISABLED" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["aic_dev_governance", "setup"])
    monkeypatch.setattr(module, "run_setup", lambda *args, **kwargs: "SETUP_COMPLETE")
    assert module.main() == 0 and "SETUP_COMPLETE" in capsys.readouterr().out

    def fail(*args, **kwargs):
        raise GovernanceError("SAFE_REASON")

    monkeypatch.setattr("sys.argv", ["aic_dev_governance", "run"])
    monkeypatch.setattr(module, "run", fail)
    assert module.main() == 1 and "SAFE_REASON" in capsys.readouterr().out


def test_context_generation_matches_exact_remote_blobs(gate_root, item, pr):
    from aic_dev_governance.artifacts import MEMORY_PATHS
    from aic_dev_governance.runner import generate_review_context

    root, _, _ = gate_root
    for path in MEMORY_PATHS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("memory\n", encoding="utf-8")
    github = Mock()
    github.pull_request.return_value = pr
    github.pages.return_value = [
        {"filename": item.review_artifact, "status": "modified"},
        {"filename": "old.py", "status": "removed"},
    ]
    github.file.side_effect = lambda path, ref: (root / path).read_text(encoding="utf-8")
    manifest = generate_review_context(root, github, 12)
    assert manifest.head_sha == pr.head_sha
    assert manifest.deleted_files == ["old.py"] and "old.py" in manifest.changed_files
    assert not any(entry.path == "old.py" for entry in manifest.context_entries)
    github.file.side_effect = lambda path, ref: (
        "modified after commit"
        if path == item.review_artifact
        else (root / path).read_text(encoding="utf-8")
    )
    with pytest.raises(GovernanceError, match="LOCAL_REMOTE_CONTEXT_MISMATCH"):
        generate_review_context(root, github, 12)


def test_cli_context_auth_and_external_output(gate_root, monkeypatch, item, pr, tmp_path):
    import aic_dev_governance.__main__ as module
    from aic_dev_governance.artifacts import MEMORY_PATHS
    from aic_dev_governance.runner import generate_review_context

    root, _, _ = gate_root
    for path in MEMORY_PATHS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("memory", encoding="utf-8")
    github = Mock()
    github.pull_request.return_value = pr
    github.pages.return_value = []
    github.file.side_effect = lambda path, ref: (root / path).read_text(encoding="utf-8")
    manifest = generate_review_context(root, github, 12)
    monkeypatch.setattr(
        "sys.argv", ["aic_dev_governance", "context", "--output", str(tmp_path / "out.json")]
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("AIC_PR_NUMBER", raising=False)
    assert module.main() == 1
    monkeypatch.setenv("GH_TOKEN", "placeholder-test-token")
    monkeypatch.setenv("AIC_PR_NUMBER", "12")
    store = Mock()
    store.load.return_value = (State(), None)
    monkeypatch.setattr(module, "GitHubStateBranchStore", lambda *args: store)
    monkeypatch.setattr(module, "generate_review_context", lambda *args: manifest)
    assert module.main() == 0
    assert json.loads((tmp_path / "out.json").read_text())["head_sha"] == pr.head_sha
