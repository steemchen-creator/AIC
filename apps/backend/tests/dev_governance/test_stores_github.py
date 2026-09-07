import base64
import json
from datetime import UTC, datetime

import httpx
import pytest

from aic_dev_governance.github import GitHubClient
from aic_dev_governance.models import Event, EventType, GovernanceError, Stage, State
from aic_dev_governance.store import GitHubStateBranchStore, LocalFileStateStore, validate_append


def audited(state, identity="one"):
    updated = state.model_copy(deep=True)
    updated.events.append(
        Event(
            event_id=identity,
            event_type=EventType.TASK_RESERVED,
            timestamp=datetime(2026, 9, 7, tzinfo=UTC),
            work_item_id="SPEC-TEST",
            actor="bot",
            output_state=Stage.PLANNED,
        )
    )
    updated.revision += 1
    return updated


def test_local_atomic_restart_and_conflicts(tmp_path, state):
    store = LocalFileStateStore(tmp_path)
    assert store.load() == (State(), None)
    initial = audited(state)
    revision = store.save(initial, None)
    assert LocalFileStateStore(tmp_path).load() == (initial, revision)
    updated = audited(initial, "two")
    with pytest.raises(GovernanceError, match="STATE_CONFLICT"):
        store.save(updated, "wrong")
    lock = tmp_path / ".write.lock"
    lock.touch()
    with pytest.raises(GovernanceError, match="STATE_CONFLICT"):
        store.save(updated, revision)
    lock.unlink()
    newer = store.save(updated, revision)
    assert newer != revision
    assert store.load()[0].events[:1] == initial.events


def test_local_atomic_write_failure_preserves_prior_state(tmp_path, state, monkeypatch):
    import aic_dev_governance.store as module

    store = LocalFileStateStore(tmp_path)
    initial = audited(state)
    revision = store.save(initial, None)

    def fail(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError):
        store.save(audited(initial, "two"), revision)
    assert store.load() == (initial, revision)
    assert list(tmp_path.iterdir()) == [store.path]


def test_append_checks_and_corrupt_state(tmp_path, state):
    from aic_dev_governance.deployment import policy_fingerprint
    from aic_dev_governance.models import (
        ArchitectureResult,
        DeploymentPolicyConfig,
        DeploymentSetup,
        Role,
    )

    initial = audited(state)
    with pytest.raises(GovernanceError, match="STATE_REVISION_NOT_ADVANCED"):
        validate_append(initial, initial)
    newer = audited(initial, "two")
    newer.events[0].actor = "attacker"
    with pytest.raises(GovernanceError, match="AUDIT_REWRITE_PROHIBITED"):
        validate_append(initial, newer)
    newer = initial.model_copy(deep=True)
    newer.revision += 1
    with pytest.raises(GovernanceError, match="AUDIT_EVENT_REQUIRED"):
        validate_append(initial, newer)
    initial.reviews["ARCH-1"] = ArchitectureResult(
        work_item="SPEC-TEST",
        review_id="ARCH-1",
        result="FINAL_APPROVED",
        reviewed_head_sha="a" * 40,
        blocking_items=[],
        non_blocking_items=[],
        reviewed_at=datetime(2026, 9, 7, tzinfo=UTC),
        reviewer_role="CHIEF_INVESTMENT_ARCHITECT",
    )
    newer = audited(initial, "two")
    newer.reviews = {}
    with pytest.raises(GovernanceError, match="REVIEW_REWRITE_PROHIBITED"):
        validate_append(initial, newer)
    initial.artifacts["requests/one.json"] = "immutable"
    newer = audited(initial, "two")
    newer.artifacts = {}
    with pytest.raises(GovernanceError, match="ARTIFACT_REWRITE_PROHIBITED"):
        validate_append(initial, newer)
    deployment = DeploymentPolicyConfig(
        policy_version="DEPLOYMENT-V1",
        mode="MANUAL",
        standard_work_execution_authorization="standard-work",
        principals={
            Role.CHAIRMAN: ["chairman"],
            Role.ARCHITECT: ["architect"],
            Role.ENGINEER: ["engineer"],
            Role.BOT: ["github-actions[bot]"],
        },
    )
    initial.deployment_setup = DeploymentSetup(
        authorized_by="chairman",
        setup_at=datetime(2026, 9, 7, tzinfo=UTC),
        policy_fingerprint=policy_fingerprint(deployment),
        effective_policy=deployment,
    )
    newer = audited(initial, "three")
    newer.deployment_setup = None
    with pytest.raises(GovernanceError, match="DEPLOYMENT_SETUP_REWRITE_PROHIBITED"):
        validate_append(initial, newer)


