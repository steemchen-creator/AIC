from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.data_foundation import deterministic_record_id
from aic_backend.data_foundation.quality import (
    ConflictDetector,
    ConflictValue,
    DailyBarQualityAssessor,
    DataQualityFlag,
    InvalidQualityInputError,
    QualityContext,
    SourceClassification,
)
from aic_backend.data_foundation.validation import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)

EVENT_TIME = datetime(2026, 1, 2, tzinfo=UTC)


def bar(*, failover: bool = False, provider_timestamp: datetime | None = EVENT_TIME) -> DailyBar:
    instrument = InstrumentIdentity(Market.CN_SSE, "600519", InstrumentType.EQUITY)
    record_id = deterministic_record_id(instrument, DailyBar.RECORD_TYPE, EVENT_TIME)
    provenance = DataProvenance(
        "provider-1", None, None, provider_timestamp, failover, 1 if failover else 0,
        "a" * 64, "daily-v1",
    )
    return DailyBar(
        record_id, "1.0", instrument, date(2026, 1, 2), EVENT_TIME, EVENT_TIME,
        EVENT_TIME, provenance, Decimal("10"), Decimal("11"), Decimal("9"),
        Decimal("10.5"), 100, Decimal("1050"),
    )


def conflict(record_id: str, field: str = "close"):
    return ConflictDetector().detect(
        record_id,
        field,
        (
            ConflictValue("provider-1", Decimal("10.5")),
            ConflictValue("provider-2", Decimal("10.6")),
        ),
    )


def test_assessor_combines_explainable_fixed_weights() -> None:
    value = bar()
    assessment = DailyBarQualityAssessor().assess(
        value,
        reference_time=EVENT_TIME,
        context=QualityContext(SourceClassification.OFFICIAL_EXCHANGE),
        validation_result=ValidationResult(),
    )
    assert assessment.score == 100.0
    assert assessment.freshness_score == 100.0
    assert assessment.completeness_score == 100.0
    assert assessment.consistency_score == 100.0
    assert assessment.source_confidence_score == 100.0


def test_failover_and_unknown_timestamp_are_annotations_without_double_penalty() -> None:
    fallback = bar(failover=True, provider_timestamp=None)
    context = QualityContext(SourceClassification.LICENSED_VENDOR)
    assessment = DailyBarQualityAssessor().assess(
        fallback,
        reference_time=EVENT_TIME,
        context=context,
        validation_result=ValidationResult(),
    )
    assert assessment.source_confidence_score == 90.0
    assert assessment.score == 98.0
    assert assessment.flags == (
        DataQualityFlag.SOURCE_FALLBACK,
        DataQualityFlag.UNKNOWN_SOURCE_TIMESTAMP,
    )


def test_conflict_changes_consistency_without_selecting_source() -> None:
    value = bar()
    detected = conflict(value.record_id)
    assert detected is not None
    assessment = DailyBarQualityAssessor().assess(
        value,
        reference_time=EVENT_TIME,
        context=QualityContext(conflicts=(detected,)),
        validation_result=ValidationResult(),
    )
    assert assessment.consistency_score == 83.33
    assert DataQualityFlag.CONFLICTING_SOURCE in assessment.flags


def test_irrelevant_conflict_does_not_affect_record() -> None:
    value = bar()
    detected = conflict("another-record")
    assert detected is not None
    assessment = DailyBarQualityAssessor().assess(
        value,
        reference_time=EVENT_TIME,
        context=QualityContext(conflicts=(detected,)),
        validation_result=ValidationResult(),
    )
    assert assessment.consistency_score == 100.0


def test_quality_requires_a_valid_validation_result() -> None:
    invalid = ValidationResult(
        errors=(
            ValidationIssue(
                "RECORD_INVALID", ValidationSeverity.ERROR, None, "Record is invalid."
            ),
        )
    )
    with pytest.raises(InvalidQualityInputError):
        DailyBarQualityAssessor().assess(
            bar(), reference_time=EVENT_TIME, context=QualityContext(),
            validation_result=invalid,
        )


def test_quality_does_not_change_record_identity_or_inputs() -> None:
    value = bar()
    context = QualityContext(SourceClassification.PUBLIC_FINANCIAL_API)
    original = replace(value)
    first = DailyBarQualityAssessor().assess(
        value, reference_time=EVENT_TIME, context=context,
        validation_result=ValidationResult(),
    )
    later = DailyBarQualityAssessor().assess(
        value, reference_time=EVENT_TIME + timedelta(days=6), context=context,
        validation_result=ValidationResult(),
    )
    assert value == original
    assert value.record_id == original.record_id
    assert first.freshness_score != later.freshness_score
    assert context == QualityContext(SourceClassification.PUBLIC_FINANCIAL_API)


def test_assessment_is_identical_100_times_and_batch_is_pure() -> None:
    value = bar()
    assessor = DailyBarQualityAssessor()
    kwargs = {
        "reference_time": EVENT_TIME + timedelta(days=4),
        "context": QualityContext(SourceClassification.DERIVED_SOURCE),
        "validation_result": ValidationResult(),
    }
    first = assessor.assess(value, **kwargs)  # type: ignore[arg-type]
    assert all(assessor.assess(value, **kwargs) == first for _ in range(100))  # type: ignore[arg-type]
    assert all(assessor.assess(value, **kwargs) == first for _ in range(10_000))  # type: ignore[arg-type]
