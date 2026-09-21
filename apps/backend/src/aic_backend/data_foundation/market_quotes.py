"""Pure normalization, validation, quality, and reconciliation for market quotes."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from aic_backend.data_foundation.normalization import NormalizationError, NormalizationErrorCode
from aic_backend.data_foundation.quality import (
    DataQualityAssessment,
    DataQualityFlag,
    InvalidQualityInputError,
    QualityContext,
)
from aic_backend.data_foundation.validation import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentType,
    Market,
    MarketQuote,
    QuoteReconciliation,
    QuoteSessionStatus,
    RawObservation,
    ReconciliationStatus,
)


def _required(payload: Mapping[str, object], field: str) -> object:
    if field not in payload:
        raise NormalizationError(
            NormalizationErrorCode.MISSING_FIELD, field, f"Required field {field} is missing."
        )
    return payload[field]


def _text(payload: Mapping[str, object], field: str) -> str:
    value = _required(payload, field)
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(
            NormalizationErrorCode.INVALID_TYPE, field, f"{field} must be non-empty text."
        )
    return value.strip()


def _optional_decimal(payload: Mapping[str, object], field: str) -> Decimal | None:
    value = payload.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise NormalizationError(
            NormalizationErrorCode.INVALID_TYPE, field, f"{field} must be decimal text."
        )
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise NormalizationError(
            NormalizationErrorCode.INVALID_VALUE, field, f"{field} is not a decimal."
        ) from error


class MarketQuoteNormalizer:
    transformation_version = "market-quote-canonical/v1"

    def normalize(self, observation: RawObservation) -> MarketQuote:
        if observation.lineage is None:
            raise NormalizationError(
                NormalizationErrorCode.MISSING_FIELD, "lineage", "Quote evidence requires lineage."
            )
        payload = observation.payload
        if not isinstance(payload, Mapping):
            raise NormalizationError(
                NormalizationErrorCode.INVALID_TYPE, "payload", "Quote payload must be a mapping."
            )
        try:
            instrument = InstrumentIdentity(
                Market(_text(payload, "market")),
                _text(payload, "symbol"),
                InstrumentType(_text(payload, "instrument_type")),
            )
            event_time = datetime.fromisoformat(_text(payload, "event_time"))
            session_status = QuoteSessionStatus(_text(payload, "session_status"))
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE,
                None,
                "Quote identity or timestamp is invalid.",
            ) from error
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, "event_time", "event_time requires timezone."
            )
        last = _optional_decimal(payload, "last")
        if last is None:
            raise NormalizationError(
                NormalizationErrorCode.MISSING_FIELD, "last", "Quote last is required."
            )
        volume_value = payload.get("volume")
        try:
            volume = None if volume_value in (None, "") else int(str(volume_value))
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, "volume", "volume must be an integer."
            ) from error
        identity = {
            "event_time": event_time.isoformat(),
            "instrument": instrument.canonical_key,
            "observation_id": observation.observation_id,
            "raw_hash": observation.payload_hash,
            "upstream": observation.lineage.upstream_source_id,
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return MarketQuote(
            f"quote_{digest}",
            instrument,
            event_time,
            observation.lineage.observed_at,
            observation.lineage.ingested_at,
            last,
            _optional_decimal(payload, "bid"),
            _optional_decimal(payload, "ask"),
            _optional_decimal(payload, "previous_close"),
            volume,
            _optional_decimal(payload, "turnover"),
            session_status,
            observation.lineage,
        )


class MarketQuoteValidator:
    def validate(self, value: MarketQuote) -> ValidationResult:
        issues: list[ValidationIssue] = []
        if value.event_time > value.observed_at:
            issues.append(
                ValidationIssue(
                    "QUOTE_EVENT_IN_FUTURE",
                    ValidationSeverity.ERROR,
                    "event_time",
                    "event_time must not follow first observation time.",
                )
            )
        if value.observed_at > value.ingested_at:
            issues.append(
                ValidationIssue(
                    "QUOTE_INGESTION_ORDER_INVALID",
                    ValidationSeverity.ERROR,
                    "ingested_at",
                    "ingested_at must not precede observed_at.",
                )
            )
        return ValidationResult(tuple(issues), ())


class MarketQuoteQualityAssessor:
    def __init__(self, fresh_for: timedelta = timedelta(seconds=15)) -> None:
        if fresh_for <= timedelta(0):
            raise ValueError("fresh_for must be positive")
        self._fresh_for = fresh_for

    def assess(
        self,
        value: MarketQuote,
        *,
        reference_time: datetime,
        context: QualityContext,
        validation_result: ValidationResult,
    ) -> DataQualityAssessment:
        if not validation_result.valid:
            raise InvalidQualityInputError("Quality assessment requires valid quote data.")
        age = reference_time - value.event_time
        freshness = 100.0 if timedelta(0) <= age <= self._fresh_for else 0.0
        optional = (value.bid, value.ask, value.previous_close, value.volume, value.turnover)
        completeness = 100.0 * sum(item is not None for item in optional) / len(optional)
        flags: set[DataQualityFlag] = set()
        if freshness == 0:
            flags.add(DataQualityFlag.STALE)
        if completeness < 100:
            flags.add(DataQualityFlag.MISSING_OPTIONAL_FIELD)
        if context.conflicts:
            flags.add(DataQualityFlag.CONFLICTING_SOURCE)
        source_confidence = {
            "PRIMARY": 100.0,
            "COMMERCIAL": 95.0,
            "HIGH_QUALITY_PUBLIC": 75.0,
            "RADAR": 25.0,
        }[value.lineage.authority_level.value]
        score = freshness * 0.35 + completeness * 0.20 + 100.0 * 0.25 + source_confidence * 0.20
        return DataQualityAssessment(
            score, freshness, completeness, 100.0, source_confidence, tuple(flags)
        )


class MarketQuoteReconciler:
    VERSION = "market-quote-reconciliation/v1"

    def __init__(self, *, max_age: timedelta, price_tolerance_bps: Decimal) -> None:
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        if price_tolerance_bps < 0:
            raise ValueError("price_tolerance_bps must not be negative")
        self._max_age = max_age
        self._price_tolerance_bps = price_tolerance_bps

    def reconcile(
        self, instrument: InstrumentIdentity, quotes: Sequence[MarketQuote], as_of: datetime
    ) -> QuoteReconciliation:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")
        by_upstream: dict[str, MarketQuote] = {}
        reasons: set[str] = set()
        for quote in sorted(quotes, key=lambda item: (item.event_time, item.quote_id)):
            if quote.instrument != instrument:
                raise ValueError("quote instrument does not match reconciliation identity")
            upstream = quote.lineage.upstream_source_id
            if upstream in by_upstream:
                reasons.add("DUPLICATE_UPSTREAM_COLLAPSED")
            by_upstream[upstream] = quote
        fresh = [
            quote
            for quote in by_upstream.values()
            if timedelta(0) <= as_of - quote.event_time <= self._max_age
        ]
        if len(fresh) != len(by_upstream):
            reasons.add("STALE_SOURCE_EXCLUDED")
        fresh.sort(key=lambda item: (item.last, item.lineage.upstream_source_id, item.quote_id))
        chosen: MarketQuote | None = None
        if not fresh:
            status = ReconciliationStatus.UNAVAILABLE
            confidence = Decimal("0")
            reasons.add("NO_FRESH_SOURCE")
        elif len(fresh) == 1:
            status = ReconciliationStatus.DEGRADED
            confidence = Decimal("0.5")
            chosen = fresh[0]
            reasons.add("INDEPENDENT_QUORUM_ABSENT")
        else:
            low, high = fresh[0].last, fresh[-1].last
            spread_bps = (high - low) / low * Decimal("10000")
            if (
                spread_bps <= self._price_tolerance_bps
                and len({quote.session_status for quote in fresh}) == 1
            ):
                status = ReconciliationStatus.CONFIRMED
                confidence = Decimal("1")
                chosen = fresh[(len(fresh) - 1) // 2]
            else:
                status = ReconciliationStatus.CONFLICTED
                confidence = Decimal("0")
                reasons.add("PRICE_OR_SESSION_CONFLICT")
        identity = {
            "as_of": as_of.isoformat(),
            "instrument": instrument.canonical_key,
            "policy": self.VERSION,
            "quotes": sorted(quote.quote_id for quote in fresh),
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return QuoteReconciliation(
            f"recon_{digest}",
            instrument,
            as_of,
            status,
            tuple(quote.quote_id for quote in fresh),
            tuple(quote.lineage.upstream_source_id for quote in fresh),
            None if chosen is None else chosen.quote_id,
            confidence,
            tuple(reasons),
            self.VERSION,
        )
