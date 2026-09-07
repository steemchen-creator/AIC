"""Derived telemetry, not model-triggering chatter. Absent timings remain unknown."""

import json
import logging
from time import monotonic

from .models import EventType, State


def log_operation(
    work_item: str, event: str, state: str, started: float, *, retry: int = 0, ai_calls: int = 0
) -> None:
    logging.getLogger("aic.dev_governance").info(
        json.dumps(
            {
                "work_item": work_item,
                "event": event,
                "state": state,
                "latency_ms": round((monotonic() - started) * 1000, 3),
                "retry": retry,
                "ai_calls": ai_calls,
            },
            sort_keys=True,
        )
    )


TIME_PAIRS = {
    "spec_to_pr_time": (EventType.SPEC_PUBLISHED, EventType.PR_CREATED),
    "pr_to_review_time": (EventType.PR_CREATED, EventType.ARCH_REVIEW_STARTED),
    "review_to_fix_time": (EventType.ARCH_CHANGES_REQUIRED, EventType.FIX_IMPLEMENTED),
    "approval_to_merge_time": (EventType.ARCH_FINAL_APPROVED, EventType.PR_MERGED),
    "merge_to_closeout_time": (EventType.PR_MERGED, EventType.CLOSEOUT_COMPLETED),
    "human_wait_time": (EventType.CHAIRMAN_ESCALATION, EventType.RESUME_PIPELINE),
}
MEMORY_TRIGGERS = {
    "major_architecture_decision",
    "new_asset_class",
    "new_chairman_policy",
    "major_governance_incident",
    "role_changes",
    "new_master_requirement",
    "major_roadmap_shift",
}


def metrics(state: State, work_item: str) -> dict[str, int | float | None]:
    item = state.work_items[work_item]
    result: dict[str, int | float | None] = {
        "architecture_calls_per_spec": item.budget.architecture_calls_used,
        "review_loops": item.budget.review_loops,
        "duplicate_calls_avoided": item.budget.duplicate_calls_avoided,
        "budget_limit_hits": item.budget.budget_limit_hits,
    }
    events = [event for event in state.events if event.work_item_id == work_item]
    result["merge_attempts"] = sum(e.event_type == EventType.MERGE_STARTED for e in events)
    result["failures"] = sum(
        e.event_type in {EventType.TASK_FAILED, EventType.OPERATION_FAILED} for e in events
    )
    for token_kind in ("input_tokens", "output_tokens", "total_tokens"):
        available = [
            int(e.metadata[token_kind])
            for e in events
            if e.event_type == EventType.TASK_DELIVERED and token_kind in e.metadata
        ]
        result[token_kind] = sum(available) if available else None
    for name, (start_kind, end_kind) in TIME_PAIRS.items():
        start = next((e.timestamp for e in events if e.event_type == start_kind), None)
        end = next((e.timestamp for e in events if e.event_type == end_kind), None)
        result[name] = (
            (end - start).total_seconds() if start is not None and end is not None else None
        )
    return result
