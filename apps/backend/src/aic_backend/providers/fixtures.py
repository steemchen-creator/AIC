"""Deterministic Mock Provider fixtures for TASK-002."""

from datetime import UTC, datetime

from aic_backend.domain import DataRecord


def build_mock_records() -> tuple[DataRecord, ...]:
    """Return fresh, deterministic records for the configured Mock Provider."""

    return (
        DataRecord(
            record_id="sample-1",
            source="mock",
            payload={"value": 42},
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
