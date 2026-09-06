"""Read-only PR governance check. Bootstrap exception is narrow and explicitly temporary."""

import hashlib
import json
from pathlib import Path

from .artifacts import ArtifactReader
from .models import GovernanceError, Policy, PullRequest, ReviewStatus, Stage, State

BOOTSTRAP_BASE = "1b9e3d50921751a9b016fcf4bb82a9d813a2bdd7"
BOOTSTRAP_BRANCH = "feature/dev-gov-001-autonomous-development-pipeline"


def check_governance(root: Path, pr: PullRequest, state: State, policy: Policy) -> None:
    descriptor = json.loads((root / ".github/dev-governance/work-item.json").read_text("utf-8"))
    if set(descriptor) != {"work_item_id", "spec_path", "review_path", "spec_sha256"}:
        raise GovernanceError("WORK_ITEM_DESCRIPTOR_INVALID")
    reader = ArtifactReader(root, {descriptor["spec_path"], descriptor["review_path"]})
    spec = reader.read(descriptor["spec_path"])
    reader.read(descriptor["review_path"])
    if hashlib.sha256(spec.encode()).hexdigest() != descriptor["spec_sha256"]:
        raise GovernanceError("APPROVED_SPEC_HASH_MISMATCH")
    item = state.work_items.get(descriptor["work_item_id"])
    if item is None:
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
    if (
        item.head_sha != pr.head_sha
        or item.target_branch != pr.branch
        or item.pr_number != pr.number
        or item.artifact_path != descriptor["spec_path"]
        or item.artifact_sha256 != descriptor["spec_sha256"]
        or item.review_artifact != descriptor["review_path"]
    ):
        raise GovernanceError("STATE_PR_IDENTITY_MISMATCH")
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
