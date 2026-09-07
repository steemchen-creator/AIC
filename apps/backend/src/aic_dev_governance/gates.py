"""Pure deterministic SHA/CI and merge predicates. No I/O and no model calls."""

from .models import CI, Policy, PullRequest, ReviewStatus, Stage, State, WorkItem


def classify_changed_paths(paths: list[str]) -> list[str]:
    """Conservative classification from actual diff paths, never from PR-body claims."""
    areas = set()
    for path in paths:
        folded = path.casefold()
        if folded in {"agents.md", "project_roadmap.md"} or folded.startswith("docs/project/"):
            areas.add("master_project_objective")
        if (
            folded.startswith(".github/")
            or folded == "configs/dev-governance.json"
            or "/shared/config" in folded
            or "/dev_governance/" in folded
            or "/aic_dev_governance/" in folded
        ):
            areas.add("secret_permission_model")
        for marker, area in (
            ("broker", "broker"),
            ("leverage", "leverage_permission"),
            ("live_trad", "production_trading"),
            ("portfolio/policies", "platform_risk_hard_cap"),
        ):
            if marker in folded:
                areas.add(area)
        risk_policy_surface = "risk" in folded and (
            folded.startswith("configs/")
            or "/policies/" in folded
            or "/policy/" in folded
            or "/limits/" in folded
            or any(marker in folded for marker in ("hard_cap", "risk_limit", "exposure_limit"))
        )
        if risk_policy_surface:
            areas.add("platform_risk_hard_cap")
    return sorted(areas)


FORBIDDEN_AREAS = frozenset(
    {
        "real_money",
        "broker",
        "leverage_permission",
        "max_leverage",
        "platform_risk_hard_cap",
        "production_trading",
        "master_project_objective",
        "commercial_regulatory_boundary",
        "secret_permission_model",
        "MASTER_REQUIREMENT_CHANGE",
        "SECURITY_POLICY_CHANGE",
        "LIVE_TRADING_CHANGE",
        "BROKER_PERMISSION_CHANGE",
        "LEVERAGE_PERMISSION_CHANGE",
        "RISK_HARD_CAP_RELAXATION",
        "GOVERNANCE_EXCEPTION",
    }
)


class ChairmanGatePolicy:
    def reasons(self, item: WorkItem) -> list[str]:
        return sorted(FORBIDDEN_AREAS.intersection(item.changed_areas))


def sha_ci_reasons(item: WorkItem, pr: PullRequest, policy: Policy) -> list[str]:
    reasons = []
    if item.head_sha != pr.head_sha:
        reasons.append("PR_HEAD_CHANGED")
    if item.approved_head_sha != pr.head_sha:
        reasons.append("APPROVAL_STALE")
    ci: CI = item.ci
    if ci.head_sha != pr.head_sha:
        reasons.append("CI_STALE")
    if not ci.discovery_complete:
        reasons.append("REQUIRED_CHECK_DISCOVERY_INCOMPLETE")
    if ci.status != "PASSED":
        reasons.append("CI_NOT_PASSED")
    if any(
        run.head_sha != pr.head_sha or run.status != "completed" or run.conclusion != "success"
        for run in ci.workflow_runs
    ):
        reasons.append("CI_WORKFLOW_STALE_OR_FAILED")
    required = {name: policy.trusted_check_app_id for name in policy.required_checks}
    required.update(
        {name: app or policy.trusted_check_app_id for name, app in ci.required_checks.items()}
    )
    for name, app in sorted(required.items()):
        checks = [check for check in ci.checks if check.name == name and check.app_id == app]
        if not checks:
            reasons.append(f"REQUIRED_CHECK_MISSING:{name}")
        elif any(c.head_sha != pr.head_sha or c.conclusion != "success" for c in checks):
            reasons.append(f"REQUIRED_CHECK_FAILED_OR_STALE:{name}")
    return reasons


def evaluate_merge_eligibility(
    item: WorkItem,
    pr: PullRequest,
    state: State,
    policy: Policy,
    *,
    ready_candidate: bool = False,
) -> list[str]:
    """An empty reason list means eligible; enabling execution is a separate gate."""
    reasons = sha_ci_reasons(item, pr, policy)
    if not policy.pipeline_enabled or state.paused:
        reasons.append("PIPELINE_DISABLED_OR_PAUSED")
    if item.status not in {Stage.FINAL_APPROVED, Stage.MERGE_ELIGIBLE, Stage.MERGING}:
        reasons.append("WORK_ITEM_NOT_APPROVED_STAGE")
    if item.blocked_reasons:
        reasons.append("WORK_ITEM_BLOCKED")
    if item.architecture_status != ReviewStatus.FINAL_APPROVED:
        reasons.append("ARCHITECTURE_NOT_FINAL")
    if pr.state != "OPEN":
        reasons.append("PR_NOT_OPEN")
    if pr.draft and not ready_candidate:
        reasons.append("PR_DRAFT")
    if pr.head_repository != policy.repository or pr.base_branch != "main":
        reasons.append("PR_REPOSITORY_OR_BASE_INVALID")
    if pr.branch != item.target_branch or pr.number != item.pr_number:
        reasons.append("PR_IDENTITY_MISMATCH")
    if item.unresolved_fix:
        reasons.append("UNRESOLVED_CHANGES_REQUIRED")
    if item.governance_exception:
        reasons.append("GOVERNANCE_EXCEPTION")
    if item.chairman_required or ChairmanGatePolicy().reasons(item):
        reasons.append("CHAIRMAN_DECISION_REQUIRED")
    previous = state.work_items.get(item.previous_work_item or "")
    if previous is None or previous.status != Stage.CLOSED:
        reasons.append("PREVIOUS_WORK_ITEM_NOT_CLOSED")
    if item.budget.budget_limit_hits:
        reasons.append("BUDGET_UNHEALTHY")
    if not item.ci.branch_protection_enabled:
        reasons.append("ADMIN_SETUP_REQUIRED")
    return reasons


def automatic_merge_reasons(item: WorkItem, state: State, policy: Policy) -> list[str]:
    reasons = []
    if item.work_item_id == "DEV-GOV-001":
        reasons.append("BOOTSTRAP_MANUAL_MERGE_ONLY")
    if not policy.merge_enabled or policy.mode != "AUTO" or state.auto_merge_disabled:
        reasons.append("AUTO_MERGE_DISABLED")
    return reasons
