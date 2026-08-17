"""Deterministic fixture normalization at the Provider-specific boundary."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol, TypeVar

from aic_backend.data_foundation.identity import deterministic_record_id
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
    RawObservation,
)


class NormalizationErrorCode(StrEnum):
    UNSUPPORTED_RECORD = "NORMALIZATION_UNSUPPORTED_RECORD"
    MISSING_FIELD = "NORMALIZATION_MISSING_FIELD"
    INVALID_TYPE = "NORMALIZATION_INVALID_TYPE"
    INVALID_VALUE = "NORMALIZATION_INVALID_VALUE"
    UNSUPPORTED_SCHEMA = "NORMALIZATION_UNSUPPORTED_SCHEMA"


class NormalizationError(ValueError):
    def __init__(self, code: NormalizationErrorCode, field: str | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.message = message


T_co = TypeVar("T_co", covariant=True)
T_enum = TypeVar("T_enum", bound=StrEnum)


class DataNormalizer(Protocol[T_co]):
    @property
    def transformation_version(self) -> str: ...

    def normalize(self, observation: RawObservation) -> T_co: ...


class FixtureDailyBarNormalizer:
    """Maps deterministic fixture fields; it is not a real Provider adapter."""

    transformation_version = "fixture-daily-bar-v1"
    supported_schema_version = "1.0"

    def normalize(self, observation: RawObservation) -> DailyBar:
        payload = observation.payload
        if not isinstance(payload, Mapping):
            raise NormalizationError(
                NormalizationErrorCode.INVALID_TYPE, "payload", "Fixture payload must be a mapping."
            )
        schema = self._text(payload, "schema")
        if schema != self.supported_schema_version:
            raise NormalizationError(
                NormalizationErrorCode.UNSUPPORTED_SCHEMA,
                "schema",
                "Fixture schema is not supported.",
            )
        ticker = self._text(payload, "ticker")
        market = self._enum(Market, payload, "market")
        instrument_type = self._enum(InstrumentType, payload, "instrument_type")
        trading_date = self._date(payload, "trade_day")
        event_time = self._datetime(payload, "event_time")
        instrument = InstrumentIdentity(market, ticker, instrument_type)
        provenance = self._provenance(observation)
        record_id = deterministic_record_id(
            instrument, DailyBar.RECORD_TYPE, event_time, trading_date.isoformat()
        )
        return DailyBar(
            record_id=record_id,
            schema_version=schema,
            instrument=instrument,
            trading_date=trading_date,
            event_time=event_time,
            observed_at=provenance.provider_timestamp or observation.received_at,
            ingested_at=observation.received_at,
            provenance=provenance,
            open=self._decimal(payload, "o"),
            high=self._decimal(payload, "h"),
            low=self._decimal(payload, "l"),
            close=self._decimal(payload, "c"),
            volume=self._integer(payload, "vol"),
            turnover=self._decimal(payload, "amount"),
        )

    def _provenance(self, observation: RawObservation) -> DataProvenance:
        metadata = observation.source_metadata
        return DataProvenance(
            provider_id=observation.provider_id,
            source_record_id=self._optional_text(metadata, "source_record_id"),
            source_uri=self._optional_text(metadata, "source_uri"),
            provider_timestamp=self._optional_datetime(metadata, "provider_timestamp"),
            received_via_failover=self._boolean(metadata, "received_via_failover", False),
            failover_count=self._integer(metadata, "failover_count", 0),
            raw_payload_hash=observation.payload_hash,
            transformation_version=self.transformation_version,
        )

    @staticmethod
    def _required(values: Mapping[str, object], field: str) -> object:
        if field not in values:
            raise NormalizationError(
                NormalizationErrorCode.MISSING_FIELD, field, f"Required field {field} is missing."
            )
        return values[field]

    @classmethod
    def _text(cls, values: Mapping[str, object], field: str) -> str:
        value = cls._required(values, field)
        if not isinstance(value, str):
            raise NormalizationError(
                NormalizationErrorCode.INVALID_TYPE, field, f"{field} must be text."
            )
        if not value.strip():
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, field, f"{field} is empty."
            )
        return value.strip()

    @classmethod
    def _optional_text(cls, values: Mapping[str, object], field: str) -> str | None:
        value = values.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise NormalizationError(
                NormalizationErrorCode.INVALID_TYPE, field, f"{field} must be text."
            )
        return value

    @classmethod
    def _decimal(cls, values: Mapping[str, object], field: str) -> Decimal:
        value = cls._required(values, field)
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise NormalizationError(
                NormalizationErrorCode.INVALID_TYPE,
                field,
                f"{field} must be decimal text.",
            )
        try:
            return Decimal(value)
        except InvalidOperation as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, field, f"{field} is not a valid decimal."
            ) from error

    @classmethod
    def _integer(cls, values: Mapping[str, object], field: str, default: int | None = None) -> int:
        value = values.get(field, default)
        if value is None:
            raise NormalizationError(
                NormalizationErrorCode.MISSING_FIELD, field, f"{field} is missing."
            )
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise NormalizationError(
                NormalizationErrorCode.INVALID_TYPE,
                field,
                f"{field} must be integer text.",
            )
        try:
            return int(value)
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, field, f"{field} is not a valid integer."
            ) from error

    @classmethod
    def _date(cls, values: Mapping[str, object], field: str) -> date:
        value = cls._text(values, field)
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, field, f"{field} is invalid."
            ) from error

    @classmethod
    def _datetime(cls, values: Mapping[str, object], field: str) -> datetime:
        value = cls._text(values, field)
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, field, f"{field} is invalid."
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE,
                field,
                f"{field} must include timezone.",
            )
        return parsed

    @classmethod
    def _optional_datetime(cls, values: Mapping[str, object], field: str) -> datetime | None:
        if values.get(field) is None:
            return None
        return cls._datetime(values, field)

    @classmethod
    def _boolean(cls, values: Mapping[str, object], field: str, default: bool) -> bool:
        value = values.get(field, default)
        if not isinstance(value, bool):
            raise NormalizationError(
                NormalizationErrorCode.INVALID_TYPE, field, f"{field} must be boolean."
            )
        return value

    @classmethod
    def _enum(
        cls, enum_type: type[T_enum], values: Mapping[str, object], field: str
    ) -> T_enum:
        value = cls._text(values, field)
        try:
            return enum_type(value)
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_VALUE, field, f"{field} is invalid."
            ) from error