class StateAPI:
    def __init__(self):
        self.head = None
        self.files = {}
        self.pending = {}
        self.requests = []
        self.fail_ref = None

    def ref(self, branch):
        assert branch == "automation/dev-state"
        return self.head

    def file(self, path, ref):
        assert ref == self.head
        return self.files[path]

    def tree(self, sha):
        return "tree-" + sha

    def request(self, method, path, data):
        self.requests.append((method, path, data))
        if path == "/git/trees":
            self.pending = {entry["path"]: entry["content"] for entry in data["tree"]}
            return {"sha": "tree"}
        if path == "/git/commits":
            return {"sha": str(len(self.requests)).zfill(40)}
        if self.fail_ref:
            raise GovernanceError(self.fail_ref)
        assert not data.get("force", False)
        self.head = data["sha"]
        self.files.update(self.pending)
        return {"ref": path}


def test_github_state_branch_restart_append_artifacts_and_cas(state):
    from aic_dev_governance.models import ArchitectureResult

    api = StateAPI()
    store = GitHubStateBranchStore(api)
    assert store.load() == (State(), None)
    initial = audited(state)
    initial.reviews["ARCH-1"] = ArchitectureResult(
        work_item="SPEC-TEST",
        review_id="ARCH-1",
        result="FINAL_APPROVED",
        reviewed_head_sha="a" * 40,
        blocking_items=[],
        non_blocking_items=[],
        reviewed_at=datetime(2026, 9, 7, tzinfo=UTC),
        reviewer_role="CHIEF_INVESTMENT_ARCHITECT",
    )
    initial.artifacts["requests/context.json"] = "{}"
    revision = store.save(initial, None)
    assert store.load() == (initial, revision)
    assert "architecture/reviews/SPEC-TEST/ARCH-1.md" in api.files
    assert "state/events/one.json" in api.files
    with pytest.raises(GovernanceError, match="STATE_BRANCH_CONFLICT"):
        store.save(audited(initial, "two"), None)
    store.save(audited(initial, "two"), revision)
    assert api.requests[-1][0] == "PATCH"
    assert api.requests[-1][2]["force"] is False


@pytest.mark.parametrize("reason", ["GITHUB_HTTP_409", "GITHUB_HTTP_422", "GITHUB_UNAVAILABLE"])
def test_state_ref_conflict_or_ambiguous_failure_never_retries(state, reason):
    api = StateAPI()
    api.fail_ref = reason
    expected = "STATE_BRANCH_CONFLICT" if reason != "GITHUB_UNAVAILABLE" else reason
    with pytest.raises(GovernanceError, match=expected):
        GitHubStateBranchStore(api).save(audited(state), None)
    assert len(api.requests) == 3


def client(handler, **kwargs):
    return GitHubClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        "steemchen-creator/AIC",
        sleep=lambda _: None,
        **kwargs,
    )


@pytest.mark.parametrize("code", [401, 403, 404, 409, 422, 429, 500, 502, 503, 504])
def test_http_failures_bounded_and_sanitized(code):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(code, json={"message": "PRIVATE_TOKEN_MUST_NOT_APPEAR"})

    api = client(handle)
    with pytest.raises(GovernanceError, match=f"GITHUB_HTTP_{code}") as error:
        api.request("GET", "/pulls/1")
    assert "PRIVATE_TOKEN" not in str(error.value)
    assert len(calls) == (3 if code in {429, 500, 502, 503, 504} else 1)
    calls.clear()
    with pytest.raises(GovernanceError):
        api.request("PUT", "/pulls/1/merge", {"sha": "a" * 40})
    assert len(calls) == 1


