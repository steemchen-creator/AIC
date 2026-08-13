"""Immutable, explainable data-quality values."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, TypeVar

from aic_backend.data_foundation.validation import ValidationResult


class DataQualityFlag(StrEnum):
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    SOURCE_FALLBACK = "SOURCE_FALLBACK"
    CONFLICTING_SOURCE = "CONFLICTING_SOURCE"
    SUSPICIOUS_VALUE = "SUSPICIOUS_VALUE"
    MISSING_OPTIONAL_FIELD = "MISSING_OPTIONAL_FIELD"
    UNKNOWN_SOURCE_TIMESTAMP = "UNKNOWN_SOURCE_TIMESTAMP"


class SourceClassification(StrEnum):
    OFFICIAL_EXCHANGE = "OFFICIAL_EXCHANGE"
    LICENSED_VENDOR = "LICENSED_VENDOR"
    PUBLIC_FINANCIAL_API = "PUBLIC_FINANCIAL_API"
    DERIVED_SOURCE = "DERIVED_SOURCE"
    UNKNOWN = "UNKNOWN"


def _score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


@dataclass(frozen=True, slots=True)
class DataQualityAssessment:
    score: float
    freshness_score: float
    completeness_score: float
    consistency_score: float
    source_confidence_score: float
    flags: tuple[DataQualityFlag, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "score",
            "freshness_score",
            "completeness_score",
            "consistency_score",
            "source_confidence_score",
        ):
            object.__setattr__(self, field, _score(getattr(self, field)))
        object.__setattr__(self, "flags", tuple(sorted(set(self.flags), key=str)))


@dataclass(frozen=True, slots=True)
class ConflictValue:
    provider_id: str
    value: Decimal
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id must not be empty")
        if not isinstance(self.value, Decimal):
            raise TypeError("conflict value must be Decimal")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("observed_at must include timezone information")


@dataclass(frozen=True, slots=True)
class DataConflict:
    record_identity: str
    field: str
    values: tuple[ConflictValue, ...]

    def __post_init__(self) -> None:
        if not self.record_identity.strip():
            raise ValueError("record_identity must not be empty")
        if not self.field.strip():
            raise ValueError("field must not be empty")
        if len(self.values) < 2:
            raise ValueError("conflict requires at least two source values")
        object.__setattr__(
            self,
            "values",
            tuple(sorted(self.values, key=lambda item: (item.provider_id, item.value))),
        )


@dataclass(frozen=True, slots=True)
class QualityContext:
    source_classification: SourceClassification = SourceClassification.UNKNOWN
    conflicts: tuple[DataConflict, ...] = ()
    unavailable_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted(self.conflicts, key=lambda item: (item.record_identity, item.field))),
        )
        if any(not field.strip() for field in self.unavailable_fields):
            raise ValueError("unavailable_fields must contain non-empty names")


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    fresh_threshold: timedelta = timedelta(days=1)
    stale_threshold: timedelta = timedelta(days=7)

    def __post_init__(self) -> None:
        if self.fresh_threshold < timedelta(0):
            raise ValueError("fresh_threshold must not be negative")
        if self.stale_threshold <= self.fresh_threshold:
            raise ValueError("stale_threshold must exceed fresh_threshold")


@dataclass(frozen=True, slots=True)
class CompletenessPolicy:
    optional_fields: tuple[str, ...]
    incomplete_threshold: float = 50.0

    def __post_init__(self) -> None:
        if len(set(self.optional_fields)) != len(self.optional_fields) or any(
            not field.strip() for field in self.optional_fields
        ):
            raise ValueError("optional_fields must be unique non-empty names")
        object.__setattr__(self, "incomplete_threshold", _score(self.incomplete_threshold))


@dataclass(frozen=True, slots=True)
class ComponentAssessment:
    score: float
    flags: tuple[DataQualityFlag, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _score(self.score))
        object.__setattr__(self, "flags", tuple(sorted(set(self.flags), key=str)))


class InvalidQualityInputError(ValueError):
    """Raised when Quality receives data that has not passed Validation."""


T_contra = TypeVar("T_contra", contravariant=True)


class DataQualityAssessor(Protocol[T_contra]):
    def assess(
        self,
        value: T_contra,
        *,
        reference_time: datetime,
        context: QualityContext,
        validation_result: ValidationResult,
    ) -> DataQualityAssessment: ...
