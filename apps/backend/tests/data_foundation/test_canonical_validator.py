from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

from aic_backend.data_foundation.validation import (
    CanonicalRecordValidator,
    ValidationContext,
)
from aic_backend.domain.market_data import (
    CanonicalRecord,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)

NOW = datetime(2026, 1, 3, tzinfo=UTC)


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def provenance() -> DataProvenance:
    return DataProvenance(
        "provider-1",
        "source-1",
        "https://example.test/1",
        datetime(2026, 1, 2, tzinfo=UTC),
        False,
        0,
        "a" * 64,
        "canonical-v1",
    )


def record() -> CanonicalRecord:
    return CanonicalRecord(
        "rec-1",
        "MARKET_SNAPSHOT",
        "1.0",
        InstrumentIdentity(Market.CN_SSE, "600519", InstrumentType.EQUITY),
        datetime(2026, 1, 2, 7, tzinfo=UTC),
        datetime(2026, 1, 2, 8, tzinfo=UTC),
        datetime(2026, 1, 2, 8, 0, 1, tzinfo=UTC),
        provenance(),
        {"price": Decimal("10.2"), "tags": ("official",)},
    )


def candidate(base: CanonicalRecord | None = None, **changes: object) -> SimpleNamespace:
    value = base or record()
    fields: dict[str, object] = {
        "record_id": value.record_id,
        "record_type": value.record_type,
        "schema_version": value.schema_version,
        "instrument": value.instrument,
        "event_time": value.event_time,
        "observed_at": value.observed_at,
        "ingested_at": value.ingested_at,
        "provenance": value.provenance,
        "payload": value.payload,
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def malformed_provenance(**changes: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "provider_id": "provider-1",
        "raw_payload_hash": "a" * 64,
        "transformation_version": "v1",
        "failover_count": 0,
        "received_via_failover": False,
        "provider_timestamp": datetime(2026, 1, 2, tzinfo=UTC),
        "source_uri": "https://example.test/1",
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def validator(clock: FixedClock | None = None) -> CanonicalRecordValidator:
    return CanonicalRecordValidator(
        ValidationContext(
            clock or FixedClock(), timedelta(minutes=5), frozenset({"1.0"})
        )
    )


def error_codes(value: object) -> tuple[str, ...]:
    result = validator().validate(value)  # type: ignore[arg-type]
    return tuple(issue.code for issue in result.errors)


def test_valid_canonical_record_passes() -> None:
    assert validator().validate(record()).valid is True


def test_structural_fields_and_schema_are_validated_together() -> None:
    result = validator().validate(
        candidate(record_id="", record_type=" ", schema_version="2.0")  # type: ignore[arg-type]
    )
    assert tuple(issue.code for issue in result.errors) == (
        "RECORD_ID_EMPTY",
        "RECORD_TYPE_EMPTY",
        "UNSUPPORTED_SCHEMA_VERSION",
    )

    assert "SCHEMA_VERSION_EMPTY" in error_codes(candidate(schema_version=""))


def test_aware_offsets_are_accepted_and_naive_or_future_times_rejected() -> None:
    plus_eight = timezone(timedelta(hours=8))
    aware = candidate(event_time=datetime(2026, 1, 2, 15, tzinfo=plus_eight))
    invalid = candidate(
        observed_at=datetime(2026, 1, 2),
        ingested_at=NOW + timedelta(minutes=6),
    )
    assert validator().validate(aware).valid is True  # type: ignore[arg-type]
    assert set(error_codes(invalid)) == {"TIMESTAMP_NAIVE", "TIMESTAMP_FUTURE"}


def test_provenance_collects_all_supported_issues() -> None:
    invalid = malformed_provenance(
        provider_id=" ",
        raw_payload_hash="bad",
        transformation_version="",
        failover_count=2,
        received_via_failover=False,
        provider_timestamp=datetime(2026, 1, 2),
        source_uri="https://user:pass@example.test/x?token=secret",
    )
    codes = set(error_codes(candidate(provenance=invalid)))
    assert codes == {
        "PROVENANCE_PROVIDER_ID_EMPTY",
        "PROVENANCE_RAW_HASH_INVALID",
        "PROVENANCE_TRANSFORMATION_VERSION_EMPTY",
        "PROVENANCE_FAILOVER_ATTRIBUTION_INVALID",
        "PROVENANCE_SOURCE_URI_SECRET",
        "TIMESTAMP_NAIVE",
    }


def test_provenance_rejects_invalid_count_and_blank_uri() -> None:
    invalid = malformed_provenance(failover_count=-1, source_uri=" ")
    assert set(error_codes(candidate(provenance=invalid))) == {
        "PROVENANCE_FAILOVER_COUNT_INVALID",
        "PROVENANCE_SOURCE_URI_INVALID",
    }


def test_invalid_instrument_and_unsafe_payload_are_reported() -> None:
    result_codes = set(
        error_codes(candidate(instrument="600519", payload={"opaque": object()}))
    )
    assert result_codes == {"INSTRUMENT_INVALID", "PAYLOAD_MUTABLE"}

    assert error_codes(candidate(instrument=None, payload="unsafe")) == (
        "PAYLOAD_UNSAFE",
    )


def test_instrument_fields_are_validated_without_provider_knowledge() -> None:
    invalid = InstrumentIdentity(Market.CN_SSE, "600519", InstrumentType.EQUITY)
    object.__setattr__(invalid, "market", "SSE")
    object.__setattr__(invalid, "symbol", "")
    object.__setattr__(invalid, "instrument_type", "STOCK")
    assert set(error_codes(candidate(instrument=invalid))) == {
        "INSTRUMENT_MARKET_INVALID",
        "INSTRUMENT_SYMBOL_EMPTY",
        "INSTRUMENT_TYPE_INVALID",
    }


def test_immutable_payload_safe_vocabulary_and_multi_issue_determinism() -> None:
    unsafe = MappingProxyType({"nested": MappingProxyType({"value": object()})})
    value = candidate(record_id="", payload=unsafe)
    first = validator().validate(value)  # type: ignore[arg-type]

    assert set(issue.code for issue in first.errors) == {"PAYLOAD_UNSAFE", "RECORD_ID_EMPTY"}
    assert all(validator().validate(value) == first for _ in range(100))  # type: ignore[arg-type]


def test_payload_datetime_must_be_aware() -> None:
    safe = MappingProxyType({"time": datetime(2026, 1, 2, tzinfo=UTC)})
    unsafe = MappingProxyType({"time": datetime(2026, 1, 2)})
    assert validator().validate(candidate(payload=safe)).valid is True  # type: ignore[arg-type]
    assert error_codes(candidate(payload=unsafe)) == ("PAYLOAD_UNSAFE",)


def test_validation_clock_must_be_timezone_aware() -> None:
    clock = FixedClock(datetime(2026, 1, 3))
    try:
        validator(clock).validate(record())
    except ValueError as error:
        assert "clock" in str(error)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("naive clock was accepted")
