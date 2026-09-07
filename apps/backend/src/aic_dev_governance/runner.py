"""Trusted-main GitHub Actions entry point. PR content never becomes executable policy."""

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .artifacts import (
    MEMORY_PATHS,
    ArtifactReader,
    ReviewContext,
    build_context,
    dashboard,
    safe_artifact_path,
    validate_artifact_content,
)
from .bridges import GitHubEventTriggerAdapter, OpenAIApiTriggerAdapter, select_architecture_bridge
from .ci_gate import BOOTSTRAP_BRANCH, check_governance, resolve_work_item
from .deployment import (
    materialize_effective_policy,
    policy_fingerprint,
    validate_deployment_policy,
)
from .github import GitHubClient
from .models import (
    ArchitectureResult,
    DeploymentPolicyConfig,
    DeploymentSetup,
    Event,
    EventType,
    GovernanceError,
    Policy,
    ReviewStatus,
    Role,
    SpecificationResult,
    Stage,
    State,
    WorkItem,
)
from .observability import MEMORY_TRIGGERS
from .orchestrator import Orchestrator
from .state_machine import authenticate
from .store import GitHubStateBranchStore, StateStore
from .workspace import GitWorkspace


class GitHubArtifactReader(ArtifactReader):
    def __init__(
        self,
        github: GitHubClient,
        allowed: set[str],
        ref: str,
        state_artifacts: dict[str, str] | None = None,
    ) -> None:
        self.github, self.allowed, self.ref = github, allowed, ref
        self.state_artifacts = state_artifacts or {}

    def read(self, path: str) -> str:
        safe_artifact_path(path)
        if path not in self.allowed:
            raise GovernanceError("ARTIFACT_NOT_ALLOWLISTED")
        content = (
            self.state_artifacts[path]
            if path in self.state_artifacts
            else self.github.file(path, self.ref)
        )
        if len(content.encode()) > 200_000 or "\x00" in content:
            raise GovernanceError("ARTIFACT_TOO_LARGE_OR_BINARY")
        validate_artifact_content(content)
        return content


def tick(
    orchestrator: Orchestrator,
    github: GitHubClient,
    api_client: httpx.Client,
    root: Path | None = None,
) -> State:
    state, _ = orchestrator.store.load()
    if state.current_work_item is None:
        return state
    item = state.work_items[state.current_work_item]
    if item.pr_number and item.status != Stage.CLOSED:
        state = orchestrator.reconcile(item.work_item_id)
        item = state.work_items[item.work_item_id]
    if (
        item.status in {Stage.BLOCKED, Stage.CHAIRMAN_DECISION_REQUIRED, Stage.FAILED}
        or state.paused
    ):
        return state
    if not orchestrator.policy.pipeline_enabled or item.work_item_id == "DEV-GOV-001":
        return state
    if item.status in {Stage.FINAL_APPROVED, Stage.MERGE_ELIGIBLE}:
        if item.ci.status != "PASSED":
            return state
        if orchestrator.policy.auto_ready:
            state = orchestrator.ready(item.work_item_id)
        # MANUAL still records eligibility for the authorized human, never merges.
        try:
            state = orchestrator.merge(item.work_item_id)
        except GovernanceError as error:
            if error.reason not in {"AUTO_MERGE_DISABLED", "PR_DRAFT"}:
                raise
            state, _ = orchestrator.store.load()
        item = state.work_items[item.work_item_id]
    if item.status in {Stage.MERGED, Stage.CLOSEOUT} and root is not None:
        state = orchestrator.closeout(item.work_item_id, GitWorkspace(root))
        item = state.work_items[item.work_item_id]
    if item.status not in {
        Stage.SPEC_READY,
        Stage.FIX_READY,
        Stage.REVIEW_REQUIRED,
        Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE,
        Stage.CLOSED,
    }:
        return state
    ref = item.head_sha or github.ref("main")
    if not ref:
        raise GovernanceError("MAIN_MISSING")
    paths = set(MEMORY_PATHS) | {item.artifact_path}
    if item.unresolved_fix:
        paths.add(item.unresolved_fix)
    if item.status in {Stage.SPEC_READY, Stage.FIX_READY}:
        return orchestrator.dispatch(
            item.work_item_id,
            "ENGINEERING",
            reader=GitHubArtifactReader(github, paths, ref, state.artifacts),
            engineering=GitHubEventTriggerAdapter(
                github, authorized=True, pr_number=item.pr_number
            ),
        )
    if item.status == Stage.CLOSED and not item.next_spec_requested:
        return state
    if not item.pr_number or not item.review_artifact:
        raise GovernanceError("REVIEW_ARTIFACT_MISSING")
    changes = github.pages(f"/pulls/{item.pr_number}/files")
    changed = [f["filename"] for f in changes]
    deleted = [f["filename"] for f in changes if f["status"] == "removed"]
    # Required ADRs come from the approved work item context, not arbitrary PR commands.
    adrs = [path for path in changed if path.startswith("docs/adr/") and path not in deleted]
    paths.update(set(changed) - set(deleted))
    paths.add(item.review_artifact)
    reader = GitHubArtifactReader(github, paths, ref, state.artifacts)
    manifest = build_context(
        reader,
        item,
        changed,
        adrs,
        tests_summary="See REVIEW and CI checks",
        coverage_summary="See exact HEAD Backend tests evidence",
        deleted_files=deleted,
    )
    bridge = select_architecture_bridge(orchestrator.policy, github, api_client, item.pr_number)
    state = orchestrator.dispatch(
        item.work_item_id,
        "NEXT_SPEC" if item.status == Stage.CLOSED else "ARCHITECTURE_REVIEW",
        architecture=bridge,
        reader=reader,
        manifest=manifest,
    )
    if isinstance(bridge, OpenAIApiTriggerAdapter):
        outcome = bridge.result
        if outcome is None:
            for task in state.tasks.values():
                stored = state.artifacts.get(f"results/{task.task_id}.json")
                if (
                    stored
                    and task.work_item_id == item.work_item_id
                    and task.head_sha == item.head_sha
                ):
                    outcome = (
                        SpecificationResult.model_validate_json(stored)
                        if task.kind == "NEXT_SPEC"
                        else ArchitectureResult.model_validate_json(stored)
                    )
        if outcome is not None:
            state = publish_architecture_result(orchestrator, github, item.work_item_id, outcome)
    return state


