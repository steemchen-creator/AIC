from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from aic_backend.data_foundation.validation import (
    ValidationContext,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 2, tzinfo=UTC)


def issue(
    code: str = "FIELD_INVALID",
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    field: str | None = "field",
) -> ValidationIssue:
    return ValidationIssue(code, severity, field, "A stable audit message.")


def test_validation_issue_is_immutable_and_preserves_fields() -> None:
    value = issue()
    assert value.code == "FIELD_INVALID"
    assert value.severity is ValidationSeverity.ERROR
    assert value.field == "field"
    assert value.message == "A stable audit message."
    with pytest.raises(FrozenInstanceError):
        value.code = "CHANGED"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"code": ""}, "code"),
        ({"code": "lowercase"}, "code"),
        ({"field": " "}, "field"),
        ({"message": " "}, "message"),
    ],
)
def test_validation_issue_rejects_invalid_identity(
    changes: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "code": "FIELD_INVALID",
        "severity": ValidationSeverity.ERROR,
        "field": None,
        "message": "message",
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        ValidationIssue(**values)  # type: ignore[arg-type]


def test_validation_result_derives_validity_and_sorts_issues() -> None:
    warning = issue("Z_WARNING", ValidationSeverity.WARNING, None)
    error_b = issue("B_ERROR", field="z")
    error_a = issue("A_ERROR", field="a")

    valid = ValidationResult(warnings=(warning,))
    invalid = ValidationResult(errors=(error_b, error_a))

    assert valid.valid is True
    assert valid.warnings == (warning,)
    assert invalid.valid is False
    assert [item.code for item in invalid.errors] == ["A_ERROR", "B_ERROR"]
    with pytest.raises(FrozenInstanceError):
        invalid.errors = ()  # type: ignore[misc]


def test_validation_result_rejects_misclassified_issues() -> None:
    with pytest.raises(ValueError, match="errors"):
        ValidationResult(errors=(issue(severity=ValidationSeverity.WARNING),))
    with pytest.raises(ValueError, match="warnings"):
        ValidationResult(warnings=(issue(),))


def test_validation_context_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="future"):
        ValidationContext(FixedClock(), timedelta(seconds=-1), frozenset({"1.0"}))
    with pytest.raises(ValueError, match="supported"):
        ValidationContext(FixedClock(), timedelta(0), frozenset())
    with pytest.raises(ValueError, match="supported"):
        ValidationContext(FixedClock(), timedelta(0), frozenset({" "}))
