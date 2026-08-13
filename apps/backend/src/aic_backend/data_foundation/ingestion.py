"""Raw-to-Canonical orchestration without persistence or Provider behavior."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from aic_backend.data_foundation.normalization import DataNormalizer, NormalizationError
from aic_backend.data_foundation.quality import (
    DataQualityAssessment,
    DataQualityAssessor,
    InvalidQualityInputError,
    QualityContext,
)
from aic_backend.data_foundation.validation import ValidationResult, Validator
from aic_backend.data_foundation.validation.candidates import DailyBarCandidate
from aic_backend.domain.market_data import DailyBar, DataProvenance, RawObservation


class IngestionFailureCode(StrEnum):
    RAW_OBSERVATION_ERROR = "RAW_OBSERVATION_ERROR"
    NORMALIZATION_ERROR = "NORMALIZATION_ERROR"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    QUALITY_INPUT_ERROR = "QUALITY_INPUT_ERROR"
    UNSUPPORTED_RECORD_TYPE = "UNSUPPORTED_RECORD_TYPE"


@dataclass(frozen=True, slots=True)
class IngestionSuccess:
    ingestion_id: str
    observation_id: str
    record_id: str
    record: DailyBar
    provenance: DataProvenance
    validation: ValidationResult
    quality: DataQualityAssessment


@dataclass(frozen=True, slots=True)
class IngestionFailure:
    ingestion_id: str
    observation_id: str
    provider_id: str
    code: IngestionFailureCode
    normalization_code: str | None = None
    field: str | None = None
    validation: ValidationResult | None = None


class DataIngestionPipeline:
    def __init__(
        self,
        normalizers: dict[str, DataNormalizer[DailyBar]],
        validator: Validator[DailyBarCandidate],
        assessor: DataQualityAssessor[DailyBar],
    ) -> None:
        self._normalizers = dict(normalizers)
        self._validator = validator
        self._assessor = assessor

    def ingest(
        self,
        *,
        ingestion_id: str,
        record_type: str,
        observation: RawObservation,
        reference_time: datetime,
        quality_context: QualityContext,
    ) -> IngestionSuccess | IngestionFailure:
        if not ingestion_id.strip():
            raise ValueError("ingestion_id must not be empty")
        normalizer = self._normalizers.get(record_type)
        if normalizer is None:
            return IngestionFailure(
                ingestion_id, observation.observation_id, observation.provider_id,
                IngestionFailureCode.UNSUPPORTED_RECORD_TYPE,
            )
        try:
            record = normalizer.normalize(observation)
        except NormalizationError as error:
            return IngestionFailure(
                ingestion_id, observation.observation_id, observation.provider_id,
                IngestionFailureCode.NORMALIZATION_ERROR, error.code.value, error.field,
            )
        validation = self._validator.validate(cast("DailyBarCandidate", record))
        if not validation.valid:
            return IngestionFailure(
                ingestion_id, observation.observation_id, observation.provider_id,
                IngestionFailureCode.VALIDATION_FAILED, validation=validation,
            )
        try:
            quality = self._assessor.assess(
                record,
                reference_time=reference_time,
                context=quality_context,
                validation_result=validation,
            )
        except InvalidQualityInputError:
            return IngestionFailure(
                ingestion_id, observation.observation_id, observation.provider_id,
                IngestionFailureCode.QUALITY_INPUT_ERROR, validation=validation,
            )
        return IngestionSuccess(
            ingestion_id, observation.observation_id, record.record_id, record,
            record.provenance, validation, quality,
        )