def publish_architecture_result(
    orchestrator: Orchestrator,
    github: GitHubClient,
    work_item: str,
    outcome: ArchitectureResult | SpecificationResult,
) -> State:
    """Ingest only an authorized bridge result; recover from durable result without a new call."""
    actor = orchestrator.policy.architecture_bridge_actor
    event = orchestrator.event(work_item, EventType.ARCH_REVIEW_STARTED)
    event.actor = actor
    authenticate(event, Role.ARCHITECT, orchestrator.policy)
    state, revision = orchestrator.store.load()
    item = state.work_items[work_item]
    orchestrator._active(state, item)
    if isinstance(outcome, SpecificationResult):
        if outcome.parent_work_item != work_item or item.status != Stage.CLOSED:
            raise GovernanceError("SPEC_PARENT_NOT_CLOSED")
        artifact_root = f"architecture/specifications/{outcome.work_item_id}"
        if f"{artifact_root}.json" not in state.artifacts:
            state.artifacts[f"{artifact_root}.json"] = outcome.model_dump_json(indent=2)
            state.artifacts[f"{artifact_root}.md"] = outcome.markdown
            orchestrator._audit(
                state,
                orchestrator.event(
                    work_item, EventType.TASK_DELIVERED, item.head_sha, result_path=artifact_root
                ),
            )
            orchestrator.store.save(state, revision)
        elif state.artifacts[f"{artifact_root}.json"] != outcome.model_dump_json(indent=2):
            raise GovernanceError("SPEC_ARTIFACT_ALREADY_EXISTS")
        authorization = orchestrator.policy.standard_work_execution_authorization
        if not authorization or outcome.work_item_id in state.work_items:
            return state
        new_item = WorkItem(
            work_item_id=outcome.work_item_id,
            kind="SPEC",
            parent_work_item=work_item,
            previous_work_item=work_item,
            created_at=orchestrator.now(),
            artifact_path=f"{artifact_root}.md",
            artifact_sha256=hashlib.sha256(outcome.markdown.encode()).hexdigest(),
            target_branch="feature/" + outcome.work_item_id.lower(),
            execution_authorization=authorization,
        )
        reader = GitHubArtifactReader(
            github, {new_item.artifact_path}, item.head_sha or "main", state.artifacts
        )
        orchestrator.register(new_item, reader, actor)
        published = orchestrator.event(new_item.work_item_id, EventType.SPEC_PUBLISHED)
        published.actor = actor
        return orchestrator.handle(published)
    if outcome.reviewed_head_sha != item.head_sha or outcome.work_item != work_item:
        raise GovernanceError("REVIEW_SHA_OR_IDENTITY_MISMATCH")
    if outcome.review_id not in state.reviews:
        if item.status != Stage.ARCHITECTURE_REVIEWING:
            event.input_sha = item.head_sha
            orchestrator.handle(event)
        review = outcome.model_copy(update={"reviewed_at": orchestrator.now()})
        state = dispatch_command(
            orchestrator,
            github,
            Path.cwd(),
            actor,
            "review",
            {"work_item_id": work_item, "review": review.model_dump(mode="json")},
        )
    if (
        outcome.result == "CHANGES_REQUIRED"
        and state.work_items[work_item].status == Stage.CHANGES_REQUIRED
    ):
        state, revision = orchestrator.store.load()
        path = f"fixes/{work_item}/FIX-{work_item}-{outcome.review_id}.md"
        if path not in state.artifacts:
            state.artifacts[path] = render_fix(outcome)
            orchestrator._audit(
                state,
                orchestrator.event(
                    work_item, EventType.TASK_DELIVERED, item.head_sha, fix_path=path
                ),
            )
            orchestrator.store.save(state, revision)
        published = orchestrator.event(
            work_item, EventType.FIX_PUBLISHED, item.head_sha, fix_path=path
        )
        published.actor = actor
        state = orchestrator.handle(published)
    return state


