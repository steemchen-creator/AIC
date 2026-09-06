"""Insert-or-verify PostgreSQL and in-memory ETF/index persistence adapters."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from aic_backend.application.ports.etf import ETFDataRepository
from aic_backend.application.ports.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.domain.market_data import (
    Currency,
    DataProvenance,
    ETFChannel,
    ETFInstrumentProfile,
    ETFTracksIndex,
    ETFValuationSnapshot,
    ExposureCategory,
    ExposureFamily,
    ExposureMarket,
    IndexReference,
    InstrumentExecutionProfile,
    InstrumentIdentity,
    InstrumentType,
    ListingStatus,
    Market,
    SettlementCapability,
)

metadata = MetaData()

etf_instrument_profiles = Table(
    "etf_instrument_profiles",
    metadata,
    Column("instrument_key", String(128), primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("display_name", String(255), nullable=False),
    Column("expanded_name", String(255)),
    Column("listing_date", Date),
    Column("delisting_date", Date),
    Column("listing_status", String(32), nullable=False),
    Column("channel", String(32), nullable=False),
    Column("benchmark_symbol", String(128)),
    Column("fund_manager", String(255)),
    Column("management_fee", Numeric(28, 10)),
    Column("underlying_market", String(32), nullable=False),
    Column("underlying_currency", String(16), nullable=False),
    Column("trading_currency", String(16), nullable=False),
    Column("exposure_category", String(64), nullable=False),
    Column("exposure_family", String(64), nullable=False),
    Column("provenance", JSON, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
)

index_references = Table(
    "index_references",
    metadata,
    Column("index_key", String(128), primary_key=True),
    Column("symbol", String(128), nullable=False),
    Column("display_name", String(255), nullable=False),
    Column("publisher", String(255)),
    Column("base_date", Date),
    Column("base_value", Numeric(28, 10)),
    Column("exposure_market", String(32), nullable=False),
    Column("point_currency", String(16), nullable=False),
    Column("provenance", JSON, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
)

etf_index_relationships = Table(
    "etf_index_relationships",
    metadata,
    Column("relationship_id", String(300), primary_key=True),
    Column("etf_market", String(32), nullable=False),
    Column("etf_symbol", String(64), nullable=False),
    Column("benchmark_symbol", String(128), nullable=False),
    Column("effective_from", Date),
    Column("effective_to", Date),
    Column("current_relationship_only", Boolean, nullable=False),
    Column("provenance", JSON, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
)

etf_valuation_snapshots = Table(
    "etf_valuation_snapshots",
    metadata,
    Column("valuation_id", String(200), primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("nav", Numeric(28, 10)),
    Column("close_price", Numeric(28, 10)),
    Column("share_size", Numeric(38, 10)),
    Column("premium_discount_pct", Numeric(28, 10)),
    Column("provenance", JSON, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
)

instrument_execution_profiles = Table(
    "instrument_execution_profiles",
    metadata,
    Column("profile_id", String(200), primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("trading_currency", String(16), nullable=False),
    Column("board_lot", Integer, nullable=False),
    Column("settlement_capability", String(16), nullable=False),
    Column("price_limit_policy_reference", String(255), nullable=False),
    Column("calendar_reference", String(32), nullable=False),
    Column("source", String(512), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("policy_version", String(128), nullable=False),
)


def _provenance_json(value: DataProvenance) -> dict[str, object]:
    return {
        "provider_id": value.provider_id,
        "source_record_id": value.source_record_id,
        "source_uri": value.source_uri,
        "provider_timestamp": (
            None if value.provider_timestamp is None else value.provider_timestamp.isoformat()
        ),
        "received_via_failover": value.received_via_failover,
        "failover_count": value.failover_count,
        "raw_payload_hash": value.raw_payload_hash,
        "transformation_version": value.transformation_version,
    }


def _stored_provenance(value: Mapping[str, Any]) -> DataProvenance:
    timestamp = value["provider_timestamp"]
    return DataProvenance(
        str(value["provider_id"]),
        None if value["source_record_id"] is None else str(value["source_record_id"]),
        None if value["source_uri"] is None else str(value["source_uri"]),
        None if timestamp is None else datetime.fromisoformat(str(timestamp)),
        bool(value["received_via_failover"]),
        int(value["failover_count"]),
        str(value["raw_payload_hash"]),
        str(value["transformation_version"]),
    )


def _etf_identity(market: str, symbol: str) -> InstrumentIdentity:
    return InstrumentIdentity(Market(market), symbol, InstrumentType.ETF)


def _index_identity(symbol: str) -> InstrumentIdentity:
    return InstrumentIdentity(Market.INDEX_REFERENCE, symbol, InstrumentType.INDEX)


def _profile_values(value: ETFInstrumentProfile) -> dict[str, object]:
    return {
        "instrument_key": value.instrument.canonical_key,
        "market": value.instrument.market.value,
        "symbol": value.instrument.symbol,
        "display_name": value.display_name,
        "expanded_name": value.expanded_name,
        "listing_date": value.listing_date,
        "delisting_date": value.delisting_date,
        "listing_status": value.listing_status.value,
        "channel": value.channel.value,
        "benchmark_symbol": (
            None
            if value.benchmark_index_identity is None
            else value.benchmark_index_identity.symbol
        ),
        "fund_manager": value.fund_manager,
        "management_fee": value.management_fee,
        "underlying_market": value.underlying_market.value,
        "underlying_currency": value.underlying_currency.value,
        "trading_currency": value.trading_currency.value,
        "exposure_category": value.exposure_category.value,
        "exposure_family": value.exposure_family.value,
        "provenance": _provenance_json(value.provenance),
        "available_at": value.available_at,
    }


def _stored_profile(row: Mapping[str, Any]) -> ETFInstrumentProfile:
    benchmark = row["benchmark_symbol"]
    return ETFInstrumentProfile(
        _etf_identity(row["market"], row["symbol"]),
        row["display_name"],
        row["expanded_name"],
        row["listing_date"],
        row["delisting_date"],
        ListingStatus(row["listing_status"]),
        ETFChannel(row["channel"]),
        None if benchmark is None else _index_identity(benchmark),
        row["fund_manager"],
        row["management_fee"],
        ExposureMarket(row["underlying_market"]),
        Currency(row["underlying_currency"]),
        Currency(row["trading_currency"]),
        ExposureCategory(row["exposure_category"]),
        _stored_provenance(row["provenance"]),
        row["available_at"].astimezone(UTC),
        ExposureFamily(row["exposure_family"]),
    )


def _index_values(value: IndexReference) -> dict[str, object]:
    return {
        "index_key": value.index_identity.canonical_key,
        "symbol": value.index_identity.symbol,
        "display_name": value.display_name,
        "publisher": value.publisher,
        "base_date": value.base_date,
        "base_value": value.base_value,
        "exposure_market": value.exposure_market.value,
        "point_currency": value.point_currency.value,
        "provenance": _provenance_json(value.provenance),
        "available_at": value.available_at,
    }


def _stored_index(row: Mapping[str, Any]) -> IndexReference:
    return IndexReference(
        _index_identity(row["symbol"]),
        row["display_name"],
        row["publisher"],
        row["base_date"],
        row["base_value"],
        ExposureMarket(row["exposure_market"]),
        Currency(row["point_currency"]),
        _stored_provenance(row["provenance"]),
        row["available_at"].astimezone(UTC),
    )


def _relationship_values(value: ETFTracksIndex) -> dict[str, object]:
    return {
        "relationship_id": value.relationship_id,
        "etf_market": value.etf_instrument.market.value,
        "etf_symbol": value.etf_instrument.symbol,
        "benchmark_symbol": value.benchmark_index.symbol,
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "current_relationship_only": value.current_relationship_only,
        "provenance": _provenance_json(value.provenance),
        "available_at": value.available_at,
    }


def _stored_relationship(row: Mapping[str, Any]) -> ETFTracksIndex:
    return ETFTracksIndex(
        row["relationship_id"],
        _etf_identity(row["etf_market"], row["etf_symbol"]),
        _index_identity(row["benchmark_symbol"]),
        row["effective_from"],
        row["effective_to"],
        row["current_relationship_only"],
        _stored_provenance(row["provenance"]),
        row["available_at"].astimezone(UTC),
    )


def _valuation_values(value: ETFValuationSnapshot) -> dict[str, object]:
    return {
        "valuation_id": value.valuation_id,
        "market": value.instrument.market.value,
        "symbol": value.instrument.symbol,
        "trading_date": value.trading_date,
        "nav": value.nav,
        "close_price": value.close_price,
        "share_size": value.share_size,
        "premium_discount_pct": value.premium_discount_pct,
        "provenance": _provenance_json(value.provenance),
        "available_at": value.available_at,
    }


def _stored_valuation(row: Mapping[str, Any]) -> ETFValuationSnapshot:
    return ETFValuationSnapshot(
        row["valuation_id"],
        _etf_identity(row["market"], row["symbol"]),
        row["trading_date"],
        row["nav"],
        row["close_price"],
        row["share_size"],
        row["premium_discount_pct"],
        _stored_provenance(row["provenance"]),
        row["available_at"].astimezone(UTC),
    )


def _execution_values(value: InstrumentExecutionProfile) -> dict[str, object]:
    return {
        "profile_id": value.profile_id,
        "market": value.instrument.market.value,
        "symbol": value.instrument.symbol,
        "instrument_type": value.instrument.instrument_type.value,
        "trading_currency": value.trading_currency.value,
        "board_lot": value.board_lot,
        "settlement_capability": value.settlement_capability.value,
        "price_limit_policy_reference": value.price_limit_policy_reference,
        "calendar_reference": value.calendar_reference.value,
        "source": value.source,
        "available_at": value.available_at,
        "effective_from": value.effective_from,
        "policy_version": value.policy_version,
    }


def _stored_execution(row: Mapping[str, Any]) -> InstrumentExecutionProfile:
    return InstrumentExecutionProfile(
        row["profile_id"],
        InstrumentIdentity(
            Market(row["market"]), row["symbol"], InstrumentType(row["instrument_type"])
        ),
        Currency(row["trading_currency"]),
        row["board_lot"],
        SettlementCapability(row["settlement_capability"]),
        row["price_limit_policy_reference"],
        Market(row["calendar_reference"]),
        row["source"],
        row["available_at"].astimezone(UTC),
        row["effective_from"],
        row["policy_version"],
    )


class PostgreSQLETFDataRepository(ETFDataRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _save(
        self, table: Table, identity_column: str, values: dict[str, object]
    ) -> SaveResult:
        try:
            async with self._engine.begin() as connection:
                return await self._insert_or_verify(connection, table, identity_column, values)
        except PersistenceError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR, "ETF persistence transaction failed"
            ) from error

    @staticmethod
    async def _insert_or_verify(
        connection: AsyncConnection,
        table: Table,
        identity_column: str,
        values: dict[str, object],
    ) -> SaveResult:
        identity = str(values[identity_column])
        inserted = (
            await connection.execute(
                pg_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[identity_column])
                .returning(table.c[identity_column])
            )
        ).scalar_one_or_none()
        if inserted is not None:
            return SaveResult(SaveStatus.INSERTED, identity)
        row = (
            await connection.execute(
                select(table).where(table.c[identity_column] == values[identity_column])
            )
        ).mappings().one()
        if any(row[key] != value for key, value in values.items()):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                f"{identity_column} identifies different ETF evidence",
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, identity)

    async def _one(self, statement: Any) -> Mapping[str, Any] | None:
        try:
            async with self._engine.connect() as connection:
                row = (await connection.execute(statement)).mappings().one_or_none()
                return None if row is None else dict(row)
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "ETF persistence query failed"
            ) from error

    async def _many(self, statement: Any) -> tuple[Mapping[str, Any], ...]:
        try:
            async with self._engine.connect() as connection:
                rows = (await connection.execute(statement)).mappings().all()
                return tuple(dict(row) for row in rows)
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "ETF persistence query failed"
            ) from error

    async def save_etf_profile(self, value: ETFInstrumentProfile) -> SaveResult:
        return await self._save(
            etf_instrument_profiles, "instrument_key", _profile_values(value)
        )

    async def get_etf_profile(
        self, instrument: InstrumentIdentity
    ) -> ETFInstrumentProfile | None:
        row = await self._one(
            select(etf_instrument_profiles).where(
                etf_instrument_profiles.c.instrument_key == instrument.canonical_key
            )
        )
        return None if row is None else _stored_profile(row)

    async def save_index_reference(self, value: IndexReference) -> SaveResult:
        return await self._save(index_references, "index_key", _index_values(value))

    async def get_index_reference(
        self, identity: InstrumentIdentity
    ) -> IndexReference | None:
        row = await self._one(
            select(index_references).where(
                index_references.c.index_key == identity.canonical_key
            )
        )
        return None if row is None else _stored_index(row)

    async def save_relationship(self, value: ETFTracksIndex) -> SaveResult:
        return await self._save(
            etf_index_relationships, "relationship_id", _relationship_values(value)
        )

    async def list_relationships(
        self, instrument: InstrumentIdentity
    ) -> tuple[ETFTracksIndex, ...]:
        rows = await self._many(
            select(etf_index_relationships)
            .where(
                etf_index_relationships.c.etf_market == instrument.market.value,
                etf_index_relationships.c.etf_symbol == instrument.symbol,
            )
            .order_by(etf_index_relationships.c.available_at)
        )
        return tuple(_stored_relationship(row) for row in rows)

    async def save_valuation(self, value: ETFValuationSnapshot) -> SaveResult:
        return await self._save(
            etf_valuation_snapshots, "valuation_id", _valuation_values(value)
        )

    async def list_valuations(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[ETFValuationSnapshot, ...]:
        if end < start:
            raise ValueError("end must not precede start")
        rows = await self._many(
            select(etf_valuation_snapshots)
            .where(
                etf_valuation_snapshots.c.market == instrument.market.value,
                etf_valuation_snapshots.c.symbol == instrument.symbol,
                etf_valuation_snapshots.c.trading_date >= start,
                etf_valuation_snapshots.c.trading_date <= end,
            )
            .order_by(
                etf_valuation_snapshots.c.trading_date,
                etf_valuation_snapshots.c.available_at,
                etf_valuation_snapshots.c.valuation_id,
            )
        )
        return tuple(_stored_valuation(row) for row in rows)

    async def save_execution_profile(self, value: InstrumentExecutionProfile) -> SaveResult:
        return await self._save(
            instrument_execution_profiles, "profile_id", _execution_values(value)
        )

    async def list_execution_profiles(
        self, instrument: InstrumentIdentity
    ) -> tuple[InstrumentExecutionProfile, ...]:
        rows = await self._many(
            select(instrument_execution_profiles)
            .where(
                instrument_execution_profiles.c.market == instrument.market.value,
                instrument_execution_profiles.c.symbol == instrument.symbol,
                instrument_execution_profiles.c.instrument_type
                == instrument.instrument_type.value,
            )
            .order_by(
                instrument_execution_profiles.c.effective_from,
                instrument_execution_profiles.c.available_at,
                instrument_execution_profiles.c.profile_id,
            )
        )
        return tuple(_stored_execution(row) for row in rows)


class InMemoryETFDataRepository(ETFDataRepository):
    def __init__(self) -> None:
        self.profiles: dict[str, ETFInstrumentProfile] = {}
        self.indexes: dict[str, IndexReference] = {}
        self.relationships: dict[str, ETFTracksIndex] = {}
        self.valuations: dict[str, ETFValuationSnapshot] = {}
        self.execution_profiles: dict[str, InstrumentExecutionProfile] = {}

    @staticmethod
    def _save_memory[T](values: dict[str, T], key: str, value: T) -> SaveResult:
        existing = values.get(key)
        if existing is None:
            values[key] = value
            return SaveResult(SaveStatus.INSERTED, key)
        if existing != value:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "identity identifies different ETF evidence"
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, key)

    async def save_etf_profile(self, value: ETFInstrumentProfile) -> SaveResult:
        return self._save_memory(self.profiles, value.instrument.canonical_key, value)

    async def get_etf_profile(
        self, instrument: InstrumentIdentity
    ) -> ETFInstrumentProfile | None:
        return self.profiles.get(instrument.canonical_key)

    async def save_index_reference(self, value: IndexReference) -> SaveResult:
        return self._save_memory(self.indexes, value.index_identity.canonical_key, value)

    async def get_index_reference(
        self, identity: InstrumentIdentity
    ) -> IndexReference | None:
        return self.indexes.get(identity.canonical_key)

    async def save_relationship(self, value: ETFTracksIndex) -> SaveResult:
        return self._save_memory(self.relationships, value.relationship_id, value)

    async def list_relationships(
        self, instrument: InstrumentIdentity
    ) -> tuple[ETFTracksIndex, ...]:
        return tuple(
            sorted(
                (
                    value
                    for value in self.relationships.values()
                    if value.etf_instrument == instrument
                ),
                key=lambda value: value.available_at,
            )
        )

    async def save_valuation(self, value: ETFValuationSnapshot) -> SaveResult:
        return self._save_memory(self.valuations, value.valuation_id, value)

    async def list_valuations(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[ETFValuationSnapshot, ...]:
        if end < start:
            raise ValueError("end must not precede start")
        return tuple(
            sorted(
                (
                    value
                    for value in self.valuations.values()
                    if value.instrument == instrument and start <= value.trading_date <= end
                ),
                key=lambda value: (
                    value.trading_date,
                    value.available_at,
                    value.valuation_id,
                ),
            )
        )

    async def save_execution_profile(self, value: InstrumentExecutionProfile) -> SaveResult:
        return self._save_memory(self.execution_profiles, value.profile_id, value)

    async def list_execution_profiles(
        self, instrument: InstrumentIdentity
    ) -> tuple[InstrumentExecutionProfile, ...]:
        return tuple(
            sorted(
                (
                    value
                    for value in self.execution_profiles.values()
                    if value.instrument == instrument
                ),
                key=lambda value: (
                    value.effective_from,
                    value.available_at,
                    value.profile_id,
                ),
            )
        )
