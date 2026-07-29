from datetime import UTC, datetime

import pytest

from aic_backend.domain import DataRecord, DataRecordReceived


def test_data_record_copies_payload_and_is_immutable() -> None:
    payload: dict[str, object] = {"value": 42}
    record = DataRecord(
        record_id="sample-1",
        source="mock",
        payload=payload,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    payload["value"] = 100

    assert record.payload == {"value": 42}
    with pytest.raises(TypeError):
        record.payload["value"] = 100  # type: ignore[index]


@pytest.mark.parametrize("field", ["record_id", "source"])
def test_data_record_rejects_blank_identity_fields(field: str) -> None:
    values = {
        "record_id": "sample-1",
        "source": "mock",
        "payload": {},
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values[field] = " "

    with pytest.raises(ValueError):
        DataRecord(**values)  # type: ignore[arg-type]


def test_data_record_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        DataRecord(
            record_id="sample-1",
            source="mock",
            payload={},
            observed_at=datetime(2026, 1, 1),
        )


def test_data_record_received_copies_payload_and_is_immutable() -> None:
    payload: dict[str, object] = {"value": 42}
    event = DataRecordReceived(
        event_id="event-1",
        record_id="sample-1",
        source="mock",
        payload=payload,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    payload["value"] = 100

    assert event.payload == {"value": 42}
    with pytest.raises(TypeError):
        event.payload["value"] = 100  # type: ignore[index]


@pytest.mark.parametrize("field", ["event_id", "record_id"])
def test_data_record_received_rejects_blank_identity_fields(field: str) -> None:
    values = {
        "event_id": "event-1",
        "record_id": "sample-1",
        "source": "mock",
        "payload": {},
        "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values[field] = " "

    with pytest.raises(ValueError):
        DataRecordReceived(**values)  # type: ignore[arg-type]


def test_data_record_received_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        DataRecordReceived(
            event_id="event-1",
            record_id="sample-1",
            source="mock",
            payload={},
            occurred_at=datetime(2026, 1, 1),
        )