def render_fix(review: ArchitectureResult) -> str:
    return (
        f"# FIX — {review.work_item} / {review.review_id}\n\n"
        f"Reviewed HEAD: {review.reviewed_head_sha}\n\n"
        "## Scope\n\nResolve the following Architecture Review blockers "
        "within the approved SPEC.\n\n"
        + "\n".join(f"- {item}" for item in review.blocking_items)
        + "\n\n## Non-scope\n\nNo Master Requirement, permission or "
        "investment-policy expansion.\n\n"
        "## Tests and quality gates\n\nAdd regression tests for each blocker; run all repository "
        "tests, coverage, architecture tests, Ruff, mypy and WPF/CI.\n\n"
        "## Review output and acceptance\n\nUpdate REVIEW; demonstrate each blocker resolved "
        "at the new exact HEAD. Prior approval is invalid.\n\n"
        "## Stop condition\n\nCommit, push, keep PR Draft and await Architecture Review. "
        "No self-merge.\n"
    )


def dispatch_command(
    orchestrator: Orchestrator,
    github: GitHubClient,
    root: Path,
    actor: str,
    command: str,
    payload: dict[str, Any],
) -> State:
    state, _ = orchestrator.store.load()
    work_item = payload.get("work_item_id") or state.current_work_item
    if command == "initialize":
        raise GovernanceError("BOOTSTRAP_ENTRYPOINT_REQUIRED")
    if command == "register":
        item = WorkItem.model_validate(payload["work_item"])
        authorization = orchestrator.event(item.work_item_id, EventType.TASK_RESERVED)
        authorization.actor = actor
        authenticate(authorization, Role.ARCHITECT, orchestrator.policy)
        reader = GitHubArtifactReader(github, {item.artifact_path}, payload["approved_ref"])
        orchestrator.register(item, reader, actor)
        published = orchestrator.event(item.work_item_id, EventType.SPEC_PUBLISHED)
        published.actor = actor
        return orchestrator.handle(published)
    if not work_item or work_item not in state.work_items:
        raise GovernanceError("WORK_ITEM_UNKNOWN")
    if command == "review":
        review = ArchitectureResult.model_validate(payload["review"])
        kind = {
            "FINAL_APPROVED": EventType.ARCH_FINAL_APPROVED,
            "CHANGES_REQUIRED": EventType.ARCH_CHANGES_REQUIRED,
        }.get(review.result, EventType.ARCH_REVIEW_COMPLETED)
        event = orchestrator.event(work_item, kind, review.reviewed_head_sha)
        event.actor, event.timestamp = actor, review.reviewed_at
        return orchestrator.handle(event, review=review)
    if command in {"ready", "merge", "closeout"}:
        event = orchestrator.event(work_item, EventType.TASK_RESERVED)
        event.actor = actor
        authenticate(event, Role.CHAIRMAN, orchestrator.policy)
        if command == "ready":
            return orchestrator.ready(work_item)
        if command == "merge":
            return orchestrator.merge(work_item)
        return orchestrator.closeout(work_item, GitWorkspace(root))
    if command == "event":
        allowed = {
            EventType.SPEC_PUBLISHED,
            EventType.CODEX_STARTED,
            EventType.IMPLEMENTATION_COMPLETED,
            EventType.ARCH_REVIEW_STARTED,
            EventType.FIX_PUBLISHED,
            EventType.FIX_IMPLEMENTED,
            EventType.ENGINEERING_FAILED,
            EventType.ENGINEERING_RETRY,
            EventType.PAUSE_PIPELINE,
            EventType.RESUME_PIPELINE,
            EventType.DISABLE_AUTO_MERGE,
            EventType.RECOVERY_AUTHORIZED,
        }
        kind = EventType(payload["event_type"])
        if kind not in allowed:
            raise GovernanceError("EVENT_COMMAND_NOT_ALLOWED")
        event = orchestrator.event(
            work_item, kind, state.work_items[work_item].head_sha, **payload.get("metadata", {})
        )
        event.actor = actor
        if kind == EventType.FIX_PUBLISHED:
            fix_path = event.metadata.get("fix_path", "")
            ref = github.ref("main")
            if not ref:
                raise GovernanceError("MAIN_MISSING")
            GitHubArtifactReader(github, {fix_path}, ref).read(fix_path)
        return orchestrator.handle(event)
    if command == "attach-pr":
        event = orchestrator.event(work_item, EventType.TASK_RESERVED)
        event.actor = actor
        authenticate(event, Role.ENGINEER, orchestrator.policy)
        pr = github.pull_request(int(payload["pr_number"]))
        path = str(payload["review_artifact"])
        GitHubArtifactReader(github, {path}, pr.head_sha).read(path)
        return orchestrator.handle(
            orchestrator.event(work_item, EventType.PR_CREATED, pr.head_sha, review_artifact=path),
            pr=pr,
        )
    if command == "memory-update":
        event = orchestrator.event(work_item, EventType.TASK_RESERVED)
        event.actor = actor
        authenticate(event, Role.ARCHITECT, orchestrator.policy)
        if payload["reason"] not in MEMORY_TRIGGERS:
            raise GovernanceError("MEMORY_TRIGGER_INVALID")
        return orchestrator.handle(
            orchestrator.event(
                work_item, EventType.MEMORY_UPDATE_REQUIRED, reason=payload["reason"]
            )
        )
    raise GovernanceError("COMMAND_NOT_ALLOWLISTED")


