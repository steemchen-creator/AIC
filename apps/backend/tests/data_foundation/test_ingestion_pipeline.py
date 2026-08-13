from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Never, cast

import pytest

from aic_backend.data_foundation import (
    DataIngestionPipeline,
    FixtureDailyBarNormalizer,
    IngestionFailure,
    IngestionFailureCode,
    IngestionSuccess,
    QualityContext,
    SourceClassification,
    create_raw_observation,
)
from aic_backend.data_foundation.quality import (
    ConflictDetector,
    ConflictValue,
    DailyBarQualityAssessor,
    DataQualityAssessment,
    DataQualityAssessor,
    DataQualityFlag,
    InvalidQualityInputError,
)
from aic_backend.data_foundation.validation import (
    DailyBarValidator,
    ValidationContext,
    ValidationResult,
)
from aic_backend.domain.market_data import DailyBar, DataCapability, RawObservation
from aic_backend.domain.market_data.models import InputValue, RawPayload

RECEIVED = datetime(2026, 1, 3, tzinfo=UTC)
EVENT = datetime(2026, 1, 2, 7, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return RECEIVED


def payload(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "schema": "1.0",
        "ticker": "600519",
        "market": "CN.SSE",
        "instrument_type": "EQUITY",
        "trade_day": "2026-01-02",
        "event_time": "2026-01-02T15:00:00+08:00",
        "o": "10.10",
        "h": "10.50",
        "l": "9.90",
        "c": "10.20",
        "vol": "100",
        "amount": "1010.00",
    }
    values.update(changes)
    return values


def observation(
    raw: dict[str, object] | str | bytes | None = None,
    *,
    failover: bool = False,
    metadata_changes: dict[str, object] | None = None,
) -> RawObservation:
    metadata: dict[str, object] = {
        "source_record_id": "fixture-1",
        "source_uri": "https://fixture.test/1",
        "provider_timestamp": "2026-01-02T15:00:01+08:00",
        "received_via_failover": failover,
        "failover_count": 1 if failover else 0,
    }
    metadata.update(metadata_changes or {})
    return create_raw_observation(
        observation_id="obs-1",
        provider_id="fixture-provider",
        capability=DataCapability.DAILY_BAR,
        received_at=RECEIVED,
        payload=cast("RawPayload", payload() if raw is None else raw),
        source_metadata=cast("Mapping[str, InputValue]", metadata),
    )


def pipeline(assessor: DataQualityAssessor[DailyBar] | None = None) -> DataIngestionPipeline:
    validator = DailyBarValidator(
        ValidationContext(FixedClock(), timedelta(minutes=5), frozenset({"1.0"}))
    )
    return DataIngestionPipeline(
        {DailyBar.RECORD_TYPE: FixtureDailyBarNormalizer()},
        validator,
        assessor or DailyBarQualityAssessor(),
    )


def ingest(
    raw: RawObservation | None = None,
    *,
    context: QualityContext | None = None,
    reference_time: datetime = RECEIVED,
) -> IngestionSuccess | IngestionFailure:
    return pipeline().ingest(
        ingestion_id="ing-1",
        record_type=DailyBar.RECORD_TYPE,
        observation=raw or observation(),
        reference_time=reference_time,
        quality_context=context or QualityContext(SourceClassification.OFFICIAL_EXCHANGE),
    )


def test_successful_fixture_daily_bar_e2e_is_traceable() -> None:
    result = ingest()
    assert isinstance(result, IngestionSuccess)
    assert result.ingestion_id == "ing-1"
    assert result.observation_id == "obs-1"
    assert result.record_id == result.record.record_id
    assert result.validation.valid is True
    assert result.quality.score == 100.0
    assert result.record.instrument.canonical_key == "CN.SSE.600519"
    assert result.record.trading_date.isoformat() == "2026-01-02"
    assert result.record.event_time == EVENT
    assert result.record.open == Decimal("10.10")
    assert result.provenance.provider_id == "fixture-provider"
    assert result.provenance.raw_payload_hash == observation().payload_hash
    assert result.provenance.transformation_version == "fixture-daily-bar-v1"


def test_mapping_order_has_same_hash_record_and_result() -> None:
    first = payload()
    second = dict(reversed(tuple(first.items())))
    left = observation(first)
    right = observation(second)
    left_result = ingest(left)
    right_result = ingest(right)
    assert left.payload_hash == right.payload_hash
    assert isinstance(left_result, IngestionSuccess)
    assert isinstance(right_result, IngestionSuccess)
    assert left_result.record == right_result.record
    assert left_result.quality == right_result.quality


@pytest.mark.parametrize(
    ("changes", "normalization_code"),
    [
        ({"c": None}, "NORMALIZATION_INVALID_TYPE"),
        ({"c": "not-number"}, "NORMALIZATION_INVALID_VALUE"),
        ({"schema": "2.0"}, "NORMALIZATION_UNSUPPORTED_SCHEMA"),
        ({"market": "UNKNOWN"}, "NORMALIZATION_INVALID_VALUE"),
    ],
)
def test_normalization_failure_is_structured(
    changes: dict[str, object], normalization_code: str
) -> None:
    raw = payload(**changes)
    if changes == {"c": None}:
        del raw["c"]
        normalization_code = "NORMALIZATION_MISSING_FIELD"
    result = ingest(observation(raw))
    assert isinstance(result, IngestionFailure)
    assert result.code is IngestionFailureCode.NORMALIZATION_ERROR
    assert result.normalization_code == normalization_code
    assert result.observation_id == "obs-1"
    assert result.provider_id == "fixture-provider"


def test_non_mapping_and_unsupported_record_type_fail_explicitly() -> None:
    invalid = ingest(observation("raw"))
    unsupported = pipeline().ingest(
        ingestion_id="ing-1",
        record_type="UNKNOWN",
        observation=observation(),
        reference_time=RECEIVED,
        quality_context=QualityContext(),
    )
    assert isinstance(invalid, IngestionFailure)
    assert invalid.normalization_code == "NORMALIZATION_INVALID_TYPE"
    assert isinstance(unsupported, IngestionFailure)
    assert unsupported.code is IngestionFailureCode.UNSUPPORTED_RECORD_TYPE


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"ticker": 1}, "ticker"),
        ({"ticker": " "}, "ticker"),
        ({"o": True}, "o"),
        ({"vol": None}, "vol"),
        ({"vol": False}, "vol"),
        ({"vol": "one"}, "vol"),
        ({"trade_day": "not-date"}, "trade_day"),
        ({"event_time": "not-time"}, "event_time"),
        ({"event_time": "2026-01-02T15:00:00"}, "event_time"),
    ],
)
def test_parsing_errors_remain_structured(changes: dict[str, object], field: str) -> None:
    result = ingest(observation(payload(**changes)))
    assert isinstance(result, IngestionFailure)
    assert result.code is IngestionFailureCode.NORMALIZATION_ERROR
    assert result.field == field


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"source_record_id": None}, None),
        ({"source_uri": 1}, "source_uri"),
        ({"provider_timestamp": None}, None),
        ({"received_via_failover": "false"}, "received_via_failover"),
    ],
)
def test_source_metadata_is_parsed_without_guessing(
    changes: dict[str, object], field: str | None
) -> None:
    result = ingest(observation(metadata_changes=changes))
    if field is None:
        assert isinstance(result, IngestionSuccess)
    else:
        assert isinstance(result, IngestionFailure)
        assert result.field == field


