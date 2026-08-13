"""Deterministic validators for canonical records and DailyBar candidates."""

from datetime import date
from decimal import Decimal

from aic_backend.data_foundation.validation.candidates import (
    CanonicalCandidate,
    DailyBarCandidate,
)
from aic_backend.data_foundation.validation.models import (
    ValidationContext,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from aic_backend.data_foundation.validation.rules import (
    error,
    validate_instrument,
    validate_provenance,
    validate_required_text,
    validate_safe_payload,
    validate_schema_version,
    validate_timestamp,
)


def _result(issues: list[ValidationIssue]) -> ValidationResult:
    return ValidationResult(
        errors=tuple(
            issue for issue in issues if issue.severity is ValidationSeverity.ERROR
        ),
        warnings=(),
    )


class CanonicalRecordValidator:
    def __init__(self, context: ValidationContext) -> None:
        self._context = context

    def validate(self, value: CanonicalCandidate) -> ValidationResult:
        issues: list[ValidationIssue] = []
        issues.extend(
            validate_required_text(value.record_id, "record_id", "RECORD_ID_EMPTY")
        )
        issues.extend(
            validate_required_text(value.record_type, "record_type", "RECORD_TYPE_EMPTY")
        )
        issues.extend(validate_schema_version(value.schema_version, self._context))
        for field in ("event_time", "observed_at", "ingested_at"):
            issues.extend(validate_timestamp(getattr(value, field), field, self._context))
        issues.extend(validate_provenance(value.provenance))
        if value.instrument is not None:
            issues.extend(validate_instrument(value.instrument))
        issues.extend(validate_safe_payload(value.payload))
        return _result(issues)


class DailyBarValidator:
    _PRICE_FIELDS = ("open", "high", "low", "close")

    def __init__(self, context: ValidationContext) -> None:
        self._context = context

    def validate(self, value: DailyBarCandidate) -> ValidationResult:
        issues: list[ValidationIssue] = []
        issues.extend(
            validate_required_text(value.record_id, "record_id", "RECORD_ID_EMPTY")
        )
        issues.extend(validate_schema_version(value.schema_version, self._context))
        issues.extend(validate_instrument(value.instrument))
        for field in ("event_time", "observed_at", "ingested_at"):
            issues.extend(validate_timestamp(getattr(value, field), field, self._context))
        issues.extend(validate_provenance(value.provenance))
        if not isinstance(value.trading_date, date):
            issues.append(
                error(
                    "DAILY_BAR_TRADING_DATE_INVALID",
                    "trading_date",
                    "trading date must be a date.",
                )
            )
        valid_prices: dict[str, Decimal] = {}
        for field in self._PRICE_FIELDS:
            price = getattr(value, field)
            if not isinstance(price, Decimal):
                issues.append(
                    error(
                        "DAILY_BAR_PRICE_TYPE_INVALID",
                        field,
                        f"{field} must be Decimal.",
                    )
                )
            else:
                valid_prices[field] = price
                if price < 0:
                    issues.append(
                        error(
                            "DAILY_BAR_PRICE_NEGATIVE",
                            field,
                            f"{field} must not be negative.",
                        )
                    )
        if len(valid_prices) == len(self._PRICE_FIELDS):
            high = valid_prices["high"]
            low = valid_prices["low"]
            if high < max(valid_prices["open"], valid_prices["close"], low):
                issues.append(
                    error(
                        "DAILY_BAR_HIGH_INVALID",
                        "high",
                        "high must not be below open, close, or low.",
                    )
                )
            if low > min(valid_prices["open"], valid_prices["close"], high):
                issues.append(
                    error(
                        "DAILY_BAR_LOW_INVALID",
                        "low",
                        "low must not exceed open, close, or high.",
                    )
                )
        if (
            not isinstance(value.volume, int)
            or isinstance(value.volume, bool)
            or value.volume < 0
        ):
            code = (
                "DAILY_BAR_VOLUME_NEGATIVE"
                if isinstance(value.volume, int)
                and not isinstance(value.volume, bool)
                and value.volume < 0
                else "DAILY_BAR_VOLUME_TYPE_INVALID"
            )
            issues.append(error(code, "volume", "volume must be a non-negative integer."))
        if not isinstance(value.turnover, Decimal):
            issues.append(
                error(
                    "DAILY_BAR_TURNOVER_TYPE_INVALID",
                    "turnover",
                    "turnover must be Decimal.",
                )
            )
        elif value.turnover < 0:
            issues.append(
                error(
                    "DAILY_BAR_TURNOVER_NEGATIVE",
                    "turnover",
                    "turnover must not be negative.",
                )
            )
        return _result(issues)