def initialize_state(
    orchestrator: Orchestrator, github: GitHubClient, actor: str, payload: dict[str, Any]
) -> State:
    """Chairman imports the independently completed bootstrap closeout, once, after manual merge."""
    event = orchestrator.event("DEV-GOV-001", EventType.TASK_RESERVED)
    event.actor = actor
    authenticate(event, Role.CHAIRMAN, orchestrator.policy)
    state, revision = orchestrator.store.load()
    if revision is not None or state.work_items:
        raise GovernanceError("STATE_ALREADY_INITIALIZED")
    reference = payload.get("architecture_closeout_reference", "")
    if not isinstance(reference, str) or not reference.strip():
        raise GovernanceError("EXTERNAL_ARCHITECTURE_CLOSEOUT_REFERENCE_REQUIRED")
    reviewed_head = payload.get("reviewed_head_sha", "")
    if not isinstance(reviewed_head, str) or not re.fullmatch(r"[0-9a-f]{40}", reviewed_head):
        raise GovernanceError("BOOTSTRAP_REVIEWED_HEAD_REQUIRED")
    pr = github.pull_request(int(payload["pr_number"]))
    if (
        pr.state != "MERGED"
        or pr.branch != BOOTSTRAP_BRANCH
        or pr.head_sha != reviewed_head
        or not pr.merge_commit
        or github.ref(BOOTSTRAP_BRANCH) is not None
    ):
        raise GovernanceError("BOOTSTRAP_CLOSEOUT_NOT_COMPLETE")
    if github.tree(pr.head_sha) != github.tree(pr.merge_commit):
        raise GovernanceError("MERGE_TREE_REVIEW_REQUIRED")
    merge_commit = pr.merge_commit
    main = github.ref("main")
    if not main or not github.contains_commit(merge_commit, main):
        raise GovernanceError("BOOTSTRAP_MAIN_MISMATCH")
    ci = github.ci(pr, orchestrator.policy)
    if ci.status != "PASSED" or ci.head_sha != pr.head_sha:
        raise GovernanceError("BOOTSTRAP_CI_NOT_PASSED")
    descriptor = json.loads(github.file(".github/dev-governance/work-item.json", merge_commit))
    if (
        set(descriptor) != {"work_item_id", "spec_path", "review_path", "spec_sha256"}
        or descriptor["work_item_id"] != "DEV-GOV-001"
    ):
        raise GovernanceError("BOOTSTRAP_DESCRIPTOR_INVALID")
    spec = github.file(descriptor["spec_path"], merge_commit)
    github.file(descriptor["review_path"], merge_commit)
    if hashlib.sha256(spec.encode()).hexdigest() != descriptor["spec_sha256"]:
        raise GovernanceError("APPROVED_SPEC_HASH_MISMATCH")
    item = WorkItem(
        work_item_id="DEV-GOV-001",
        kind="DEV_GOV",
        status=Stage.CLOSED,
        created_at=orchestrator.now(),
        artifact_path=descriptor["spec_path"],
        artifact_sha256=hashlib.sha256(spec.encode()).hexdigest(),
        target_branch=BOOTSTRAP_BRANCH,
        execution_authorization="owner-authorized-bootstrap",
        pr_number=pr.number,
        head_sha=pr.head_sha,
        base_sha=pr.base_sha,
        review_artifact=descriptor["review_path"],
        architecture_status=ReviewStatus.FINAL_APPROVED,
        approved_head_sha=pr.head_sha,
        ci=ci,
        merge_commit=pr.merge_commit,
        closeout={
            "source": "Chairman import of external Architecture Closeout",
            "architecture_closeout_reference": reference,
            "main_sha": main,
            "merge_commit": pr.merge_commit,
            "head_sha": pr.head_sha,
        },
    )
    state.work_items[item.work_item_id] = item
    state.current_work_item = item.work_item_id
    orchestrator._audit(
        state,
        orchestrator.event(
            item.work_item_id,
            EventType.TASK_RESERVED,
            item.head_sha,
            reason="BOOTSTRAP_CLOSEOUT_IMPORTED",
            authorized_actor=actor,
            architecture_closeout_reference=reference,
        ),
    )
    orchestrator.store.save(state, None)
    # No NEXT_SPEC event; bootstrap activation does not itself authorize SPEC-010.
    return state