def test_transport_retry_success_and_response_validation():
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("private detail")
        return httpx.Response(200, json={"ok": True})

    assert client(handle).request("GET", "/test") == {"ok": True}

    def down(request):
        raise httpx.ConnectError("private detail")

    with pytest.raises(GovernanceError, match="GITHUB_UNAVAILABLE"):
        client(down).request("GET", "/test")
    with pytest.raises(GovernanceError, match="GITHUB_RESPONSE_INVALID"):
        client(lambda r: httpx.Response(200, text="not json")).request("GET", "/test")
    with pytest.raises(GovernanceError, match="REPOSITORY_INVALID"):
        GitHubClient(httpx.Client(), "https://attacker.test")
    with pytest.raises(GovernanceError, match="RETRY_POLICY_INVALID"):
        client(handle, attempts=0)
    for method, path in [("EXEC", "/x"), ("GET", "http://attacker.test")]:
        with pytest.raises(GovernanceError, match="HTTP_OPERATION_NOT_ALLOWED"):
            client(handle).request(method, path)


def test_pagination_and_limit():
    def pages(request):
        return httpx.Response(
            200, json={"values": [{}] * (100 if request.url.params["page"] == "1" else 1)}
        )

    assert len(client(pages).pages("/checks?filter=latest", "values")) == 101
    with pytest.raises(GovernanceError, match="GITHUB_RESPONSE_INVALID"):
        client(lambda r: httpx.Response(200, json={})).pages("/bad")
    with pytest.raises(GovernanceError, match="GITHUB_PAGINATION_LIMIT"):
        client(lambda r: httpx.Response(200, json=[{}] * 100)).pages("/unbounded")


def raw_pr(pr):
    return {
        "number": pr.number,
        "head": {"sha": pr.head_sha, "ref": pr.branch, "repo": {"full_name": pr.head_repository}},
        "base": {"sha": pr.base_sha, "ref": pr.base_branch},
        "merged": pr.state == "MERGED",
        "state": "closed" if pr.state == "MERGED" else pr.state.lower(),
        "draft": pr.draft,
        "merge_commit_sha": pr.merge_commit,
        "node_id": "PR_node",
    }


@pytest.mark.parametrize("protected", [True, False])
@pytest.mark.parametrize("conclusion", ["success", "failure", None])
def test_ci_required_check_discovery_including_extra_rules(pr, policy, protected, conclusion):
    required = policy.required_checks + ["extra"]

    def handle(request):
        path = request.url.path
        if path.endswith("/rules/branches/main"):
            return httpx.Response(
                200,
                json=[
                    {"type": "other"},
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [{"context": "extra", "integration_id": 42}]
                        },
                    },
                ],
            )
        if path.endswith("/branches/main"):
            return httpx.Response(200, json={"protected": protected})
        if path.endswith("/required_status_checks"):
            return httpx.Response(
                200, json={"contexts": ["extra"], "checks": [{"context": "extra", "app_id": 42}]}
            )
        if path.endswith("/pulls/12"):
            return httpx.Response(200, json=raw_pr(pr))
        if "/actions/runs/" in path:
            return httpx.Response(
                200,
                json={
                    "id": 555,
                    "head_sha": pr.head_sha,
                    "status": "completed" if conclusion else "in_progress",
                    "conclusion": conclusion,
                    "run_attempt": 1,
                    "html_url": "https://run.test",
                },
            )
        return httpx.Response(
            200,
            json={
                "check_runs": [
                    {
                        "name": name,
                        "head_sha": pr.head_sha,
                        "conclusion": conclusion,
                        "id": i + 1,
                        "app": {"id": 42 if name == "extra" else 15368},
                        "html_url": "https://github.com/example/actions/runs/555/job/1",
                    }
                    for i, name in enumerate(required)
                ]
            },
        )

    api = client(handle)
    assert api.pull_request(12) == pr
    ci = api.ci(pr, policy)
    assert ci.status == {"success": "PASSED", "failure": "FAILED", None: "PENDING"}[conclusion]
    assert ci.required_checks["extra"] == 42 and ci.discovery_complete


