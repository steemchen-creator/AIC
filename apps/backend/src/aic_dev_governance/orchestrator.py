"""Durable task orchestration. All external effects follow a persisted reservation."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Literal, Protocol
from uuid import uuid4

from .artifacts import ArtifactReader, ReviewContext, context_payload, validate_artifact_content
from .bridges import ArchitectureReviewTrigger, EngineeringWorkTrigger
from .budget import reserve_call
from .gates import automatic_merge_reasons, classify_changed_paths, evaluate_merge_eligibility
from .models import (
    CI,
    ArchitectureResult,
    Event,
    EventType,
    GovernanceError,
    Policy,
    PullRequest,
    Role,
    Stage,
    State,
    Task,
    WorkItem,
)
from .observability import log_operation
from .state_machine import apply_event, authenticate
from .store import StateStore

RECOVERABLE_ENGINEERING_FAILURES = {
    "CODEX_TASK_FAILED",
    "ENGINEERING_TASK_FAILED",
    "IMPLEMENTATION_FAILED",
}


class Repository(Protocol):
    def pull_request(self, number: int) -> PullRequest: ...
    def ci(self, pr: PullRequest, policy: Policy) -> CI: ...
    def merge(self, number: int, expected_head_sha: str) -> str: ...
    def tree(self, commit: str) -> str: ...
    def ref(self, branch: str) -> str | None: ...
    def delete_branch(self, branch: str, expected_sha: str) -> None: ...
    def mark_ready(self, number: int, expected_head_sha: str) -> None: ...
    def mark_draft(self, number: int, expected_head_sha: str) -> None: ...
    def changed_paths(self, number: int) -> list[str]: ...


class Workspace(Protocol):
    def closeout(self, branch: str, head: str, merge_commit: str, main: str) -> None: ...


class Orchestrator:
    def __init__(
        self,
        store: StateStore,
        repository: Repository,
        policy: Policy,
        actor: str,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.repository, self.policy, self.actor, self.now = (
            store,
            repository,
            policy,
            actor,
            now,
        )

    def event(
        self,
        work_item: str,
        kind: EventType,
        head: str | None = None,
        **metadata: str,
    ) -> Event:
        return Event(
            event_id=uuid4().hex,
            event_type=kind,
            timestamp=self.now(),
            work_item_id=work_item,
            actor=self.actor,
            input_sha=head,
            metadata=metadata,
        )

    def handle(
        self,
        event: Event,
        *,
        pr: PullRequest | None = None,
        ci: CI | None = None,
        review: ArchitectureResult | None = None,
    ) -> State:
        started = monotonic()
        state, revision = self.store.load()
        revalidated_paths = None
        if event.event_type == EventType.SENSITIVE_DIFF_REVALIDATED:
            authenticate(event, Role.CHAIRMAN, self.policy)
            item = state.work_items.get(event.work_item_id)
            if item is None:
                raise GovernanceError("WORK_ITEM_UNKNOWN")
            if not item.head_sha or event.input_sha != item.head_sha:
                raise GovernanceError("SENSITIVE_DIFF_REVALIDATION_STALE_HEAD")
            if not item.pr_number:
                raise GovernanceError("PR_IDENTITY_MISMATCH")
            # Ignore caller-supplied PRs. Read actual GitHub evidence at this invocation.
            pr = self.repository.pull_request(item.pr_number)
            if (
                pr.number != item.pr_number
                or pr.branch != item.target_branch
                or pr.head_repository != self.policy.repository
                or pr.base_branch != "main"
                or pr.state != "OPEN"
            ):
                raise GovernanceError("PR_IDENTITY_MISMATCH")
            if pr.head_sha != event.input_sha:
                raise GovernanceError("SENSITIVE_DIFF_REVALIDATION_STALE_HEAD")
            revalidated_paths = self.repository.changed_paths(pr.number)
            if classify_changed_paths(revalidated_paths):
                raise GovernanceError("SENSITIVE_DIFF_STILL_PRESENT")
            # The files endpoint is mutable. Refuse a head/base/identity change while reading it.
            if self.repository.pull_request(pr.number) != pr:
                raise GovernanceError("SENSITIVE_DIFF_REVALIDATION_PR_CHANGED")
            event = event.model_copy(
                update={
                    "metadata": {
                        "pr_number": str(pr.number),
                        "base_sha": pr.base_sha,
                        "changed_paths_sha256": hashlib.sha256(
                            json.dumps(sorted(revalidated_paths), separators=(",", ":")).encode()
                        ).hexdigest(),
                        "changed_path_count": str(len(revalidated_paths)),
                    }
                }
            )
        updated = apply_event(
            state,
            event,
            self.policy,
            pr=pr,
            ci=ci,
            review=review,
            revalidated_paths=revalidated_paths,
        )
        if updated.revision != state.revision:
            self.store.save(updated, revision)
        item = updated.work_items[event.work_item_id]
        log_operation(
            event.work_item_id,
            event.event_type,
            item.status,
            started,
            ai_calls=item.budget.architecture_calls_used,
        )
        return updated

    def register(self, item: WorkItem, reader: ArtifactReader, authorized_actor: str) -> State:
        state, revision = self.store.load()
        event = self.event(item.work_item_id, EventType.SPEC_PUBLISHED)
        event.actor = authorized_actor
        if authorized_actor in self.policy.principals.get(Role.CHAIRMAN, []):
            authenticate(event, Role.CHAIRMAN, self.policy)
        else:
            authenticate(event, Role.ARCHITECT, self.policy)
            if (
                not self.policy.standard_work_execution_authorization
                or item.execution_authorization != self.policy.standard_work_execution_authorization
            ):
                raise GovernanceError("DELEGATED_EXECUTION_AUTHORIZATION_MISSING")
        if not self.policy.pipeline_enabled or state.paused:
            raise GovernanceError("PIPELINE_DISABLED_OR_PAUSED")
        if item.work_item_id in state.work_items:
            raise GovernanceError("WORK_ITEM_ALREADY_EXISTS")
        current = state.work_items.get(state.current_work_item or "")
        previous = state.work_items.get(item.previous_work_item or "")
        if (
            current is not None
            and current.status != Stage.CLOSED
            or previous is None
            or previous.status != Stage.CLOSED
        ):
            raise GovernanceError("PREVIOUS_WORK_ITEM_NOT_CLOSED")
        if (
            item.status != Stage.PLANNED
            or item.approved_head_sha
            or item.merge_eligible
            or item.architecture_status != "NOT_REVIEWED"
            or item.pr_number is not None
            or item.head_sha is not None
            or item.ci.status != "UNKNOWN"
        ):
            raise GovernanceError("NEW_WORK_ITEM_STATE_INVALID")
        if not item.execution_authorization:
            raise GovernanceError("EXECUTION_AUTHORIZATION_MISSING")
        content = reader.read(item.artifact_path)
        if hashlib.sha256(content.encode()).hexdigest() != item.artifact_sha256:
            raise GovernanceError("APPROVED_SPEC_HASH_MISMATCH")
        state.work_items[item.work_item_id] = item.model_copy(deep=True)
        state.current_work_item = item.work_item_id
        # Registration is execution authorization, NOT SPEC publication / architecture approval.
        self._audit(
            state,
            self.event(
                item.work_item_id,
                EventType.TASK_RESERVED,
                reason="EXECUTION_AUTHORIZATION",
                authorized_actor=authorized_actor,
            ),
        )
        self.store.save(state, revision)
        return state

    def dispatch(
        self,
        work_item: str,
        kind: Literal["ENGINEERING", "ARCHITECTURE_REVIEW", "NEXT_SPEC"],
        *,
        engineering: EngineeringWorkTrigger | None = None,
        architecture: ArchitectureReviewTrigger | None = None,
        manifest: ReviewContext | None = None,
        reader: ArtifactReader | None = None,
    ) -> State:
        state, revision = self.store.load()
        item = state.work_items[work_item]
        self._active(state, item)
        if kind == "ENGINEERING":
            if item.status not in {Stage.SPEC_READY, Stage.FIX_READY} or engineering is None:
                raise GovernanceError("ENGINEERING_TASK_NOT_READY")
            artifact = item.unresolved_fix or item.artifact_path
            if reader is None:
                raise GovernanceError("PROJECT_MEMORY_REQUIRED")
            from .artifacts import MEMORY_PATHS

            for path in (*MEMORY_PATHS, artifact):
                reader.read(path)
            if (
                hashlib.sha256(reader.read(item.artifact_path).encode()).hexdigest()
                != item.artifact_sha256
            ):
                raise GovernanceError("APPROVED_SPEC_HASH_MISMATCH")
        elif kind in {"ARCHITECTURE_REVIEW", "NEXT_SPEC"}:
            expected = (
                {Stage.REVIEW_REQUIRED, Stage.WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE}
                if kind == "ARCHITECTURE_REVIEW"
                else {Stage.CLOSED}
            )
            if (
                item.status not in expected
                or architecture is None
                or manifest is None
                or reader is None
            ):
                raise GovernanceError("ARCHITECTURE_TASK_NOT_READY")
            if manifest.head_sha != item.head_sha or manifest.work_item_id != work_item:
                raise GovernanceError("REVIEW_SHA_OR_IDENTITY_MISMATCH")
            entries = {entry.path: entry.sha256 for entry in manifest.context_entries}
            if (
                manifest.spec_path != item.artifact_path
                or manifest.review_path != item.review_artifact
                or entries.get(item.artifact_path) != item.artifact_sha256
            ):
                raise GovernanceError("APPROVED_SPEC_HASH_MISMATCH")
            artifact = item.artifact_path
        else:
            raise GovernanceError("TASK_KIND_INVALID")
        key = hashlib.sha256(f"{work_item}:{kind}:{item.head_sha}:{artifact}".encode()).hexdigest()
        if key in state.tasks:
            # Including RESERVED after crash: never redeliver an uncertain model request.
            known_unavailable = state.tasks[key].status == "WAITING"
            if not (
                known_unavailable
                and self.policy.bridge_authorized
                and self.policy.bridge_mode != "MANUAL_BRIDGE"
            ):
                return state
        payload = context_payload(reader, manifest) if manifest is not None and reader else {}
        if kind != "ENGINEERING":
            try:
                reserve_call(
                    state,
                    item,
                    self.policy,
                    key,
                    self.now(),
                    new_spec=kind == "NEXT_SPEC",
                    review=kind == "ARCHITECTURE_REVIEW",
                )
            except GovernanceError as error:
                updated = apply_event(
                    state,
                    self.event(
                        work_item,
                        EventType.BUDGET_LIMIT_REACHED,
                        item.head_sha,
                        reason=error.reason,
                    ),
                    self.policy,
                )
                self.store.save(updated, revision)
                return updated
        task = Task(
            task_id=key,
            work_item_id=work_item,
            kind=kind,
            head_sha=item.head_sha,
            artifact_path=artifact,
        )
        if manifest:
            task.manifest_path = f"requests/{key}/REVIEW_CONTEXT.json"
            state.artifacts[task.manifest_path] = manifest.model_dump_json(indent=2)
            state.artifacts[f"requests/{key}/CONTEXT.json"] = json.dumps(
                payload, ensure_ascii=False
            )
        state.tasks[key] = task
        task_path = f"tasks/{key}.json"
        if task_path in state.artifacts:
            task_path = f"tasks/{key}/retry-{state.revision + 1}.json"
        state.artifacts[task_path] = task.model_dump_json(indent=2)
        self._audit(
            state, self.event(work_item, EventType.TASK_RESERVED, item.head_sha, task_id=key)
        )
        # A conflicting writer loses here, before the call or task publication.
        reserved_revision = self.store.save(state, revision)
        try:
            if kind == "ENGINEERING" and engineering is not None:
                reference = engineering.trigger_engineering(task, item.pr_number)
            elif architecture is not None and manifest is not None:
                reference = architecture.trigger(task, manifest, payload)
            else:
                raise GovernanceError("BRIDGE_UNAVAILABLE")
            if architecture is not None and architecture.result is not None:
                serialized = architecture.result.model_dump_json(indent=2)
                validate_artifact_content(serialized)
                state.artifacts[f"results/{key}.json"] = serialized
        except GovernanceError as error:
            waiting = error.reason in {
                "WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE",
                "ENGINEERING_BRIDGE_UNAVAILABLE",
            }
            task.status = "WAITING" if waiting else "FAILED"
            if waiting and key in item.budget.reserved_requests:
                # The adapter refused BEFORE an external call. Release only this known-unused
                # reservation; uncertain network failures never receive an automatic refund.
                item.budget.reserved_requests.remove(key)
                item.budget.architecture_calls_used -= 1
                if kind == "ARCHITECTURE_REVIEW":
                    item.budget.review_loops -= 1
                if kind == "NEXT_SPEC":
                    day = self.now().astimezone(UTC).date().isoformat()
                    state.new_specs_by_day[day] -= 1
            failure = (
                EventType.ENGINEERING_BRIDGE_UNAVAILABLE
                if waiting and kind == "ENGINEERING"
                else EventType.ENGINEERING_FAILED
                if kind == "ENGINEERING" and error.reason in RECOVERABLE_ENGINEERING_FAILURES
                else EventType.BRIDGE_UNAVAILABLE
                if waiting
                else EventType.TASK_FAILED
            )
            state = apply_event(
                state,
                self.event(work_item, failure, item.head_sha, reason=error.reason),
                self.policy,
            )
        else:
            task.status, task.delivery_reference = "DELIVERED", reference
            usage = architecture.usage if architecture is not None else {}
            self._audit(
                state,
                self.event(
                    work_item,
                    EventType.TASK_DELIVERED,
                    item.head_sha,
                    task_id=key,
                    **{name: str(value) for name, value in usage.items()},
                ),
            )
        state.artifacts[f"deliveries/{key}/{task.status}.json"] = task.model_dump_json(indent=2)
        self.store.save(state, reserved_revision)
        return state

    def reconcile(self, work_item: str) -> State:
        state, _ = self.store.load()
        item = state.work_items[work_item]
        if item.pr_number is None:
            raise GovernanceError("PR_MISSING")
        side_effect_attempted = False
        try:
            pr = self.repository.pull_request(item.pr_number)
            if pr.state == "MERGED":
                if item.status in {Stage.MERGED, Stage.CLOSEOUT, Stage.CLOSED}:
                    return state
                return self.handle(self.event(work_item, EventType.PR_MERGED, pr.head_sha), pr=pr)
            if pr.state != "OPEN":
                raise GovernanceError("PR_CLOSED_UNEXPECTEDLY")
            if pr.head_sha != item.head_sha:
                state = self.handle(
                    self.event(work_item, EventType.PR_HEAD_CHANGED, pr.head_sha), pr=pr
                )
                if not pr.draft:
                    side_effect_attempted = True
                    self.repository.mark_draft(pr.number, pr.head_sha)
                    side_effect_attempted = False
                    pr = self.repository.pull_request(pr.number)
                item = state.work_items[work_item]
            if not pr.draft and item.architecture_status != "FINAL_APPROVED":
                raise GovernanceError("PR_READY_BEFORE_FINAL_APPROVAL")
            sensitive = classify_changed_paths(self.repository.changed_paths(pr.number))
            if sensitive:
                return self.handle(
                    self.event(
                        work_item,
                        EventType.CHAIRMAN_ESCALATION,
                        pr.head_sha,
                        reason="SENSITIVE_DIFF:" + ",".join(sensitive),
                    )
                )
            ci = self.repository.ci(pr, self.policy)
            kind = {"PASSED": EventType.CI_PASSED, "FAILED": EventType.CI_FAILED}.get(
                ci.status,
                EventType.CI_STARTED,
            )
            return self.handle(self.event(work_item, kind, pr.head_sha), ci=ci)
        except GovernanceError as error:
            failure_class = "UNKNOWN_SIDE_EFFECT" if side_effect_attempted else "RECOVERABLE_READ"
            return self.handle(
                self.event(
                    work_item,
                    EventType.OPERATION_FAILED,
                    item.head_sha,
                    reason=error.reason,
                    failure_class=failure_class,
                )
            )

    def merge(self, work_item: str) -> State:
        self.reconcile(work_item)
        state, _ = self.store.load()
        item = state.work_items[work_item]
        self._active(state, item)
        if item.pr_number is None:
            raise GovernanceError("PR_MISSING")
        pr = self.repository.pull_request(item.pr_number)
        reasons = evaluate_merge_eligibility(item, pr, state, self.policy)
        if reasons:
            raise GovernanceError(reasons[0])
        state = self.handle(self.event(work_item, EventType.MERGE_GATE_PASSED, pr.head_sha), pr=pr)
        if self.policy.mode == "DRY_RUN":
            return state
        reasons = automatic_merge_reasons(item, state, self.policy)
        if reasons:
            raise GovernanceError(reasons[0])
        self.handle(self.event(work_item, EventType.MERGE_STARTED, pr.head_sha))
        try:
            self.repository.merge(pr.number, pr.head_sha)
        except GovernanceError as error:
            # Reconcile may reveal HEAD drift or a successful-but-unacknowledged merge.
            reconciled = self.reconcile(work_item)
            if reconciled.work_items[work_item].status in {Stage.MERGED, Stage.REVIEW_REQUIRED}:
                return reconciled
            return self.handle(
                self.event(work_item, EventType.OPERATION_FAILED, pr.head_sha, reason=error.reason)
            )
        return self.reconcile(work_item)

    def ready(self, work_item: str) -> State:
        state = self.reconcile(work_item)
        item = state.work_items[work_item]
        self._active(state, item)
        if not self.policy.auto_ready or item.work_item_id == "DEV-GOV-001":
            raise GovernanceError("AUTOMATIC_READY_DISABLED")
        if item.pr_number is None:
            raise GovernanceError("PR_MISSING")
        pr = self.repository.pull_request(item.pr_number)
        reasons = evaluate_merge_eligibility(item, pr, state, self.policy, ready_candidate=True)
        if reasons:
            raise GovernanceError(reasons[0])
        if pr.draft:
            self.repository.mark_ready(pr.number, pr.head_sha)
        return self.reconcile(work_item)

    def closeout(self, work_item: str, workspace: Workspace) -> State:
        state, _ = self.store.load()
        item = state.work_items[work_item]
        if item.status == Stage.CLOSED:
            if item.next_spec_requested:
                return state
            return self.handle(self.event(work_item, EventType.NEXT_SPEC_REQUESTED, item.head_sha))
        self._active(state, item)
        state = self.reconcile(work_item)
        item = state.work_items[work_item]
        if item.status not in {Stage.MERGED, Stage.CLOSEOUT} or item.pr_number is None:
            raise GovernanceError("CLOSEOUT_NOT_ALLOWED")
        try:
            pr = self.repository.pull_request(item.pr_number)
            if (
                pr.state != "MERGED"
                or pr.head_sha != item.approved_head_sha
                or pr.merge_commit != item.merge_commit
                or not pr.merge_commit
            ):
                raise GovernanceError("MERGE_EVIDENCE_MISMATCH")
            head_tree, merge_tree = (
                self.repository.tree(pr.head_sha),
                self.repository.tree(pr.merge_commit),
            )
            if head_tree != merge_tree:
                raise GovernanceError("MERGE_TREE_REVIEW_REQUIRED")
            main = self.repository.ref("main")
            if not main:
                raise GovernanceError("MAIN_MISSING")
            if item.status == Stage.MERGED:
                self.handle(self.event(work_item, EventType.CLOSEOUT_STARTED, pr.head_sha))
            workspace.closeout(item.target_branch, pr.head_sha, pr.merge_commit, main)
            self.repository.delete_branch(item.target_branch, pr.head_sha)
            if self.repository.ref(item.target_branch) is not None:
                raise GovernanceError("BRANCH_DELETION_FAILED")
            self.handle(
                self.event(
                    work_item,
                    EventType.CLOSEOUT_COMPLETED,
                    pr.head_sha,
                    merge_commit=pr.merge_commit,
                    tree_sha=merge_tree,
                    main_sha=main,
                    ci_head_sha=pr.head_sha,
                    local_branch_deleted="true",
                    remote_branch_deleted="true",
                    workspace_clean="true",
                )
            )
            return self.handle(self.event(work_item, EventType.NEXT_SPEC_REQUESTED, pr.head_sha))
        except GovernanceError as error:
            return self.handle(
                self.event(
                    work_item, EventType.OPERATION_FAILED, item.head_sha, reason=error.reason
                )
            )

    def _audit(self, state: State, event: Event) -> None:
        authenticate(event, Role.BOT, self.policy)
        event.output_state = state.work_items[event.work_item_id].status
        state.events.append(event)
        state.revision += 1

    def _active(self, state: State, item: WorkItem) -> None:
        authenticate(self.event(item.work_item_id, EventType.TASK_RESERVED), Role.BOT, self.policy)
        if (
            not self.policy.pipeline_enabled
            or state.paused
            or item.chairman_required
            or item.governance_exception
            or item.blocked_reasons
        ):
            raise GovernanceError("PIPELINE_DISABLED_PAUSED_OR_BLOCKED")
