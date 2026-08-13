"""Deterministic helpers for the real-data foundation."""

from aic_backend.data_foundation.canonical import create_raw_observation
from aic_backend.data_foundation.identity import (
    deterministic_record_id,
    raw_payload_hash,
)
from aic_backend.data_foundation.ingestion import (
    DataIngestionPipeline,
    IngestionFailure,
    IngestionFailureCode,
    IngestionSuccess,
)
from aic_backend.data_foundation.normalization import (
    DataNormalizer,
    FixtureDailyBarNormalizer,
    NormalizationError,
    NormalizationErrorCode,
)
from aic_backend.data_foundation.quality import (
    CompletenessPolicy,
    ConflictDetector,
    ConflictValue,
    DailyBarQualityAssessor,
    DataConflict,
    DataQualityAssessment,
    DataQualityFlag,
    FreshnessPolicy,
    InvalidQualityInputError,
    QualityContext,
    SourceClassification,
)
from aic_backend.data_foundation.validation import (
    CanonicalRecordValidator,
    DailyBarValidator,
    DataValidationService,
    ValidationContext,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

__all__ = [
    "CanonicalRecordValidator",
    "CompletenessPolicy",
    "ConflictDetector",
    "ConflictValue",
    "DailyBarValidator",
    "DailyBarQualityAssessor",
    "DataConflict",
    "DataIngestionPipeline",
    "DataNormalizer",
    "DataQualityAssessment",
    "DataQualityFlag",
    "DataValidationService",
    "FreshnessPolicy",
    "FixtureDailyBarNormalizer",
    "IngestionFailure",
    "IngestionFailureCode",
    "IngestionSuccess",
    "InvalidQualityInputError",
    "QualityContext",
    "NormalizationError",
    "NormalizationErrorCode",
    "SourceClassification",
    "ValidationContext",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "create_raw_observation",
    "deterministic_record_id",
    "raw_payload_hash",
]
