"""Read-only PR governance check. Bootstrap exception is narrow and explicitly temporary."""

import hashlib
import json
from pathlib import Path
from typing import cast

from .artifacts import ArtifactReader, safe_artifact_path, validate_artifact_content
from .models import GovernanceError, Policy, PullRequest, ReviewStatus, Stage, State, WorkItem

BOOTSTRAP_BASE = "1b9e3d50921751a9b016fcf4bb82a9d813a2bdd7"
BOOTSTRAP_BRANCH = "feature/dev-gov-001-autonomous-development-pipeline"


def resolve_work_item(pr: PullRequest, state: State) -> WorkItem:
    """Resolve normal PR identity only from durable state; partial matches fail closed."""
    candidates = [
        item
        for item in state.work_items.values()
        if item.pr_number == pr.number or item.target_branch == pr.branch
    ]
    if not candidates:
        raise GovernanceError("WORK_ITEM_NOT_RESOLVED")
    if len(candidates) != 1:
        raise GovernanceError("WORK_ITEM_IDENTITY_AMBIGUOUS")
    item = candidates[0]
    if (
        item.pr_number != pr.number
        or item.target_branch != pr.branch
        or item.head_sha != pr.head_sha
        or not item.review_artifact
    ):
        raise GovernanceError("STATE_PR_IDENTITY_MISMATCH")
    return item


def check_governance(root: Path, pr: PullRequest, state: State, policy: Policy) -> None:
    if not state.work_items:
        descriptor = json.loads((root / ".github/dev-governance/work-item.json").read_text("utf-8"))
        if set(descriptor) != {"work_item_id", "spec_path", "review_path", "spec_sha256"}:
            raise GovernanceError("WORK_ITEM_DESCRIPTOR_INVALID")
        reader = ArtifactReader(root, {descriptor["spec_path"], descriptor["review_path"]})
        spec = reader.read(descriptor["spec_path"])
        reader.read(descriptor["review_path"])
        if hashlib.sha256(spec.encode()).hexdigest() != descriptor["spec_sha256"]:
            raise GovernanceError("APPROVED_SPEC_HASH_MISMATCH")
        if not (
            descriptor["work_item_id"] == "DEV-GOV-001"
            and pr.branch == BOOTSTRAP_BRANCH
            and pr.base_sha == BOOTSTRAP_BASE
            and pr.head_repository == policy.repository
            and pr.state == "OPEN"
            and pr.draft
            and pr.base_branch == "main"
            and not policy.merge_enabled
        ):
            raise GovernanceError("STATE_MISSING_OR_BOOTSTRAP_SCOPE_INVALID")
        return
    item = resolve_work_item(pr, state)
    review_artifact = cast(str, item.review_artifact)
    reader = ArtifactReader(root, {review_artifact})
    reader.read(review_artifact)
    state_spec = state.artifacts.get(item.artifact_path)
    if state_spec is None:
        state_spec = ArtifactReader(root, {item.artifact_path}).read(item.artifact_path)
    else:
        safe_artifact_path(item.artifact_path)
        validate_artifact_content(state_spec)
    if hashlib.sha256(state_spec.encode()).hexdigest() != item.artifact_sha256:
        raise GovernanceError("APPROVED_SPEC_HASH_MISMATCH")
    if pr.state != "OPEN" or pr.base_branch != "main" or pr.head_repository != policy.repository:
        raise GovernanceError("PR_NOT_OPEN_OR_FOREIGN")
    if item.status in {Stage.MERGED, Stage.CLOSEOUT, Stage.CLOSED, Stage.MERGING}:
        raise GovernanceError("ILLEGAL_MERGE_STATE")
    if item.governance_exception or item.chairman_required or item.blocked_reasons:
        raise GovernanceError("WORK_ITEM_BLOCKED")
    if not pr.draft and (
        item.architecture_status != ReviewStatus.FINAL_APPROVED
        or item.approved_head_sha != pr.head_sha
    ):
        raise GovernanceError("READY_BEFORE_FINAL_APPROVAL")
    if item.approved_head_sha and item.approved_head_sha != pr.head_sha:
        raise GovernanceError("APPROVAL_STALE")
