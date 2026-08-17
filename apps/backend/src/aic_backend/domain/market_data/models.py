"""Immutable, source-neutral market-data domain models."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType
from urllib.parse import parse_qsl, urlsplit

from aic_backend.domain.market_data.enums import (
    DataCapability,
    InstrumentType,
    Market,
)
from aic_backend.domain.market_data.errors import (
    InvalidInstrumentError,
    InvalidPayloadError,
    InvalidProvenanceError,
    InvalidTimestampError,
)

type ScalarValue = None | bool | int | str | Decimal | date | datetime
type ImmutableValue = ScalarValue | tuple["ImmutableValue", ...] | Mapping[
    str, "ImmutableValue"
]
type InputValue = ScalarValue | list["InputValue"] | tuple["InputValue", ...] | Mapping[
    str, "InputValue"
]
type RawPayload = bytes | str | Mapping[str, InputValue]

_SECRET_QUERY_FIELDS = frozenset(
    {"access_token", "api_key", "apikey", "auth", "key", "secret", "signature", "token"}
)


def _require_text(value: str, field: str, error_type: type[ValueError] = ValueError) -> str:
    normalized = value.strip()
    if not normalized:
        raise error_type(f"{field} must not be empty")
    return normalized


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidTimestampError(f"{field} must include timezone information")
    return value.astimezone(UTC)


def _freeze(value: InputValue, field: str = "payload") -> ImmutableValue:
    if isinstance(value, datetime):
        return _utc(value, field)
    if isinstance(value, (str, bool, int, Decimal, date)) or value is None:
        return value
    if isinstance(value, Mapping):
        copied: dict[str, ImmutableValue] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise InvalidPayloadError(f"{field} keys must be non-empty strings")
            copied[key] = _freeze(item, f"{field}.{key}")
        return MappingProxyType(copied)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, field) for item in value)
    raise InvalidPayloadError(f"{field} contains unsupported value type")


def _freeze_mapping(value: Mapping[str, InputValue], field: str) -> Mapping[str, ImmutableValue]:
    frozen = _freeze(value, field)
    if not isinstance(frozen, Mapping):  # pragma: no cover - fixed by the input type
        raise InvalidPayloadError(f"{field} must be a mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    market: Market
    symbol: str
    instrument_type: InstrumentType

    def __post_init__(self) -> None:
        symbol = _require_text(self.symbol, "symbol", InvalidInstrumentError).upper()
        if "." in symbol:
            raise InvalidInstrumentError("symbol must not contain market separators")
        object.__setattr__(self, "symbol", symbol)

    @property
    def canonical_key(self) -> str:
        return f"{self.market.value}.{self.symbol}"


@dataclass(frozen=True, slots=True)
class DataProvenance:
    provider_id: str
    source_record_id: str | None
    source_uri: str | None
    provider_timestamp: datetime | None
    received_via_failover: bool
    failover_count: int
    raw_payload_hash: str
    transformation_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_id",
            _require_text(self.provider_id, "provider_id", InvalidProvenanceError),
        )
        object.__setattr__(
            self,
            "transformation_version",
            _require_text(
                self.transformation_version,
                "transformation_version",
                InvalidProvenanceError,
            ),
        )
        if len(self.raw_payload_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.raw_payload_hash
        ):
            raise InvalidProvenanceError("raw_payload_hash must be a lowercase SHA-256 digest")
        if self.failover_count < 0:
            raise InvalidProvenanceError("failover_count must not be negative")
        if self.failover_count and not self.received_via_failover:
            raise InvalidProvenanceError("positive failover_count requires failover attribution")
        if self.source_record_id is not None:
            object.__setattr__(
                self,
                "source_record_id",
                _require_text(
                    self.source_record_id, "source_record_id", InvalidProvenanceError
                ),
            )
        if self.provider_timestamp is not None:
            object.__setattr__(
                self,
                "provider_timestamp",
                _utc(self.provider_timestamp, "provider_timestamp"),
            )
        if self.source_uri is not None:
            uri = _require_text(self.source_uri, "source_uri", InvalidProvenanceError)
            parsed = urlsplit(uri)
            query_fields = {key.casefold() for key, _ in parse_qsl(parsed.query)}
            if parsed.username or parsed.password or query_fields & _SECRET_QUERY_FIELDS:
                raise InvalidProvenanceError("source_uri must not contain credentials")
            object.__setattr__(self, "source_uri", uri)


@dataclass(frozen=True, slots=True)
class RawObservation:
    observation_id: str
    provider_id: str
    capability: DataCapability
    received_at: datetime
    payload: RawPayload
    payload_hash: str
    source_metadata: Mapping[str, InputValue]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _require_text(self.observation_id, "observation_id"),
        )
        object.__setattr__(self, "provider_id", _require_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "received_at", _utc(self.received_at, "received_at"))
        if isinstance(self.payload, Mapping):
            object.__setattr__(self, "payload", _freeze_mapping(self.payload, "payload"))
        elif not isinstance(self.payload, (bytes, str)):
            raise InvalidPayloadError("payload must be bytes, text, or a mapping")
        if len(self.payload_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.payload_hash
        ):
            raise InvalidPayloadError("payload_hash must be a lowercase SHA-256 digest")
        object.__setattr__(
            self,
            "source_metadata",
            _freeze_mapping(self.source_metadata, "source_metadata"),
        )


@dataclass(frozen=True, slots=True)
class CanonicalRecord:
    record_id: str
    record_type: str
    schema_version: str
    instrument: InstrumentIdentity | None
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    provenance: DataProvenance
    payload: Mapping[str, InputValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _require_text(self.record_id, "record_id"))
        object.__setattr__(self, "record_type", _require_text(self.record_type, "record_type"))
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "event_time", _utc(self.event_time, "event_time"))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        object.__setattr__(self, "ingested_at", _utc(self.ingested_at, "ingested_at"))
        object.__setattr__(self, "payload", _freeze_mapping(self.payload, "payload"))


@dataclass(frozen=True, slots=True)
class DailyBar:
    record_id: str
    schema_version: str
    instrument: InstrumentIdentity
    trading_date: date
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    provenance: DataProvenance
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal

    RECORD_TYPE = "DAILY_BAR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _require_text(self.record_id, "record_id"))
        object.__setattr__(
            self, "schema_version", _require_text(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "event_time", _utc(self.event_time, "event_time"))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        object.__setattr__(self, "ingested_at", _utc(self.ingested_at, "ingested_at"))
        for field in ("open", "high", "low", "close", "turnover"):
            if not isinstance(getattr(self, field), Decimal):
                raise TypeError(f"{field} must be Decimal")
        if not isinstance(self.volume, int) or isinstance(self.volume, bool):
            raise TypeError("volume must be int")
