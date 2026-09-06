from datetime import UTC, datetime

import pytest

from aic_dev_governance.models import (
    CI,
    Check,
    Policy,
    PullRequest,
    ReviewStatus,
    Role,
    Stage,
    State,
    WorkItem,
)


@pytest.fixture
def policy() -> Policy:
    return Policy(
        pipeline_enabled=True,
        merge_enabled=True,
        mode="AUTO",
        auto_ready=True,
        principals={
            Role.BOT: ["bot"],
            Role.ARCHITECT: ["architect"],
            Role.ENGINEER: ["engineer"],
            Role.CHAIRMAN: ["chairman"],
        },
    )


@pytest.fixture
def item(policy: Policy) -> WorkItem:
    return WorkItem(
        work_item_id="SPEC-TEST",
        kind="SPEC",
        previous_work_item="PREVIOUS",
        status=Stage.FINAL_APPROVED,
        created_at=datetime(2026, 9, 7, tzinfo=UTC),
        artifact_path="docs/specifications/SPEC-TEST.md",
        artifact_sha256="a" * 64,
        target_branch="feature/spec-test",
        execution_authorization="owner-delegation-reference",
        pr_number=12,
        head_sha="a" * 40,
        base_sha="b" * 40,
        review_artifact="REVIEW-TEST.md",
        architecture_status=ReviewStatus.FINAL_APPROVED,
        approved_head_sha="a" * 40,
        ci=CI(
            head_sha="a" * 40,
            status="PASSED",
            discovery_complete=True,
            branch_protection_enabled=True,
            checks=[
                Check(
                    name=name,
                    head_sha="a" * 40,
                    conclusion="success",
                    run_id=index + 1,
                    app_id=15368,
                    url="https://github.com/test/check",
                )
                for index, name in enumerate(policy.required_checks)
            ],
        ),
    )


@pytest.fixture
def pr(item: WorkItem, policy: Policy) -> PullRequest:
    return PullRequest(
        number=12,
        head_sha="a" * 40,
        base_sha="b" * 40,
        branch=item.target_branch,
        state="OPEN",
        draft=False,
        head_repository=policy.repository,
    )


@pytest.fixture
def state(item: WorkItem) -> State:
    previous = item.model_copy(deep=True)
    previous.work_item_id, previous.status = "PREVIOUS", Stage.CLOSED
    return State(
        current_work_item=item.work_item_id,
        work_items={item.work_item_id: item, "PREVIOUS": previous},
    )
