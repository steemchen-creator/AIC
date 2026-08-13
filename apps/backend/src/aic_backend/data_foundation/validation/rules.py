"""Pure structural and DailyBar semantic validation rules."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from urllib.parse import parse_qsl, urlsplit

from aic_backend.data_foundation.validation.models import (
    ValidationContext,
    ValidationIssue,
    ValidationSeverity,
)
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market

_SECRET_QUERY_FIELDS = frozenset(
    {"access_token", "api_key", "apikey", "auth", "key", "secret", "signature", "token"}
)


def error(code: str, field: str | None, message: str) -> ValidationIssue:
    return ValidationIssue(code, ValidationSeverity.ERROR, field, message)


def validate_required_text(value: object, field: str, code: str) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, str) or not value.strip():
        return (error(code, field, f"{field} must be a non-empty string."),)
    return ()


def validate_timestamp(
    value: object,
    field: str,
    context: ValidationContext,
) -> tuple[ValidationIssue, ...]:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return (error("TIMESTAMP_NAIVE", field, f"{field} must include timezone information."),)
    now = context.clock.now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("validation clock must return a timezone-aware datetime")
    if value > now + context.max_future_skew:
        return (error("TIMESTAMP_FUTURE", field, f"{field} exceeds the allowed future skew."),)
    return ()


def validate_instrument(value: object, field: str = "instrument") -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if not isinstance(value, InstrumentIdentity):
        return (error("INSTRUMENT_INVALID", field, "instrument must be an InstrumentIdentity."),)
    if not isinstance(value.market, Market):
        issues.append(error("INSTRUMENT_MARKET_INVALID", f"{field}.market", "market is invalid."))
    if not isinstance(value.symbol, str) or not value.symbol.strip():
        issues.append(error("INSTRUMENT_SYMBOL_EMPTY", f"{field}.symbol", "symbol is empty."))
    if not isinstance(value.instrument_type, InstrumentType):
        issues.append(
            error(
                "INSTRUMENT_TYPE_INVALID",
                f"{field}.instrument_type",
                "instrument type is invalid.",
            )
        )
    if not issues:
        _ = value.canonical_key
    return tuple(issues)


def validate_provenance(value: object) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    provider_id = getattr(value, "provider_id")
    raw_hash = getattr(value, "raw_payload_hash")
    transformation_version = getattr(value, "transformation_version")
    failover_count = getattr(value, "failover_count")
    received_via_failover = getattr(value, "received_via_failover")
    provider_timestamp = getattr(value, "provider_timestamp")
    source_uri = getattr(value, "source_uri")

    issues.extend(
        validate_required_text(
            provider_id, "provenance.provider_id", "PROVENANCE_PROVIDER_ID_EMPTY"
        )
    )
    if not isinstance(raw_hash, str) or len(raw_hash) != 64 or any(
        character not in "0123456789abcdef" for character in raw_hash
    ):
        issues.append(
            error(
                "PROVENANCE_RAW_HASH_INVALID",
                "provenance.raw_payload_hash",
                "raw payload hash must be a lowercase SHA-256 digest.",
            )
        )
    issues.extend(
        validate_required_text(
            transformation_version,
            "provenance.transformation_version",
            "PROVENANCE_TRANSFORMATION_VERSION_EMPTY",
        )
    )
    if (
        not isinstance(failover_count, int)
        or isinstance(failover_count, bool)
        or failover_count < 0
    ):
        issues.append(
            error(
                "PROVENANCE_FAILOVER_COUNT_INVALID",
                "provenance.failover_count",
                "failover count must be a non-negative integer.",
            )
        )
    elif failover_count > 0 and received_via_failover is not True:
        issues.append(
            error(
                "PROVENANCE_FAILOVER_ATTRIBUTION_INVALID",
                "provenance.received_via_failover",
                "positive failover count requires failover attribution.",
            )
        )
    if provider_timestamp is not None and (
        not isinstance(provider_timestamp, datetime)
        or provider_timestamp.tzinfo is None
        or provider_timestamp.utcoffset() is None
    ):
        issues.append(
            error(
                "TIMESTAMP_NAIVE",
                "provenance.provider_timestamp",
                "provider timestamp must include timezone information.",
            )
        )
    if source_uri is not None:
        if not isinstance(source_uri, str) or not source_uri.strip():
            issues.append(
                error(
                    "PROVENANCE_SOURCE_URI_INVALID",
                    "provenance.source_uri",
                    "source URI must be a non-empty string when present.",
                )
            )
        else:
            parsed = urlsplit(source_uri)
            query_fields = {key.casefold() for key, _ in parse_qsl(parsed.query)}
            if parsed.username or parsed.password or query_fields & _SECRET_QUERY_FIELDS:
                issues.append(
                    error(
                        "PROVENANCE_SOURCE_URI_SECRET",
                        "provenance.source_uri",
                        "source URI must not contain credentials.",
                    )
                )
    return tuple(issues)


def validate_schema_version(
    value: object, context: ValidationContext
) -> tuple[ValidationIssue, ...]:
    required = validate_required_text(value, "schema_version", "SCHEMA_VERSION_EMPTY")
    if required:
        return required
    if value not in context.supported_schema_versions:
        return (
            error(
                "UNSUPPORTED_SCHEMA_VERSION",
                "schema_version",
                "schema version is not supported by this validator.",
            ),
        )
    return ()


def validate_safe_payload(value: object, field: str = "payload") -> tuple[ValidationIssue, ...]:
    if not isinstance(value, Mapping):
        return (error("PAYLOAD_UNSAFE", field, "payload must be an immutable mapping."),)
    if not isinstance(value, MappingProxyType):
        return (error("PAYLOAD_MUTABLE", field, "payload mapping must be immutable."),)
    if _safe_value(value):
        return ()
    return (error("PAYLOAD_UNSAFE", field, "payload contains an unsupported value."),)


def _safe_value(value: object) -> bool:
    if isinstance(value, datetime):
        return value.tzinfo is not None and value.utcoffset() is not None
    if value is None or isinstance(value, (str, bool, int, Decimal, date)):
        return True
    if isinstance(value, tuple):
        return all(_safe_value(item) for item in value)
    if isinstance(value, MappingProxyType):
        return all(
            isinstance(key, str) and bool(key) and _safe_value(item)
            for key, item in value.items()
        )
    return False