def run_bootstrap(root: Path) -> str:
    """Protected, one-shot bootstrap path; it never runs the autonomous tick loop."""
    policy = Policy.model_validate_json((root / "configs/dev-governance.json").read_text("utf-8"))
    if any(
        (
            policy.pipeline_enabled,
            policy.merge_enabled,
            policy.auto_ready,
            policy.bridge_authorized,
        )
    ):
        raise GovernanceError("BOOTSTRAP_REQUIRES_ALL_ACTIVATION_OFF")
    token = os.environ.get("GH_TOKEN", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    actor = os.environ.get("GITHUB_ACTOR", "")
    trusted_actor = os.environ.get("AIC_BOOTSTRAP_CHAIRMAN", "")
    if not token:
        raise GovernanceError("GITHUB_AUTHORIZATION_MISSING")
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or not event_path:
        raise GovernanceError("BOOTSTRAP_MANUAL_WORKFLOW_REQUIRED")
    if not actor or actor != trusted_actor:
        raise GovernanceError("BOOTSTRAP_CHAIRMAN_NOT_AUTHORIZED")
    raw = json.loads(Path(event_path).read_text("utf-8"))
    payload = json.loads(raw.get("inputs", {}).get("payload") or "{}")
    bootstrap_policy = policy.model_copy(deep=True)
    bootstrap_policy.principals[Role.CHAIRMAN] = [actor]
    bootstrap_policy.principals[Role.BOT] = ["github-actions[bot]"]
    with httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    ) as client:
        github = GitHubClient(client, policy.repository, attempts=policy.read_attempts)
        store = GitHubStateBranchStore(github)
        orchestrator = Orchestrator(store, github, bootstrap_policy, "github-actions[bot]")
        state = initialize_state(orchestrator, github, actor, payload)
    return dashboard(state)


