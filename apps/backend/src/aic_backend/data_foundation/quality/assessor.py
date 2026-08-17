"""DailyBar data-quality composition without mutation or I/O."""

from datetime import datetime

from aic_backend.data_foundation.quality.models import (
    CompletenessPolicy,
    DataQualityAssessment,
    DataQualityFlag,
    FreshnessPolicy,
    InvalidQualityInputError,
    QualityContext,
)
from aic_backend.data_foundation.quality.policies import (
    assess_completeness,
    assess_consistency,
    assess_freshness,
    assess_source_confidence,
)
from aic_backend.data_foundation.validation import ValidationResult
from aic_backend.domain.market_data import DailyBar

FRESHNESS_WEIGHT = 0.30
COMPLETENESS_WEIGHT = 0.25
CONSISTENCY_WEIGHT = 0.25
SOURCE_CONFIDENCE_WEIGHT = 0.20


class DailyBarQualityAssessor:
    _COMPARABLE_FIELDS = frozenset(
        {"open", "high", "low", "close", "volume", "turnover"}
    )

    def __init__(
        self,
        freshness_policy: FreshnessPolicy | None = None,
        completeness_policy: CompletenessPolicy | None = None,
    ) -> None:
        self._freshness_policy = freshness_policy or FreshnessPolicy()
        self._completeness_policy = completeness_policy or CompletenessPolicy(
            ("turnover",)
        )

    def assess(
        self,
        value: DailyBar,
        *,
        reference_time: datetime,
        context: QualityContext,
        validation_result: ValidationResult,
    ) -> DataQualityAssessment:
        if not validation_result.valid:
            raise InvalidQualityInputError("Quality assessment requires valid data.")
        freshness = assess_freshness(
            value.event_time, reference_time, self._freshness_policy
        )
        completeness = assess_completeness(
            {"turnover": value.turnover},
            self._completeness_policy,
            context.unavailable_fields,
        )
        relevant_conflicts = tuple(
            conflict
            for conflict in context.conflicts
            if conflict.record_identity == value.record_id
        )
        consistency = assess_consistency(relevant_conflicts, self._COMPARABLE_FIELDS)
        confidence = assess_source_confidence(context.source_classification)
        flags = {
            *freshness.flags,
            *completeness.flags,
            *consistency.flags,
            *confidence.flags,
        }
        if value.provenance.received_via_failover:
            flags.add(DataQualityFlag.SOURCE_FALLBACK)
        if value.provenance.provider_timestamp is None:
            flags.add(DataQualityFlag.UNKNOWN_SOURCE_TIMESTAMP)
        score = (
            freshness.score * FRESHNESS_WEIGHT
            + completeness.score * COMPLETENESS_WEIGHT
            + consistency.score * CONSISTENCY_WEIGHT
            + confidence.score * SOURCE_CONFIDENCE_WEIGHT
        )
        return DataQualityAssessment(
            score=score,
            freshness_score=freshness.score,
            completeness_score=completeness.score,
            consistency_score=consistency.score,
            source_confidence_score=confidence.score,
            flags=tuple(flags),
        )