class CountingAssessor:
    def __init__(self) -> None:
        self.calls = 0

    def assess(
        self,
        value: DailyBar,
        *,
        reference_time: datetime,
        context: QualityContext,
        validation_result: object,
    ) -> Never:
        del value, reference_time, context, validation_result
        self.calls += 1
        raise AssertionError("Quality must not run after validation failure")


class RejectingAssessor:
    def assess(
        self,
        value: DailyBar,
        *,
        reference_time: datetime,
        context: QualityContext,
        validation_result: ValidationResult,
    ) -> DataQualityAssessment:
        del value, reference_time, context, validation_result
        raise InvalidQualityInputError("rejected")


def test_quality_input_failure_is_structured() -> None:
    result = pipeline(RejectingAssessor()).ingest(
        ingestion_id="ing-1",
        record_type=DailyBar.RECORD_TYPE,
        observation=observation(),
        reference_time=RECEIVED,
        quality_context=QualityContext(),
    )
    assert isinstance(result, IngestionFailure)
    assert result.code is IngestionFailureCode.QUALITY_INPUT_ERROR
    assert result.validation is not None and result.validation.valid


@pytest.mark.parametrize("changes", [{"h": "1"}, {"vol": "-1"}])
def test_validation_failure_stops_before_quality(changes: dict[str, object]) -> None:
    assessor = CountingAssessor()
    result = pipeline(assessor).ingest(
        ingestion_id="ing-1",
        record_type=DailyBar.RECORD_TYPE,
        observation=observation(payload(**changes)),
        reference_time=RECEIVED,
        quality_context=QualityContext(),
    )
    assert isinstance(result, IngestionFailure)
    assert result.code is IngestionFailureCode.VALIDATION_FAILED
    assert result.validation is not None and not result.validation.valid
    assert assessor.calls == 0


