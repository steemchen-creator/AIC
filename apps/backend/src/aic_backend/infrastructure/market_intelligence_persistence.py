"""PostgreSQL and in-memory persistence for auditable market evidence."""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Column,
    DateTime,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.market_intelligence import (
    MarketPulseRepository,
    MarketQuoteRepository,
    PersistedMarketQuote,
    RawObservationRepository,
)
from aic_backend.application.ports.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.data_foundation.quality import DataQualityAssessment, DataQualityFlag
from aic_backend.domain.market_data import (
    AuthorityLevel,
    DataCapability,
    InstrumentIdentity,
    InstrumentType,
    Market,
    MarketPulseFamily,
    MarketPulseObservation,
    MarketQuote,
    MarketSeriesIdentity,
    PublicationMode,
    QuoteReconciliation,
    QuoteSessionStatus,
    RawObservation,
    ReconciliationStatus,
    SourceLineage,
    SourceType,
)
from aic_backend.domain.market_data.models import InputValue, RawPayload

metadata = MetaData()

raw_observations = Table(
    "raw_observations",
    metadata,
    Column("observation_id", String(96), primary_key=True),
    Column("provider_id", String(64), nullable=False),
    Column("capability", String(64), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("payload_kind", String(16), nullable=False),
    Column("payload", LargeBinary, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("source_metadata", Text, nullable=False),
    Column("adapter_id", String(64), nullable=False),
    Column("upstream_source_id", String(96), nullable=False),
    Column("authority_level", String(32), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("raw_hash", String(64), nullable=False),
    Column("transformation_version", String(96), nullable=False),
    Column("source_uri", String(2048)),
    Column("source_record_id", String(255)),
    Column("license_id", String(96)),
)

canonical_market_quotes = Table(
    "canonical_market_quotes",
    metadata,
    Column("quote_id", String(96), primary_key=True),
    Column("observation_id", String(96), nullable=False),
    Column("market", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("last", Numeric(28, 10), nullable=False),
    Column("bid", Numeric(28, 10)),
    Column("ask", Numeric(28, 10)),
    Column("previous_close", Numeric(28, 10)),
    Column("volume", BigInteger),
    Column("turnover", Numeric(38, 10)),
    Column("session_status", String(24), nullable=False),
    Column("adapter_id", String(64), nullable=False),
    Column("upstream_source_id", String(96), nullable=False),
    Column("authority_level", String(32), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("raw_hash", String(64), nullable=False),
    Column("transformation_version", String(96), nullable=False),
    Column("source_uri", String(2048)),
    Column("source_record_id", String(255)),
    Column("license_id", String(96)),
    Column("quality_score", Numeric(5, 2), nullable=False),
    Column("freshness_score", Numeric(5, 2), nullable=False),
    Column("completeness_score", Numeric(5, 2), nullable=False),
    Column("consistency_score", Numeric(5, 2), nullable=False),
    Column("source_confidence_score", Numeric(5, 2), nullable=False),
    Column("quality_flags", ARRAY(String(64)), nullable=False),
)

quote_reconciliations = Table(
    "quote_reconciliations",
    metadata,
    Column("reconciliation_id", String(96), primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("status", String(24), nullable=False),
    Column("contributing_quote_ids", ARRAY(String(96)), nullable=False),
    Column("contributing_upstream_ids", ARRAY(String(96)), nullable=False),
    Column("chosen_quote_id", String(96)),
    Column("confidence", Numeric(8, 6), nullable=False),
    Column("reasons", ARRAY(String(96)), nullable=False),
    Column("policy_version", String(96), nullable=False),
)

market_pulse_observations = Table(
    "market_pulse_observations",
    metadata,
    Column("observation_id", String(96), primary_key=True),
    Column("series_id", String(96), nullable=False),
    Column("family", String(32), nullable=False),
    Column("benchmark_owner", String(96), nullable=False),
    Column("definition", Text, nullable=False),
    Column("geography", String(96), nullable=False),
    Column("unit", String(32), nullable=False),
    Column("publication_mode", String(32), nullable=False),
    Column("currency", String(16)),
    Column("tenor_or_contract", String(96)),
    Column("value", Numeric(38, 12), nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("adapter_id", String(64), nullable=False),
    Column("upstream_source_id", String(96), nullable=False),
    Column("authority_level", String(32), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("raw_hash", String(64), nullable=False),
    Column("transformation_version", String(96), nullable=False),
    Column("source_uri", String(2048)),
    Column("source_record_id", String(255)),
    Column("license_id", String(96)),
)


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        return {"$datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    raise TypeError("unsupported evidence value")


def _from_jsonable(value: object) -> InputValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, list):
        return [_from_jsonable(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return Decimal(str(value["$decimal"]))
        if set(value) == {"$datetime"}:
            return datetime.fromisoformat(str(value["$datetime"]))
        if set(value) == {"$date"}:
            return date.fromisoformat(str(value["$date"]))
        return {str(key): _from_jsonable(item) for key, item in value.items()}
    raise TypeError("unsupported stored evidence value")


def _encode_payload(payload: RawPayload) -> tuple[str, bytes]:
    if isinstance(payload, bytes):
        return "bytes", payload
    if isinstance(payload, str):
        return "text", payload.encode("utf-8")
    return "mapping", json.dumps(
        _jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _decode_payload(kind: str, payload: bytes) -> RawPayload:
    if kind == "bytes":
        return payload
    if kind == "text":
        return payload.decode("utf-8")
    value = _from_jsonable(json.loads(payload))
    if not isinstance(value, dict):
        raise ValueError("stored mapping payload is invalid")
    return value


def _lineage_values(value: SourceLineage) -> dict[str, object]:
    return {
        "adapter_id": value.adapter_id,
        "upstream_source_id": value.upstream_source_id,
        "authority_level": value.authority_level.value,
        "source_type": value.source_type.value,
        "event_time": value.event_time,
        "published_at": value.published_at,
        "observed_at": value.observed_at,
        "ingested_at": value.ingested_at,
        "raw_hash": value.raw_hash,
        "transformation_version": value.transformation_version,
        "source_uri": value.source_uri,
        "source_record_id": value.source_record_id,
        "license_id": value.license_id,
    }


def _lineage(row: Mapping[str, Any] | RowMapping) -> SourceLineage:
    return SourceLineage(
        row["adapter_id"],
        row["upstream_source_id"],
        AuthorityLevel(row["authority_level"]),
        SourceType(row["source_type"]),
        row["event_time"].astimezone(UTC),
        row["observed_at"].astimezone(UTC),
        row["ingested_at"].astimezone(UTC),
        row["raw_hash"],
        row["transformation_version"],
        None if row["published_at"] is None else row["published_at"].astimezone(UTC),
        row["source_uri"],
        row["source_record_id"],
        row["license_id"],
    )


async def _save(
    engine: AsyncEngine, table: Table, key: str, values: Mapping[str, object]
) -> SaveResult:
    try:
        async with engine.begin() as connection:
            statement = (
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[key])
                .returning(table.c[key])
            )
            inserted = (await connection.execute(statement)).scalar_one_or_none()
            if inserted is not None:
                return SaveResult(SaveStatus.INSERTED, str(inserted))
            stored = (
                (await connection.execute(select(table).where(table.c[key] == values[key])))
                .mappings()
                .one()
            )
            expected = {name: value for name, value in values.items()}
            if any(stored[name] != value for name, value in expected.items()):
                raise PersistenceError(
                    PersistenceErrorCode.IDENTITY_CONFLICT,
                    f"{key} already identifies different immutable evidence",
                )
            return SaveResult(SaveStatus.ALREADY_EXISTS, str(values[key]))
    except PersistenceError:
        raise
    except IntegrityError as error:
        raise PersistenceError(
            PersistenceErrorCode.CONSTRAINT_VIOLATION, "evidence constraint rejected data"
        ) from error
    except (DBAPIError, OSError) as error:
        raise PersistenceError(
            PersistenceErrorCode.UNAVAILABLE, "market evidence persistence is unavailable"
        ) from error
    except (SQLAlchemyError, ValueError, TypeError) as error:
        raise PersistenceError(
            PersistenceErrorCode.TRANSACTION_ERROR, "market evidence transaction failed"
        ) from error


class PostgreSQLMarketIntelligenceRepository(
    RawObservationRepository, MarketQuoteRepository, MarketPulseRepository
):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_raw(self, value: RawObservation) -> SaveResult:
        if value.lineage is None:
            raise PersistenceError(
                PersistenceErrorCode.CONSTRAINT_VIOLATION, "raw evidence requires source lineage"
            )
        kind, payload = _encode_payload(value.payload)
        values = {
            "observation_id": value.observation_id,
            "provider_id": value.provider_id,
            "capability": value.capability.value,
            "received_at": value.received_at,
            "payload_kind": kind,
            "payload": payload,
            "payload_hash": value.payload_hash,
            "source_metadata": json.dumps(
                _jsonable(value.source_metadata), ensure_ascii=False, sort_keys=True
            ),
            **_lineage_values(value.lineage),
        }
        return await _save(self._engine, raw_observations, "observation_id", values)

    async def get_raw(self, observation_id: str) -> RawObservation | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(raw_observations).where(
                            raw_observations.c.observation_id == observation_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        metadata_value = _from_jsonable(json.loads(row["source_metadata"]))
        if not isinstance(metadata_value, dict):
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR, "stored source metadata is invalid"
            )
        return RawObservation(
            row["observation_id"],
            row["provider_id"],
            DataCapability(row["capability"]),
            row["received_at"].astimezone(UTC),
            _decode_payload(row["payload_kind"], row["payload"]),
            row["payload_hash"],
            metadata_value,
            _lineage(row),
        )

    async def save_quote(self, value: PersistedMarketQuote) -> SaveResult:
        quote = value.quote
        quality = value.quality
        values = {
            "quote_id": quote.quote_id,
            "observation_id": value.observation_id,
            "market": quote.instrument.market.value,
            "symbol": quote.instrument.symbol,
            "instrument_type": quote.instrument.instrument_type.value,
            "event_time": quote.event_time,
            "observed_at": quote.observed_at,
            "ingested_at": quote.ingested_at,
            "last": quote.last,
            "bid": quote.bid,
            "ask": quote.ask,
            "previous_close": quote.previous_close,
            "volume": quote.volume,
            "turnover": quote.turnover,
            "session_status": quote.session_status.value,
            **_lineage_values(quote.lineage),
            "quality_score": Decimal(str(quality.score)),
            "freshness_score": Decimal(str(quality.freshness_score)),
            "completeness_score": Decimal(str(quality.completeness_score)),
            "consistency_score": Decimal(str(quality.consistency_score)),
            "source_confidence_score": Decimal(str(quality.source_confidence_score)),
            "quality_flags": [flag.value for flag in quality.flags],
        }
        return await _save(self._engine, canonical_market_quotes, "quote_id", values)

    async def get_quote(self, quote_id: str) -> PersistedMarketQuote | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(canonical_market_quotes).where(
                            canonical_market_quotes.c.quote_id == quote_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _stored_quote(row)

    async def list_quotes(
        self, instrument: InstrumentIdentity, start: datetime, end: datetime
    ) -> tuple[PersistedMarketQuote, ...]:
        if end < start:
            raise ValueError("end must not precede start")
        statement = (
            select(canonical_market_quotes)
            .where(
                canonical_market_quotes.c.market == instrument.market.value,
                canonical_market_quotes.c.symbol == instrument.symbol,
                canonical_market_quotes.c.instrument_type == instrument.instrument_type.value,
                canonical_market_quotes.c.event_time >= start,
                canonical_market_quotes.c.event_time <= end,
            )
            .order_by(canonical_market_quotes.c.event_time, canonical_market_quotes.c.quote_id)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(_stored_quote(row) for row in rows)

    async def save_reconciliation(self, value: QuoteReconciliation) -> SaveResult:
        values = {
            "reconciliation_id": value.reconciliation_id,
            "market": value.instrument.market.value,
            "symbol": value.instrument.symbol,
            "instrument_type": value.instrument.instrument_type.value,
            "as_of": value.as_of,
            "status": value.status.value,
            "contributing_quote_ids": list(value.contributing_quote_ids),
            "contributing_upstream_ids": list(value.contributing_upstream_ids),
            "chosen_quote_id": value.chosen_quote_id,
            "confidence": value.confidence,
            "reasons": list(value.reasons),
            "policy_version": value.policy_version,
        }
        return await _save(self._engine, quote_reconciliations, "reconciliation_id", values)

    async def get_reconciliation(self, reconciliation_id: str) -> QuoteReconciliation | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(quote_reconciliations).where(
                            quote_reconciliations.c.reconciliation_id == reconciliation_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return QuoteReconciliation(
            row["reconciliation_id"],
            InstrumentIdentity(
                Market(row["market"]), row["symbol"], InstrumentType(row["instrument_type"])
            ),
            row["as_of"].astimezone(UTC),
            ReconciliationStatus(row["status"]),
            tuple(row["contributing_quote_ids"]),
            tuple(row["contributing_upstream_ids"]),
            row["chosen_quote_id"],
            row["confidence"],
            tuple(row["reasons"]),
            row["policy_version"],
        )

    async def save_pulse(self, value: MarketPulseObservation) -> SaveResult:
        series = value.series
        values = {
            "observation_id": value.observation_id,
            "series_id": series.series_id,
            "family": series.family.value,
            "benchmark_owner": series.benchmark_owner,
            "definition": series.definition,
            "geography": series.geography,
            "unit": series.unit,
            "publication_mode": series.publication_mode.value,
            "currency": series.currency,
            "tenor_or_contract": series.tenor_or_contract,
            "value": value.value,
            "event_time": value.event_time,
            "observed_at": value.observed_at,
            "ingested_at": value.ingested_at,
            **_lineage_values(value.lineage),
        }
        return await _save(self._engine, market_pulse_observations, "observation_id", values)

    async def list_pulse(
        self, series_id: str, start: datetime, end: datetime
    ) -> tuple[MarketPulseObservation, ...]:
        statement = (
            select(market_pulse_observations)
            .where(
                market_pulse_observations.c.series_id == series_id,
                market_pulse_observations.c.event_time >= start,
                market_pulse_observations.c.event_time <= end,
            )
            .order_by(
                market_pulse_observations.c.event_time, market_pulse_observations.c.observation_id
            )
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(_stored_pulse(row) for row in rows)


def _stored_quote(row: Mapping[str, Any] | RowMapping) -> PersistedMarketQuote:
    quote = MarketQuote(
        row["quote_id"],
        InstrumentIdentity(
            Market(row["market"]), row["symbol"], InstrumentType(row["instrument_type"])
        ),
        row["event_time"].astimezone(UTC),
        row["observed_at"].astimezone(UTC),
        row["ingested_at"].astimezone(UTC),
        row["last"],
        row["bid"],
        row["ask"],
        row["previous_close"],
        row["volume"],
        row["turnover"],
        QuoteSessionStatus(row["session_status"]),
        _lineage(row),
    )
    quality = DataQualityAssessment(
        float(row["quality_score"]),
        float(row["freshness_score"]),
        float(row["completeness_score"]),
        float(row["consistency_score"]),
        float(row["source_confidence_score"]),
        tuple(DataQualityFlag(flag) for flag in row["quality_flags"]),
    )
    return PersistedMarketQuote(row["observation_id"], quote, quality)


def _stored_pulse(row: Mapping[str, Any] | RowMapping) -> MarketPulseObservation:
    series = MarketSeriesIdentity(
        row["series_id"],
        MarketPulseFamily(row["family"]),
        row["benchmark_owner"],
        row["definition"],
        row["geography"],
        row["unit"],
        PublicationMode(row["publication_mode"]),
        row["currency"],
        row["tenor_or_contract"],
    )
    return MarketPulseObservation(
        row["observation_id"],
        series,
        row["value"],
        row["event_time"].astimezone(UTC),
        row["observed_at"].astimezone(UTC),
        row["ingested_at"].astimezone(UTC),
        _lineage(row),
    )


class InMemoryMarketIntelligenceRepository(
    RawObservationRepository, MarketQuoteRepository, MarketPulseRepository
):
    def __init__(self) -> None:
        self.raw: dict[str, RawObservation] = {}
        self.quotes: dict[str, PersistedMarketQuote] = {}
        self.reconciliations: dict[str, QuoteReconciliation] = {}
        self.pulse: dict[str, MarketPulseObservation] = {}

    @staticmethod
    def _memory_save(store: dict[str, Any], key: str, value: Any) -> SaveResult:
        existing = store.get(key)
        if existing is None:
            store[key] = value
            return SaveResult(SaveStatus.INSERTED, key)
        if existing != value:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                "identity already contains different immutable evidence",
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, key)

    async def save_raw(self, value: RawObservation) -> SaveResult:
        if value.lineage is None:
            raise PersistenceError(
                PersistenceErrorCode.CONSTRAINT_VIOLATION, "raw evidence requires source lineage"
            )
        return self._memory_save(self.raw, value.observation_id, value)

    async def get_raw(self, observation_id: str) -> RawObservation | None:
        return self.raw.get(observation_id)

    async def save_quote(self, value: PersistedMarketQuote) -> SaveResult:
        return self._memory_save(self.quotes, value.quote.quote_id, value)

    async def get_quote(self, quote_id: str) -> PersistedMarketQuote | None:
        return self.quotes.get(quote_id)

    async def list_quotes(
        self, instrument: InstrumentIdentity, start: datetime, end: datetime
    ) -> tuple[PersistedMarketQuote, ...]:
        return tuple(
            sorted(
                (
                    v
                    for v in self.quotes.values()
                    if v.quote.instrument == instrument and start <= v.quote.event_time <= end
                ),
                key=lambda v: (v.quote.event_time, v.quote.quote_id),
            )
        )

    async def save_reconciliation(self, value: QuoteReconciliation) -> SaveResult:
        return self._memory_save(self.reconciliations, value.reconciliation_id, value)

    async def get_reconciliation(self, reconciliation_id: str) -> QuoteReconciliation | None:
        return self.reconciliations.get(reconciliation_id)

    async def save_pulse(self, value: MarketPulseObservation) -> SaveResult:
        return self._memory_save(self.pulse, value.observation_id, value)

    async def list_pulse(
        self, series_id: str, start: datetime, end: datetime
    ) -> tuple[MarketPulseObservation, ...]:
        return tuple(
            sorted(
                (
                    v
                    for v in self.pulse.values()
                    if v.series.series_id == series_id and start <= v.event_time <= end
                ),
                key=lambda v: (v.event_time, v.observation_id),
            )
        )
