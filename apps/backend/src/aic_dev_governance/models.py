"""Versioned, deny-unknown-field wire contracts for the governance control plane."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, NonNegativeInt, field_validator

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Stage(StrEnum):
    PLANNED = "PLANNED"
    SPEC_READY = "SPEC_READY"
    IMPLEMENTING = "IMPLEMENTING"
    IMPLEMENTATION_COMPLETE = "IMPLEMENTATION_COMPLETE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ARCHITECTURE_REVIEWING = "ARCHITECTURE_REVIEWING"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    FIX_READY = "FIX_READY"
    FIXING = "FIXING"
    FINAL_APPROVED = "FINAL_APPROVED"
    MERGE_ELIGIBLE = "MERGE_ELIGIBLE"
    MERGING = "MERGING"
    MERGED = "MERGED"
    CLOSEOUT = "CLOSEOUT"
    CLOSED = "CLOSED"
    RECOVERABLE_FAILURE = "RECOVERABLE_FAILURE"
    BLOCKED = "BLOCKED"
    CHAIRMAN_DECISION_REQUIRED = "CHAIRMAN_DECISION_REQUIRED"
    FAILED = "FAILED"
    WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE = "WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE"


class EventType(StrEnum):
    SPEC_PUBLISHED = "SPEC_PUBLISHED"
    CODEX_STARTED = "CODEX_STARTED"
    IMPLEMENTATION_COMPLETED = "IMPLEMENTATION_COMPLETED"
    PR_CREATED = "PR_CREATED"
    PR_HEAD_CHANGED = "PR_HEAD_CHANGED"
    CI_STARTED = "CI_STARTED"
    CI_PASSED = "CI_PASSED"
    CI_FAILED = "CI_FAILED"
    REVIEW_REQUESTED = "REVIEW_REQUESTED"
    ARCH_REVIEW_STARTED = "ARCH_REVIEW_STARTED"
    ARCH_CHANGES_REQUIRED = "ARCH_CHANGES_REQUIRED"
    ARCH_REVIEW_COMPLETED = "ARCH_REVIEW_COMPLETED"
    FIX_PUBLISHED = "FIX_PUBLISHED"
    FIX_IMPLEMENTED = "FIX_IMPLEMENTED"
    ARCH_FINAL_APPROVED = "ARCH_FINAL_APPROVED"
    MERGE_GATE_PASSED = "MERGE_GATE_PASSED"
    MERGE_GATE_BLOCKED = "MERGE_GATE_BLOCKED"
    MERGE_STARTED = "MERGE_STARTED"
    PR_MERGED = "PR_MERGED"
    CLOSEOUT_STARTED = "CLOSEOUT_STARTED"
    CLOSEOUT_COMPLETED = "CLOSEOUT_COMPLETED"
    NEXT_SPEC_REQUESTED = "NEXT_SPEC_REQUESTED"
    CHAIRMAN_ESCALATION = "CHAIRMAN_ESCALATION"
    BUDGET_LIMIT_REACHED = "BUDGET_LIMIT_REACHED"
    GOVERNANCE_EXCEPTION = "GOVERNANCE_EXCEPTION"
    TASK_RESERVED = "TASK_RESERVED"
    TASK_DELIVERED = "TASK_DELIVERED"
    TASK_FAILED = "TASK_FAILED"
    ENGINEERING_FAILED = "ENGINEERING_FAILED"
    ENGINEERING_BRIDGE_UNAVAILABLE = "ENGINEERING_BRIDGE_UNAVAILABLE"
    ENGINEERING_RETRY = "ENGINEERING_RETRY"
    BRIDGE_UNAVAILABLE = "BRIDGE_UNAVAILABLE"
    OPERATION_FAILED = "OPERATION_FAILED"
    PAUSE_PIPELINE = "PAUSE_PIPELINE"
    RESUME_PIPELINE = "RESUME_PIPELINE"
    DISABLE_AUTO_MERGE = "DISABLE_AUTO_MERGE"
    MEMORY_UPDATE_REQUIRED = "MEMORY_UPDATE_REQUIRED"
    RECOVERY_AUTHORIZED = "RECOVERY_AUTHORIZED"
    SENSITIVE_DIFF_REVALIDATED = "SENSITIVE_DIFF_REVALIDATED"
    DEPLOYMENT_SETUP_COMPLETED = "DEPLOYMENT_SETUP_COMPLETED"
    DEPLOYMENT_POLICY_ROTATED = "DEPLOYMENT_POLICY_ROTATED"


class Role(StrEnum):
    CHAIRMAN = "CHAIRMAN"
    ARCHITECT = "CHIEF_INVESTMENT_ARCHITECT"
    ENGINEER = "CTO"
    BOT = "ORCHESTRATOR"


class ReviewStatus(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED_CANDIDATE = "APPROVED_CANDIDATE"
    APPROVED_WITH_NON_BLOCKING_DEBT = "APPROVED_WITH_NON_BLOCKING_DEBT"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    FINAL_APPROVED = "FINAL_APPROVED"


class Debt(Model):
    debt_id: Identifier
    origin_spec: Identifier
    description: str = Field(min_length=1, max_length=4000)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    blocking: bool
    target_phase: str
    status: Literal["OPEN", "RESOLVED"] = "OPEN"


class ArchitectureResult(Model):
    work_item: Identifier
    review_id: Identifier
    result: Literal[
        "APPROVED_CANDIDATE",
        "APPROVED_WITH_NON_BLOCKING_DEBT",
        "CHANGES_REQUIRED",
        "FINAL_APPROVED",
    ]
    reviewed_head_sha: Sha
    blocking_items: list[str]
    non_blocking_items: list[Debt]
    reviewed_at: datetime
    reviewer_role: Literal["CHIEF_INVESTMENT_ARCHITECT"]

    @field_validator("reviewed_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("TIMESTAMP_NOT_AWARE")
        return value


class Check(Model):
    name: str
    head_sha: Sha
    conclusion: str
    run_id: int = Field(gt=0)
    app_id: int = Field(gt=0)
    url: str


class SpecificationResult(Model):
    work_item_id: Identifier
    parent_work_item: Identifier
    title: str
    scope: str
    non_scope: str
    requirements: list[str]
    tests: list[str]
    quality_gates: list[str]
    review_output_requirement: str
    stop_condition: str
    markdown: str = Field(min_length=100, max_length=200000)


class PullRequest(Model):
    number: int = Field(gt=0)
    head_sha: Sha
    base_sha: Sha
    branch: str
    state: Literal["OPEN", "CLOSED", "MERGED"]
    draft: bool
    head_repository: str
    base_branch: str = "main"
    merge_commit: Sha | None = None


class CI(Model):
    head_sha: Sha | None = None
    status: Literal["UNKNOWN", "PENDING", "PASSED", "FAILED"] = "UNKNOWN"
    required_checks: dict[str, int | None] = Field(default_factory=dict)
    checks: list[Check] = Field(default_factory=list)
    discovery_complete: bool = False
    branch_protection_enabled: bool = False
    workflow_runs: list["WorkflowRun"] = Field(default_factory=list)


class WorkflowRun(Model):
    run_id: int = Field(gt=0)
    head_sha: Sha
    status: str
    conclusion: str | None
    attempt: int = Field(gt=0)
    url: str


class Budget(Model):
    architecture_calls_used: NonNegativeInt = 0
    review_loops: NonNegativeInt = 0
    duplicate_calls_avoided: NonNegativeInt = 0
    budget_limit_hits: NonNegativeInt = 0
    reserved_requests: list[str] = Field(default_factory=list)


class WorkItem(Model):
    work_item_id: Identifier
    kind: Literal["SPEC", "FIX", "GOVERNANCE_FIX", "DEV_GOV", "DOCUMENTATION"]
    parent_work_item: Identifier | None = None
    previous_work_item: Identifier | None = None
    status: Stage = Stage.PLANNED
    created_at: AwareDatetime
    artifact_path: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_branch: str = Field(pattern=r"^feature/[a-z0-9][a-z0-9-]+$")
    execution_authorization: str
    pr_number: int | None = None
    head_sha: Sha | None = None
    base_sha: Sha | None = None
    review_artifact: str | None = None
    architecture_status: ReviewStatus = ReviewStatus.NOT_REVIEWED
    approved_head_sha: Sha | None = None
    review_id: str | None = None
    ci: CI = Field(default_factory=CI)
    budget: Budget = Field(default_factory=Budget)
    blocked_reasons: list[str] = Field(default_factory=list)
    recoverable_failures: list[str] = Field(default_factory=list)
    recovery_stage: Stage | None = None
    unresolved_fix: str | None = None
    governance_exception: bool = False
    chairman_required: bool = False
    changed_areas: list[str] = Field(default_factory=list)
    merge_eligible: bool = False
    merge_commit: Sha | None = None
    merge_expected_sha: Sha | None = None
    closeout: dict[str, str] = Field(default_factory=dict)
    next_spec_requested: bool = False
    memory_update_required: bool = False


class DeploymentPolicyConfig(Model):
    """Non-secret effective values supplied only by the protected setup environment."""

    policy_version: Identifier
    pipeline_enabled: Literal[True] = True
    mode: Literal["MANUAL", "DRY_RUN"]
    merge_enabled: bool = False
    auto_ready: Literal[False] = False
    bridge_mode: Literal["MANUAL_BRIDGE", "CHATGPT_WORK_EVENT_BRIDGE", "OPENAI_API_BRIDGE"] = (
        "MANUAL_BRIDGE"
    )
    bridge_authorized: bool = False
    openai_model: str | None = None
    standard_work_execution_authorization: str = Field(min_length=1, max_length=500)
    principals: dict[Role, list[str]]


class DeploymentSetup(Model):
    status: Literal["COMPLETE"] = "COMPLETE"
    authorized_by: str = Field(min_length=1, max_length=200)
    setup_at: AwareDatetime
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_policy: DeploymentPolicyConfig


class DeploymentPolicyRotation(Model):
    """One immutable link in the post-setup deployment-policy audit chain."""

    previous_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorized_by: str = Field(min_length=1, max_length=200)
    rotated_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=4000)
    new_effective_policy: DeploymentPolicyConfig


class Event(Model):
    event_id: Identifier
    event_type: EventType
    timestamp: datetime
    work_item_id: Identifier
    actor: str = Field(min_length=1, max_length=200)
    input_sha: Sha | None = None
    output_state: Stage | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("TIMESTAMP_NOT_AWARE")
        return value


class Task(Model):
    task_id: Identifier
    work_item_id: Identifier
    kind: Literal["ENGINEERING", "ARCHITECTURE_REVIEW", "NEXT_SPEC"]
    head_sha: Sha | None = None
    artifact_path: str
    manifest_path: str | None = None
    status: Literal["RESERVED", "DELIVERED", "FAILED", "WAITING"] = "RESERVED"
    delivery_reference: str | None = None


class State(Model):
    schema_version: Literal["1.0"] = "1.0"
    project: Literal["AIC"] = "AIC"
    revision: NonNegativeInt = 0
    current_work_item: Identifier | None = None
    work_items: dict[str, WorkItem] = Field(default_factory=dict)
    events: list[Event] = Field(default_factory=list)
    tasks: dict[str, Task] = Field(default_factory=dict)
    reviews: dict[str, ArchitectureResult] = Field(default_factory=dict)
    technical_debt: dict[str, Debt] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    new_specs_by_day: dict[str, NonNegativeInt] = Field(default_factory=dict)
    paused: bool = False
    auto_merge_disabled: bool = False
    project_blocked_reasons: list[str] = Field(default_factory=list)
    deployment_setup: DeploymentSetup | None = None
    deployment_policy_rotations: list[DeploymentPolicyRotation] = Field(default_factory=list)


class Policy(Model):
    """Load ONLY from trusted main / protected runner configuration, never PR prose."""

    pipeline_enabled: bool = False
    merge_enabled: bool = False
    mode: Literal["MANUAL", "DRY_RUN", "AUTO"] = "MANUAL"
    auto_ready: bool = False
    method: Literal["squash"] = "squash"
    require_expected_head_sha: Literal[True] = True
    bridge_mode: Literal["MANUAL_BRIDGE", "CHATGPT_WORK_EVENT_BRIDGE", "OPENAI_API_BRIDGE"] = (
        "MANUAL_BRIDGE"
    )
    bridge_authorized: bool = False
    repository: str = "steemchen-creator/AIC"
    state_branch: Literal["automation/dev-state"] = "automation/dev-state"
    max_architecture_review_loops_per_work_item: int = Field(default=3, ge=1, le=20)
    max_architecture_calls_per_work_item: int = Field(default=5, ge=1, le=50)
    max_new_specs_per_day: int = Field(default=2, ge=1, le=20)
    duplicate_event_window_minutes: int = Field(default=30, ge=1, le=1440)
    read_attempts: int = Field(default=3, ge=1, le=5)
    openai_model: str | None = None
    architecture_bridge_actor: str = "openai-architecture-bridge"
    standard_work_execution_authorization: str | None = None
    trusted_check_app_id: int = 15368
    principals: dict[Role, list[str]] = Field(default_factory=dict)
    required_checks: list[str] = Field(
        default_factory=lambda: [
            "Governance baseline",
            "Backend tests",
            "Desktop build",
            "AIC Development Governance Gate",
        ]
    )


class GovernanceError(Exception):
    """Safe reason code; do not surface raw HTTP bodies, subprocess output or credentials."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