def test_failover_provenance_and_quality_flag_are_propagated_once() -> None:
    result = ingest(observation(failover=True))
    assert isinstance(result, IngestionSuccess)
    assert result.provenance.received_via_failover is True
    assert result.provenance.failover_count == 1
    assert DataQualityFlag.SOURCE_FALLBACK in result.quality.flags


def test_reference_time_changes_quality_not_record_identity() -> None:
    fresh = ingest(reference_time=RECEIVED)
    stale = ingest(reference_time=RECEIVED + timedelta(days=10))
    assert isinstance(fresh, IngestionSuccess) and isinstance(stale, IngestionSuccess)
    assert fresh.record_id == stale.record_id
    assert fresh.record == stale.record
    assert fresh.quality.freshness_score != stale.quality.freshness_score


def test_conflict_context_reaches_existing_quality_engine() -> None:
    base = ingest()
    assert isinstance(base, IngestionSuccess)
    conflict = ConflictDetector().detect(
        base.record_id,
        "close",
        (
            ConflictValue("fixture-provider", Decimal("10.20")),
            ConflictValue("fixture-backup", Decimal("10.21")),
        ),
    )
    assert conflict is not None
    result = ingest(context=QualityContext(conflicts=(conflict,)))
    assert isinstance(result, IngestionSuccess)
    assert DataQualityFlag.CONFLICTING_SOURCE in result.quality.flags


def test_pipeline_is_deterministic_except_explicit_ingestion_identity_and_no_mutation() -> None:
    raw_payload = payload()
    raw = observation(raw_payload)
    context = QualityContext(SourceClassification.PUBLIC_FINANCIAL_API)
    first = pipeline().ingest(
        ingestion_id="ing-1", record_type=DailyBar.RECORD_TYPE, observation=raw,
        reference_time=RECEIVED, quality_context=context,
    )
    results = [
        pipeline().ingest(
            ingestion_id=f"ing-{index}", record_type=DailyBar.RECORD_TYPE,
            observation=raw, reference_time=RECEIVED, quality_context=context,
        )
        for index in range(100)
    ]
    assert isinstance(first, IngestionSuccess)
    assert all(isinstance(item, IngestionSuccess) for item in results)
    successful = cast("list[IngestionSuccess]", results)
    assert all(item.record == first.record and item.quality == first.quality for item in successful)
    assert raw_payload == payload()
    assert isinstance(raw.payload, MappingProxyType)
    assert context == QualityContext(SourceClassification.PUBLIC_FINANCIAL_API)


class BuggyNormalizer:
    transformation_version = "buggy-v1"

    def normalize(self, observation: RawObservation) -> DailyBar:
        del observation
        raise RuntimeError("programming bug")


def test_programming_error_is_not_converted_to_data_failure() -> None:
    validator = DailyBarValidator(
        ValidationContext(FixedClock(), timedelta(minutes=5), frozenset({"1.0"}))
    )
    service = DataIngestionPipeline(
        {DailyBar.RECORD_TYPE: BuggyNormalizer()}, validator, DailyBarQualityAssessor()
    )
    with pytest.raises(RuntimeError, match="programming bug"):
        service.ingest(
            ingestion_id="ing-1", record_type=DailyBar.RECORD_TYPE,
            observation=observation(), reference_time=RECEIVED,
            quality_context=QualityContext(),
        )


def test_blank_ingestion_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="ingestion_id"):
        pipeline().ingest(
            ingestion_id=" ", record_type=DailyBar.RECORD_TYPE,
            observation=observation(), reference_time=RECEIVED,
            quality_context=QualityContext(),
        )
