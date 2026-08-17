"""Pure, centralized component quality policies."""

from collections.abc import Mapping
from datetime import datetime

from aic_backend.data_foundation.quality.models import (
    CompletenessPolicy,
    ComponentAssessment,
    DataConflict,
    DataQualityFlag,
    FreshnessPolicy,
    SourceClassification,
)

SOURCE_CONFIDENCE_SCORES: Mapping[SourceClassification, float] = {
    SourceClassification.OFFICIAL_EXCHANGE: 100.0,
    SourceClassification.LICENSED_VENDOR: 90.0,
    SourceClassification.PUBLIC_FINANCIAL_API: 70.0,
    SourceClassification.DERIVED_SOURCE: 50.0,
    SourceClassification.UNKNOWN: 30.0,
}


def assess_freshness(
    event_time: datetime,
    reference_time: datetime,
    policy: FreshnessPolicy,
) -> ComponentAssessment:
    for value, field in ((event_time, "event_time"), (reference_time, "reference_time")):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone information")
    age = reference_time - event_time
    if age.total_seconds() < 0:
        raise ValueError("event_time must not be after reference_time")
    if age <= policy.fresh_threshold:
        return ComponentAssessment(100.0)
    if age >= policy.stale_threshold:
        return ComponentAssessment(0.0, (DataQualityFlag.STALE,))
    span = (policy.stale_threshold - policy.fresh_threshold).total_seconds()
    elapsed = (age - policy.fresh_threshold).total_seconds()
    return ComponentAssessment(100.0 * (1.0 - elapsed / span))


def assess_completeness(
    values: Mapping[str, object],
    policy: CompletenessPolicy,
    unavailable_fields: frozenset[str],
) -> ComponentAssessment:
    expected = tuple(
        field for field in policy.optional_fields if field not in unavailable_fields
    )
    if not expected:
        return ComponentAssessment(100.0)
    missing = tuple(field for field in expected if values.get(field) is None)
    score = 100.0 * (len(expected) - len(missing)) / len(expected)
    if not missing:
        return ComponentAssessment(score)
    flag = (
        DataQualityFlag.INCOMPLETE
        if score <= policy.incomplete_threshold
        else DataQualityFlag.MISSING_OPTIONAL_FIELD
    )
    return ComponentAssessment(score, (flag,))


def assess_consistency(
    conflicts: tuple[DataConflict, ...],
    comparable_fields: frozenset[str],
) -> ComponentAssessment:
    affected = {conflict.field for conflict in conflicts if conflict.field in comparable_fields}
    if not affected:
        return ComponentAssessment(100.0)
    score = 100.0 * (1.0 - len(affected) / len(comparable_fields))
    return ComponentAssessment(score, (DataQualityFlag.CONFLICTING_SOURCE,))


def assess_source_confidence(classification: object) -> ComponentAssessment:
    normalized = (
        classification
        if isinstance(classification, SourceClassification)
        else SourceClassification.UNKNOWN
    )
    score = SOURCE_CONFIDENCE_SCORES[normalized]
    return ComponentAssessment(score)
