"""Immutable validation results and pure validation protocols."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, TypeVar

_ISSUE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ValidationSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    field: str | None
    message: str

    def __post_init__(self) -> None:
        if not _ISSUE_CODE.fullmatch(self.code):
            raise ValueError("code must be a stable uppercase identifier")
        if self.field is not None and not self.field.strip():
            raise ValueError("field must be None or non-empty")
        if not self.message.strip():
            raise ValueError("message must not be empty")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        if any(issue.severity is not ValidationSeverity.ERROR for issue in self.errors):
            raise ValueError("errors must contain only ERROR issues")
        if any(
            issue.severity is not ValidationSeverity.WARNING for issue in self.warnings
        ):
            raise ValueError("warnings must contain only WARNING issues")
        object.__setattr__(self, "errors", tuple(sorted(self.errors, key=_issue_key)))
        object.__setattr__(self, "warnings", tuple(sorted(self.warnings, key=_issue_key)))

    @property
    def valid(self) -> bool:
        return not self.errors


def _issue_key(issue: ValidationIssue) -> tuple[str, str]:
    return (issue.field or "", issue.code)


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class ValidationContext:
    clock: Clock
    max_future_skew: timedelta
    supported_schema_versions: frozenset[str]

    def __post_init__(self) -> None:
        if self.max_future_skew < timedelta(0):
            raise ValueError("max_future_skew must not be negative")
        if not self.supported_schema_versions or any(
            not version.strip() for version in self.supported_schema_versions
        ):
            raise ValueError("supported_schema_versions must contain non-empty values")


T_contra = TypeVar("T_contra", contravariant=True)


class Validator(Protocol[T_contra]):
    def validate(self, value: T_contra) -> ValidationResult: ...