@pytest.mark.parametrize(
    ("unrelated_status", "unrelated_conclusion"),
    [("completed", "skipped"), ("in_progress", None), ("completed", "failure")],
)
def test_ci_ignores_non_required_trusted_workflow_state(
    pr, policy, unrelated_status, unrelated_conclusion
):
    requested_runs = []

    def handle(request):
        path = request.url.path
        if path.endswith("/rules/branches/main"):
            return httpx.Response(200, json=[])
        if path.endswith("/branches/main"):
            return httpx.Response(200, json={"protected": True})
        if path.endswith("/required_status_checks"):
            return httpx.Response(200, json={"contexts": [], "checks": []})
        if "/actions/runs/" in path:
            run_id = int(path.rsplit("/", 1)[-1])
            requested_runs.append(run_id)
            return httpx.Response(
                200,
                json={
                    "id": run_id,
                    "head_sha": pr.head_sha,
                    "status": "completed" if run_id == 555 else unrelated_status,
                    "conclusion": "success" if run_id == 555 else unrelated_conclusion,
                    "run_attempt": 1,
                    "html_url": f"https://github.com/example/actions/runs/{run_id}",
                },
            )
        return httpx.Response(
            200,
            json={
                "check_runs": [
                    {
                        "name": name,
                        "head_sha": pr.head_sha,
                        "conclusion": "success",
                        "id": index + 1,
                        "app": {"id": policy.trusted_check_app_id},
                        "html_url": "https://github.com/example/actions/runs/555/job/1",
                    }
                    for index, name in enumerate(policy.required_checks)
                ]
                + [
                    {
                        "name": "AIC Development Orchestrator / orchestrate",
                        "head_sha": pr.head_sha,
                        "conclusion": unrelated_conclusion,
                        "id": 999,
                        "app": {"id": policy.trusted_check_app_id},
                        "html_url": "https://github.com/example/actions/runs/666/job/1",
                    }
                ]
            },
        )

    ci = client(handle).ci(pr, policy)
    assert ci.status == "PASSED"
    assert requested_runs == [555]
    assert [run.run_id for run in ci.workflow_runs] == [555]
    assert any(
        check.name == "AIC Development Orchestrator / orchestrate"
        and check.conclusion == (unrelated_conclusion or "pending")
        for check in ci.checks
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("check_failed", "FAILED"),
        ("workflow_failed", "FAILED"),
        ("check_stale", "PENDING"),
        ("workflow_stale", "PENDING"),
        ("check_missing", "PENDING"),
        ("workflow_pending", "PENDING"),
    ],
)
def test_required_check_and_workflow_failures_remain_fail_closed(pr, policy, failure, expected):
    def handle(request):
        path = request.url.path
        if path.endswith("/rules/branches/main"):
            return httpx.Response(200, json=[])
        if path.endswith("/branches/main"):
            return httpx.Response(200, json={"protected": True})
        if path.endswith("/required_status_checks"):
            return httpx.Response(200, json={"contexts": [], "checks": []})
        if "/actions/runs/" in path:
            return httpx.Response(
                200,
                json={
                    "id": 555,
                    "head_sha": "b" * 40 if failure == "workflow_stale" else pr.head_sha,
                    "status": "in_progress" if failure == "workflow_pending" else "completed",
                    "conclusion": None
                    if failure == "workflow_pending"
                    else "failure"
                    if failure == "workflow_failed"
                    else "success",
                    "run_attempt": 1,
                    "html_url": "https://github.com/example/actions/runs/555",
                },
            )
        names = list(policy.required_checks)
        if failure == "check_missing":
            names.pop()
        return httpx.Response(
            200,
            json={
                "check_runs": [
                    {
                        "name": name,
                        "head_sha": "b" * 40
                        if failure == "check_stale" and index == 0
                        else pr.head_sha,
                        "conclusion": "failure"
                        if failure == "check_failed" and index == 0
                        else "success",
                        "id": index + 1,
                        "app": {"id": policy.trusted_check_app_id},
                        "html_url": "https://github.com/example/actions/runs/555/job/1",
                    }
                    for index, name in enumerate(names)
                ]
            },
        )

    assert client(handle).ci(pr, policy).status == expected