def complete_deployment_setup(
    store: StateStore,
    static_policy: Policy,
    actor: str,
    config: DeploymentPolicyConfig,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> State:
    """Record the protected setup once; this function cannot activate or dispatch work."""
    state, revision = store.load()
    materialize_effective_policy(static_policy, state, activated=False)
    if state.deployment_setup is not None:
        raise GovernanceError("DEPLOYMENT_SETUP_ALREADY_COMPLETE")
    bootstrap = state.work_items.get("DEV-GOV-001")
    if (
        bootstrap is None
        or state.current_work_item != bootstrap.work_item_id
        or bootstrap.status != Stage.CLOSED
        or bootstrap.architecture_status != ReviewStatus.FINAL_APPROVED
        or bootstrap.ci.status != "PASSED"
        or not bootstrap.merge_commit
        or not bootstrap.closeout
        or bootstrap.next_spec_requested
    ):
        raise GovernanceError("BOOTSTRAP_CLOSEOUT_STATE_REQUIRED")
    validate_deployment_policy(config, actor)
    serialized = config.model_dump_json()
    validate_artifact_content(serialized)
    fingerprint = policy_fingerprint(config)
    timestamp = now()
    state.deployment_setup = DeploymentSetup(
        authorized_by=actor,
        setup_at=timestamp,
        policy_fingerprint=fingerprint,
        effective_policy=config,
    )
    state.events.append(
        Event(
            event_id=uuid4().hex,
            event_type=EventType.DEPLOYMENT_SETUP_COMPLETED,
            timestamp=timestamp,
            work_item_id=bootstrap.work_item_id,
            actor=actor,
            input_sha=bootstrap.head_sha,
            output_state=bootstrap.status,
            metadata={
                "policy_version": config.policy_version,
                "policy_fingerprint": fingerprint,
                "mode": config.mode,
                "bridge_mode": config.bridge_mode,
                "merge_enabled": str(config.merge_enabled).lower(),
                "auto_ready": str(config.auto_ready).lower(),
                "principals_configured": "true",
                "setup_completed": "true",
            },
        )
    )
    state.revision += 1
    store.save(state, revision)
    return state


def run_setup(root: Path) -> str:
    """Protected setup path; it records policy but never activates the normal runner."""
    static_policy = Policy.model_validate_json(
        (root / "configs/dev-governance.json").read_text("utf-8")
    )
    token = os.environ.get("GH_TOKEN", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    actor = os.environ.get("GITHUB_ACTOR", "")
    trusted_actor = os.environ.get("AIC_SETUP_CHAIRMAN", "")
    raw_policy = os.environ.get("AIC_DEPLOYMENT_POLICY", "")
    if not token:
        raise GovernanceError("GITHUB_AUTHORIZATION_MISSING")
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or not event_path:
        raise GovernanceError("DEPLOYMENT_SETUP_MANUAL_WORKFLOW_REQUIRED")
    if os.environ.get("AIC_PIPELINE_ENABLED") == "true":
        raise GovernanceError("DEPLOYMENT_SETUP_REQUIRES_PIPELINE_OFF")
    try:
        event = json.loads(Path(event_path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GovernanceError("DEPLOYMENT_SETUP_EVENT_INVALID") from error
    if not isinstance(event, dict):
        raise GovernanceError("DEPLOYMENT_SETUP_EVENT_INVALID")
    if not actor or actor != trusted_actor:
        raise GovernanceError("DEPLOYMENT_SETUP_CHAIRMAN_NOT_AUTHORIZED")
    if not raw_policy:
        raise GovernanceError("DEPLOYMENT_POLICY_REQUIRED")
    validate_artifact_content(raw_policy)
    config = DeploymentPolicyConfig.model_validate_json(raw_policy)
    with httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    ) as client:
        github = GitHubClient(
            client, static_policy.repository, attempts=static_policy.read_attempts
        )
        store = GitHubStateBranchStore(github)
        state = complete_deployment_setup(store, static_policy, actor, config)
    setup = state.deployment_setup
    if setup is None:  # Defensive narrowing after validated transition.
        raise GovernanceError("DEPLOYMENT_SETUP_INCOMPLETE")
    return dashboard(state) + f"\nDeployment policy: {setup.policy_fingerprint}"


def run(root: Path, *, gate_only: bool = False) -> str:
    static_policy = Policy.model_validate_json(
        (root / "configs/dev-governance.json").read_text("utf-8")
    )
    activated = os.environ.get("AIC_PIPELINE_ENABLED") == "true"
    if not gate_only and not activated:
        return "PIPELINE_DISABLED: read/audit remain available; no external effects."
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise GovernanceError("GITHUB_AUTHORIZATION_MISSING")
    with httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    ) as client:
        github = GitHubClient(
            client, static_policy.repository, attempts=static_policy.read_attempts
        )
        store = GitHubStateBranchStore(github)
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if not event_path:
            raise GovernanceError("AUTHENTICATED_EVENT_REQUIRED")
        raw = json.loads(Path(event_path).read_text("utf-8"))
        if gate_only:
            if "pull_request" not in raw:
                # main CI validates the published artifact baseline without mutating runtime state.
                return "MAIN_PUBLICATION_CHECK: bootstrap remains manual; tests enforce gates."
            pr = github.pull_request(raw["pull_request"]["number"])
            expected = os.environ.get("AIC_EXPECTED_HEAD")
            if expected != pr.head_sha:
                raise GovernanceError("CI_CHECKOUT_HEAD_STALE")
            check_governance(root, pr, store.load()[0], static_policy)
            return "AIC Development Governance Gate: PASSED"
        state, _ = store.load()
        policy = materialize_effective_policy(static_policy, state, activated=True)
        actor = os.environ.get("GITHUB_ACTOR", "")
        orchestrator = Orchestrator(store, github, policy, "github-actions[bot]")
        inputs = raw.get("inputs", {})
        if inputs and inputs.get("command") != "reconcile":
            payload = json.loads(inputs.get("payload") or "{}")
            dispatch_command(orchestrator, github, root, actor, inputs["command"], payload)
        with httpx.Client(
            headers={"Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", "")}
        ) as api:
            state, _ = store.load()
            for _ in range(8):
                previous_revision = state.revision
                state = tick(orchestrator, github, api, root)
                if state.revision == previous_revision:
                    break
        return dashboard(state)


def spec_hash(path: Path) -> str:
    return hashlib.sha256(path.read_text("utf-8").encode()).hexdigest()


def generate_review_context(
    root: Path, github: GitHubClient, number: int, state: State | None = None
) -> ReviewContext:
    """Generate external exact-HEAD evidence after commit, never commit its own identity."""
    pr = github.pull_request(number)
    state = state or State()
    changes = github.pages(f"/pulls/{number}/files")
    changed = [entry["filename"] for entry in changes]
    deleted = [entry["filename"] for entry in changes if entry["status"] == "removed"]
    adrs = [path for path in changed if path.startswith("docs/adr/") and path not in deleted]
    if state.work_items:
        item = resolve_work_item(pr, state).model_copy(deep=True)
    else:
        descriptor = json.loads((root / ".github/dev-governance/work-item.json").read_text("utf-8"))
        item = WorkItem(
            work_item_id=descriptor["work_item_id"],
            kind="DEV_GOV",
            status=Stage.REVIEW_REQUIRED,
            created_at=datetime.now(UTC),
            artifact_path=descriptor["spec_path"],
            artifact_sha256=descriptor["spec_sha256"],
            target_branch=pr.branch,
            execution_authorization="approved-bootstrap-descriptor",
            pr_number=pr.number,
            head_sha=pr.head_sha,
            base_sha=pr.base_sha,
            review_artifact=descriptor["review_path"],
        )
    item.base_sha = pr.base_sha
    item.head_sha = pr.head_sha
    selected = {
        *MEMORY_PATHS,
        *(set(changed) - set(deleted)),
        item.artifact_path,
        item.review_artifact,
    }
    reader = GitHubArtifactReader(github, selected, pr.head_sha, state_artifacts=state.artifacts)
    manifest = build_context(
        reader,
        item,
        changed,
        adrs,
        tests_summary="See REVIEW and exact HEAD CI Backend tests job",
        coverage_summary="See exact HEAD coverage artifact",
        deleted_files=deleted,
    )
    manifest.known_debt = ["ADMIN_SETUP_REQUIRED", "ARCHITECTURE_BRIDGE_AUTHORIZATION_REQUIRED"]
    # When a selected artifact exists in this exact checkout, verify it against its durable source.
    for entry in manifest.context_entries:
        local = root / entry.path
        if (
            local.is_file()
            and hashlib.sha256(local.read_text("utf-8").replace("\r\n", "\n").encode()).hexdigest()
            != entry.sha256
        ):
            raise GovernanceError("LOCAL_REMOTE_CONTEXT_MISMATCH")
    return manifest
