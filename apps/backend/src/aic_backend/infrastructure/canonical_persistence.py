"""PostgreSQL canonical DailyBar persistence adapter."""

from collections.abc import Mapping
from datetime import UTC
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    MetaData,
    Numeric,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.persistence import (
    CanonicalDailyBarRepository,
    PersistedDailyBar,
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.data_foundation.quality import DataQualityAssessment, DataQualityFlag
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)

metadata = MetaData()

canonical_daily_bars = Table(
    "canonical_daily_bars",
    metadata,
    Column("record_id", String(64), primary_key=True),
    Column("observation_id", String(255), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("market", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("open", Numeric(28, 10), nullable=False),
    Column("high", Numeric(28, 10), nullable=False),
    Column("low", Numeric(28, 10), nullable=False),
    Column("close", Numeric(28, 10), nullable=False),
    Column("volume", BigInteger, nullable=False),
    Column("turnover", Numeric(38, 10), nullable=False),
    Column("provider_id", String(255), nullable=False),
    Column("source_record_id", String(255)),
    Column("source_uri", String(2048)),
    Column("provider_timestamp", DateTime(timezone=True)),
    Column("received_via_failover", Boolean, nullable=False),
    Column("failover_count", BigInteger, nullable=False),
    Column("raw_payload_hash", String(64), nullable=False),
    Column("transformation_version", String(255), nullable=False),
    Column("quality_score", Numeric(5, 2), nullable=False),
    Column("freshness_score", Numeric(5, 2), nullable=False),
    Column("completeness_score", Numeric(5, 2), nullable=False),
    Column("consistency_score", Numeric(5, 2), nullable=False),
    Column("source_confidence_score", Numeric(5, 2), nullable=False),
    Column("quality_flags", ARRAY(String(64)), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",
        nullable=False,
    ),
)


def _values(value: PersistedDailyBar) -> dict[str, object]:
    record = value.record
    provenance = record.provenance
    quality = value.quality
    return {
        "record_id": record.record_id,
        "observation_id": value.observation_id,
        "schema_version": record.schema_version,
        "market": record.instrument.market.value,
        "symbol": record.instrument.symbol,
        "instrument_type": record.instrument.instrument_type.value,
        "trading_date": record.trading_date,
        "event_time": record.event_time,
        "observed_at": record.observed_at,
        "ingested_at": record.ingested_at,
        "open": record.open,
        "high": record.high,
        "low": record.low,
        "close": record.close,
        "volume": record.volume,
        "turnover": record.turnover,
        "provider_id": provenance.provider_id,
        "source_record_id": provenance.source_record_id,
        "source_uri": provenance.source_uri,
        "provider_timestamp": provenance.provider_timestamp,
        "received_via_failover": provenance.received_via_failover,
        "failover_count": provenance.failover_count,
        "raw_payload_hash": provenance.raw_payload_hash,
        "transformation_version": provenance.transformation_version,
        "quality_score": Decimal(str(quality.score)),
        "freshness_score": Decimal(str(quality.freshness_score)),
        "completeness_score": Decimal(str(quality.completeness_score)),
        "consistency_score": Decimal(str(quality.consistency_score)),
        "source_confidence_score": Decimal(str(quality.source_confidence_score)),
        "quality_flags": [flag.value for flag in quality.flags],
    }


_FACT_FIELDS = (
    "schema_version", "market", "symbol", "instrument_type", "trading_date",
    "event_time", "observed_at", "ingested_at", "open", "high", "low", "close",
    "volume", "turnover",
)


def _same_fact(row: Mapping[str, Any] | RowMapping, expected: Mapping[str, object]) -> bool:
    return all(row[field] == expected[field] for field in _FACT_FIELDS)


def _stored(row: Mapping[str, Any] | RowMapping) -> PersistedDailyBar:
    provenance = DataProvenance(
        provider_id=row["provider_id"],
        source_record_id=row["source_record_id"],
        source_uri=row["source_uri"],
        provider_timestamp=row["provider_timestamp"],
        received_via_failover=row["received_via_failover"],
        failover_count=row["failover_count"],
        raw_payload_hash=row["raw_payload_hash"],
        transformation_version=row["transformation_version"],
    )
    record = DailyBar(
        record_id=row["record_id"], schema_version=row["schema_version"],
        instrument=InstrumentIdentity(
            Market(row["market"]), row["symbol"], InstrumentType(row["instrument_type"])
        ),
        trading_date=row["trading_date"], event_time=row["event_time"].astimezone(UTC),
        observed_at=row["observed_at"].astimezone(UTC),
        ingested_at=row["ingested_at"].astimezone(UTC), provenance=provenance,
        open=row["open"], high=row["high"], low=row["low"], close=row["close"],
        volume=row["volume"], turnover=row["turnover"],
    )
    quality = DataQualityAssessment(
        score=float(row["quality_score"]), freshness_score=float(row["freshness_score"]),
        completeness_score=float(row["completeness_score"]),
        consistency_score=float(row["consistency_score"]),
        source_confidence_score=float(row["source_confidence_score"]),
        flags=tuple(DataQualityFlag(flag) for flag in row["quality_flags"]),
    )
    return PersistedDailyBar(row["observation_id"], record, quality)


class PostgreSQLCanonicalDailyBarRepository(CanonicalDailyBarRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, value: PersistedDailyBar) -> SaveResult:
        values = _values(value)
        try:
            async with self._engine.begin() as connection:
                statement = (
                    postgresql_insert(canonical_daily_bars)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["record_id"])
                    .returning(canonical_daily_bars.c.record_id)
                )
                inserted = (await connection.execute(statement)).scalar_one_or_none()
                if inserted is not None:
                    return SaveResult(SaveStatus.INSERTED, value.record.record_id)
                row = (
                    await connection.execute(
                        select(canonical_daily_bars).where(
                            canonical_daily_bars.c.record_id == value.record.record_id
                        )
                    )
                ).mappings().one()
                if not _same_fact(row, values):
                    raise PersistenceError(
                        PersistenceErrorCode.IDENTITY_CONFLICT,
                        "record_id already identifies a different financial fact",
                    )
                return SaveResult(SaveStatus.ALREADY_EXISTS, value.record.record_id)
        except PersistenceError:
            raise
        except IntegrityError as error:
            raise PersistenceError(
                PersistenceErrorCode.CONSTRAINT_VIOLATION, "persistence constraint rejected data"
            ) from error
        except DBAPIError as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "canonical persistence is unavailable"
            ) from error
        except (ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR, "canonical value cannot be serialized"
            ) from error
        except SQLAlchemyError as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR, "canonical transaction failed"
            ) from error

    async def get_by_record_id(self, record_id: str) -> PersistedDailyBar | None:
        try:
            async with self._engine.connect() as connection:
                row = (
                    await connection.execute(
                        select(canonical_daily_bars).where(
                            canonical_daily_bars.c.record_id == record_id
                        )
                    )
                ).mappings().one_or_none()
            return None if row is None else _stored(row)
        except DBAPIError as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "canonical persistence is unavailable"
            ) from error
        except (ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR, "stored canonical value is invalid"
            ) from error
        except SQLAlchemyError as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR, "canonical read transaction failed"
            ) from error


class InMemoryCanonicalDailyBarRepository(CanonicalDailyBarRepository):
    def __init__(self) -> None:
        self._records: dict[str, PersistedDailyBar] = {}

    async def save(self, value: PersistedDailyBar) -> SaveResult:
        existing = self._records.get(value.record.record_id)
        if existing is None:
            self._records[value.record.record_id] = value
            return SaveResult(SaveStatus.INSERTED, value.record.record_id)
        if not _same_fact(_values(existing), _values(value)):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                "record_id already identifies a different financial fact",
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, value.record.record_id)

    async def get_by_record_id(self, record_id: str) -> PersistedDailyBar | None:
        return self._records.get(record_id)