def test_missing_required_workflow_run_fails_closed(pr, policy):
    def handle(request):
        path = request.url.path
        if path.endswith("/rules/branches/main"):
            return httpx.Response(200, json=[])
        if path.endswith("/branches/main"):
            return httpx.Response(200, json={"protected": True})
        if path.endswith("/required_status_checks"):
            return httpx.Response(200, json={"contexts": [], "checks": []})
        if "/actions/runs/" in path:
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "check_runs": [
                    {
                        "name": name,
                        "head_sha": pr.head_sha,
                        "conclusion": "success",
                        "id": index + 1,
                        "app": {"id": policy.trusted_check_app_id},
                        "html_url": "https://github.com/example/actions/runs/555/job/1",
                    }
                    for index, name in enumerate(policy.required_checks)
                ]
            },
        )

    with pytest.raises(GovernanceError, match="GITHUB_HTTP_404"):
        client(handle).ci(pr, policy)


def test_merge_expected_sha_and_ready_head_drift(pr):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path.endswith("/merge"):
            return httpx.Response(200, json={"merged": True, "sha": "c" * 40})
        if request.url.path.endswith("/graphql"):
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(200, json=raw_pr(pr))

    api = client(handle)
    assert api.merge(12, "a" * 40) == "c" * 40
    assert json.loads(requests[0].content) == {"sha": "a" * 40, "merge_method": "squash"}
    api.mark_ready(12, "a" * 40)
    with pytest.raises(GovernanceError, match="PR_HEAD_CHANGED"):
        api.mark_ready(12, "b" * 40)
    with pytest.raises(GovernanceError, match="MERGE_PERMISSION_DENIED"):
        client(lambda r: httpx.Response(200, json={"merged": False})).merge(12, "a" * 40)
    pr.state, pr.merge_commit = "MERGED", "c" * 40
    assert api.pull_request(12).state == "MERGED"


def test_branch_ref_file_tree_and_deletion():
    refs = {"feature/test": "a" * 40}

    def handle(request):
        path = request.url.path
        if "/git/ref/heads/" in path:
            branch = path.split("/heads/")[1]
            return (
                httpx.Response(200, json={"object": {"sha": refs[branch]}})
                if branch in refs
                else httpx.Response(404)
            )
        if request.method == "DELETE":
            refs.pop("feature/test")
            return httpx.Response(204)
        if "/contents/" in path:
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "encoding": "base64",
                    "content": base64.b64encode(b"text").decode(),
                },
            )
        return httpx.Response(200, json={"tree": {"sha": "d" * 40}})

    api = client(handle)
    assert api.tree("a" * 40) == "d" * 40
    assert api.file("docs/test.md", "a" * 40) == "text"
    with pytest.raises(GovernanceError, match="BRANCH_DELETION_NOT_ALLOWED"):
        api.delete_branch("main", "a" * 40)
    with pytest.raises(GovernanceError, match="BRANCH_HAS_UNMERGED_WORK"):
        api.delete_branch("feature/test", "b" * 40)
    api.delete_branch("feature/test", "a" * 40)
    api.delete_branch("feature/test", "a" * 40)
    with pytest.raises(GovernanceError, match="ARTIFACT_ENCODING_INVALID"):
        client(lambda r: httpx.Response(200, json={})).file("path", "main")
    with pytest.raises(GovernanceError, match="GITHUB_HTTP_403"):
        client(lambda r: httpx.Response(403)).ref("main")


@pytest.mark.parametrize(
    ("status", "expected"), [("ahead", True), ("identical", True), ("diverged", False)]
)
def test_commit_containment(status, expected):
    api = client(lambda r: httpx.Response(200, json={"status": status}))
    assert api.contains_commit("a" * 40, "b" * 40) is expected


@pytest.mark.parametrize("pr_number", [12, None])
def test_task_publication_and_duplicate_transport(pr_number):
    posted = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json=posted)
        body = json.loads(request.content)["body"]
        posted.append({"body": body, "html_url": "https://github.com/task/1"})
        return httpx.Response(201, json=posted[-1])

    api = client(handle)
    assert api.publish_task("task1", "request", pr_number) == "https://github.com/task/1"
    assert api.publish_task("task1", "request", pr_number) == "https://github.com/task/1"
    assert len(posted) == 1
