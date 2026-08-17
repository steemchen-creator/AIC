"""PostgreSQL and deterministic in-memory instrument persistence adapters."""

from datetime import UTC, date
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    MetaData,
    String,
    Table,
    insert,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.instruments import InstrumentCoverageAttempt
from aic_backend.application.ports.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.domain.market_data import (
    DataProvenance,
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentTradingState,
    InstrumentTradingStatus,
    InstrumentType,
    ListingStatus,
    Market,
)

instrument_metadata = MetaData()
instrument_masters = Table(
    "instrument_masters",
    instrument_metadata,
    Column("canonical_key", String(96), primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("display_name", String(255), nullable=False),
    Column("listing_date", Date),
    Column("delisting_date", Date),
    Column("listing_status", String(32), nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("provider_timestamp", DateTime(timezone=True)),
    Column("provider_id", String(255), nullable=False),
    Column("source_record_id", String(255)),
    Column("source_uri", String(2048)),
    Column("raw_payload_hash", String(64), nullable=False),
    Column("transformation_version", String(255), nullable=False),
)
instrument_trading_statuses = Table(
    "instrument_trading_statuses",
    instrument_metadata,
    Column("canonical_key", String(96), primary_key=True),
    Column("trading_date", Date, primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("state", String(32), nullable=False),
    Column("reason", String(512)),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("provider_timestamp", DateTime(timezone=True)),
    Column("provider_id", String(255), nullable=False),
    Column("source_record_id", String(255)),
    Column("source_uri", String(2048)),
    Column("raw_payload_hash", String(64), nullable=False),
    Column("transformation_version", String(255), nullable=False),
)
instrument_sync_attempts = Table(
    "instrument_sync_attempts",
    instrument_metadata,
    Column("attempt_id", String(80), primary_key=True),
    Column("provider_id", String(255), nullable=False),
    Column("capability", String(128), nullable=False),
    Column("market", String(32), nullable=False),
    Column("canonical_key", String(96)),
    Column("symbol", String(32)),
    Column("requested_start", Date),
    Column("requested_end", Date),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False),
    Column("status", String(32), nullable=False),
    Column("received_count", BigInteger, nullable=False),
    Column("persisted_count", BigInteger, nullable=False),
    Column("already_exists_count", BigInteger, nullable=False),
    Column("failed_count", BigInteger, nullable=False),
    Column("error_code", String(128)),
)


def _provenance(row: Any) -> DataProvenance:
    return DataProvenance(
        row["provider_id"],
        row["source_record_id"],
        row["source_uri"],
        row["provider_timestamp"],
        False,
        0,
        row["raw_payload_hash"],
        row["transformation_version"],
    )


def _identity(row: Any) -> InstrumentIdentity:
    return InstrumentIdentity(
        Market(row["market"]), row["symbol"], InstrumentType(row["instrument_type"])
    )


def _master_values(value: InstrumentMaster) -> dict[str, object]:
    p = value.provenance
    return {
        "canonical_key": value.instrument.canonical_key,
        "market": value.instrument.market.value,
        "symbol": value.instrument.symbol,
        "instrument_type": value.instrument.instrument_type.value,
        "display_name": value.display_name,
        "listing_date": value.listing_date,
        "delisting_date": value.delisting_date,
        "listing_status": value.listing_status.value,
        "retrieved_at": value.retrieved_at,
        "provider_timestamp": p.provider_timestamp,
        "provider_id": p.provider_id,
        "source_record_id": p.source_record_id,
        "source_uri": p.source_uri,
        "raw_payload_hash": p.raw_payload_hash,
        "transformation_version": p.transformation_version,
    }


def _status_values(value: InstrumentTradingStatus) -> dict[str, object]:
    p = value.provenance
    return {
        "canonical_key": value.instrument.canonical_key,
        "trading_date": value.trading_date,
        "market": value.instrument.market.value,
        "symbol": value.instrument.symbol,
        "instrument_type": value.instrument.instrument_type.value,
        "state": value.state.value,
        "reason": value.reason,
        "retrieved_at": value.retrieved_at,
        "provider_timestamp": p.provider_timestamp,
        "provider_id": p.provider_id,
        "source_record_id": p.source_record_id,
        "source_uri": p.source_uri,
        "raw_payload_hash": p.raw_payload_hash,
        "transformation_version": p.transformation_version,
    }


class PostgreSQLInstrumentMasterRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, value: InstrumentMaster) -> SaveResult:
        values = _master_values(value)
        try:
            async with self._engine.begin() as c:
                inserted = (
                    await c.execute(
                        pg_insert(instrument_masters)
                        .values(**values)
                        .on_conflict_do_nothing()
                        .returning(instrument_masters.c.canonical_key)
                    )
                ).scalar_one_or_none()
                if inserted is not None:
                    return SaveResult(SaveStatus.INSERTED, value.instrument.canonical_key)
                row = (
                    (
                        await c.execute(
                            select(instrument_masters).where(
                                instrument_masters.c.canonical_key == value.instrument.canonical_key
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                facts = (
                    "market",
                    "symbol",
                    "instrument_type",
                    "display_name",
                    "listing_date",
                    "delisting_date",
                    "listing_status",
                )
                if any(row[key] != values[key] for key in facts):
                    raise PersistenceError(
                        PersistenceErrorCode.IDENTITY_CONFLICT, "instrument identity conflict"
                    )
                return SaveResult(SaveStatus.ALREADY_EXISTS, value.instrument.canonical_key)
        except PersistenceError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "instrument persistence unavailable"
            ) from error

    async def get_instrument(self, identity: InstrumentIdentity) -> InstrumentMaster | None:
        return await self.find_instrument(identity.market, identity.symbol)

    async def find_instrument(self, market: Market, symbol: str) -> InstrumentMaster | None:
        try:
            async with self._engine.connect() as c:
                row = (
                    (
                        await c.execute(
                            select(instrument_masters).where(
                                instrument_masters.c.market == market.value,
                                instrument_masters.c.symbol == symbol.upper(),
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            return (
                None
                if row is None
                else InstrumentMaster(
                    _identity(row),
                    row["display_name"],
                    row["listing_date"],
                    row["delisting_date"],
                    ListingStatus(row["listing_status"]),
                    row["retrieved_at"].astimezone(UTC),
                    _provenance(row),
                )
            )
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "instrument query unavailable"
            ) from error

    async def list_instruments(self, market: Market | None = None) -> tuple[InstrumentMaster, ...]:
        try:
            query = select(instrument_masters)
            if market is not None:
                query = query.where(instrument_masters.c.market == market.value)
            query = query.order_by(instrument_masters.c.market, instrument_masters.c.symbol)
            async with self._engine.connect() as c:
                rows = (await c.execute(query)).mappings().all()
            return tuple(
                InstrumentMaster(
                    _identity(r),
                    r["display_name"],
                    r["listing_date"],
                    r["delisting_date"],
                    ListingStatus(r["listing_status"]),
                    r["retrieved_at"].astimezone(UTC),
                    _provenance(r),
                )
                for r in rows
            )
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "instrument query unavailable"
            ) from error


class PostgreSQLInstrumentTradingStatusRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, value: InstrumentTradingStatus) -> SaveResult:
        values = _status_values(value)
        record_id = f"{value.instrument.canonical_key}:{value.trading_date}"
        try:
            async with self._engine.begin() as c:
                inserted = (
                    await c.execute(
                        pg_insert(instrument_trading_statuses)
                        .values(**values)
                        .on_conflict_do_nothing()
                        .returning(instrument_trading_statuses.c.canonical_key)
                    )
                ).scalar_one_or_none()
                if inserted is not None:
                    return SaveResult(SaveStatus.INSERTED, record_id)
                row = (
                    (
                        await c.execute(
                            select(instrument_trading_statuses).where(
                                instrument_trading_statuses.c.canonical_key
                                == value.instrument.canonical_key,
                                instrument_trading_statuses.c.trading_date == value.trading_date,
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                if row["state"] != value.state.value or row["reason"] != value.reason:
                    raise PersistenceError(
                        PersistenceErrorCode.IDENTITY_CONFLICT, "trading-status identity conflict"
                    )
                return SaveResult(SaveStatus.ALREADY_EXISTS, record_id)
        except PersistenceError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "trading-status persistence unavailable"
            ) from error

    async def get_trading_status(
        self, instrument: InstrumentIdentity, trading_date: date
    ) -> InstrumentTradingStatus | None:
        rows = await self.list_trading_status(instrument, trading_date, trading_date)
        return rows[0] if rows else None

    async def list_trading_status(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[InstrumentTradingStatus, ...]:
        if end < start:
            raise ValueError("end must not precede start")
        try:
            async with self._engine.connect() as c:
                rows = (
                    (
                        await c.execute(
                            select(instrument_trading_statuses)
                            .where(
                                instrument_trading_statuses.c.canonical_key
                                == instrument.canonical_key,
                                instrument_trading_statuses.c.trading_date >= start,
                                instrument_trading_statuses.c.trading_date <= end,
                            )
                            .order_by(instrument_trading_statuses.c.trading_date)
                        )
                    )
                    .mappings()
                    .all()
                )
            return tuple(
                InstrumentTradingStatus(
                    _identity(r),
                    r["trading_date"],
                    InstrumentTradingState(r["state"]),
                    r["reason"],
                    r["retrieved_at"].astimezone(UTC),
                    _provenance(r),
                )
                for r in rows
            )
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "trading-status query unavailable"
            ) from error


class PostgreSQLInstrumentCoverageRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, v: InstrumentCoverageAttempt) -> None:
        try:
            async with self._engine.begin() as c:
                await c.execute(
                    insert(instrument_sync_attempts).values(
                        attempt_id=v.attempt_id,
                        provider_id=v.provider_id,
                        capability=v.capability,
                        market=v.market.value,
                        canonical_key=v.instrument.canonical_key if v.instrument else None,
                        symbol=v.instrument.symbol if v.instrument else None,
                        requested_start=v.interval.start if v.interval else None,
                        requested_end=v.interval.end if v.interval else None,
                        requested_at=v.requested_at,
                        completed_at=v.completed_at,
                        status=v.status.value,
                        received_count=v.received_count,
                        persisted_count=v.persisted_count,
                        already_exists_count=v.already_exists_count,
                        failed_count=v.failed_count,
                        error_code=v.error_code,
                    )
                )
        except (SQLAlchemyError, OSError) as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR, "instrument metadata transaction failed"
            ) from error

    async def get_attempts(
        self,
        capability: str,
        market: Market,
        instrument: InstrumentIdentity | None,
        start: date | None,
        end: date | None,
    ) -> tuple[InstrumentCoverageAttempt, ...]:
        try:
            query = select(instrument_sync_attempts).where(
                instrument_sync_attempts.c.capability == capability,
                instrument_sync_attempts.c.market == market.value,
            )
            if instrument is None:
                query = query.where(instrument_sync_attempts.c.canonical_key.is_(None))
            else:
                query = query.where(
                    instrument_sync_attempts.c.canonical_key == instrument.canonical_key
                )
            if start is not None:
                query = query.where(instrument_sync_attempts.c.requested_end >= start)
            if end is not None:
                query = query.where(instrument_sync_attempts.c.requested_start <= end)
            async with self._engine.connect() as c:
                rows = (
                    (await c.execute(query.order_by(instrument_sync_attempts.c.requested_at)))
                    .mappings()
                    .all()
                )
            return tuple(
                InstrumentCoverageAttempt(
                    r["attempt_id"],
                    r["provider_id"],
                    r["capability"],
                    Market(r["market"]),
                    None
                    if r["canonical_key"] is None
                    else InstrumentIdentity(
                        Market(r["market"]), r["symbol"], InstrumentType.EQUITY
                    ),
                    None
                    if r["requested_start"] is None
                    else DateInterval(r["requested_start"], r["requested_end"]),
                    r["requested_at"].astimezone(UTC),
                    r["completed_at"].astimezone(UTC),
                    BackfillAttemptStatus(r["status"]),
                    r["received_count"],
                    r["persisted_count"],
                    r["already_exists_count"],
                    r["failed_count"],
                    r["error_code"],
                )
                for r in rows
            )
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "instrument metadata unavailable"
            ) from error


class InMemoryInstrumentMasterRepository:
    def __init__(self) -> None:
        self.values: dict[InstrumentIdentity, InstrumentMaster] = {}

    async def save(self, value: InstrumentMaster) -> SaveResult:
        old = self.values.get(value.instrument)
        if old is None:
            self.values[value.instrument] = value
            return SaveResult(SaveStatus.INSERTED, value.instrument.canonical_key)
        if (old.display_name, old.listing_date, old.delisting_date, old.listing_status) != (
            value.display_name,
            value.listing_date,
            value.delisting_date,
            value.listing_status,
        ):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "instrument identity conflict"
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, value.instrument.canonical_key)

    async def get_instrument(self, identity: InstrumentIdentity) -> InstrumentMaster | None:
        return self.values.get(identity)

    async def find_instrument(self, market: Market, symbol: str) -> InstrumentMaster | None:
        return next(
            (
                v
                for k, v in self.values.items()
                if k.market is market and k.symbol == symbol.upper()
            ),
            None,
        )

    async def list_instruments(self, market: Market | None = None) -> tuple[InstrumentMaster, ...]:
        return tuple(
            sorted(
                (
                    v
                    for v in self.values.values()
                    if market is None or v.instrument.market is market
                ),
                key=lambda v: v.instrument.canonical_key,
            )
        )


class InMemoryInstrumentTradingStatusRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[InstrumentIdentity, date], InstrumentTradingStatus] = {}

    async def save(self, value: InstrumentTradingStatus) -> SaveResult:
        key = (value.instrument, value.trading_date)
        old = self.values.get(key)
        record_id = f"{value.instrument.canonical_key}:{value.trading_date}"
        if old is None:
            self.values[key] = value
            return SaveResult(SaveStatus.INSERTED, record_id)
        if (old.state, old.reason) != (value.state, value.reason):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "trading-status identity conflict"
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, record_id)

    async def get_trading_status(
        self, instrument: InstrumentIdentity, trading_date: date
    ) -> InstrumentTradingStatus | None:
        return self.values.get((instrument, trading_date))

    async def list_trading_status(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[InstrumentTradingStatus, ...]:
        return tuple(
            sorted(
                (v for (i, d), v in self.values.items() if i == instrument and start <= d <= end),
                key=lambda v: v.trading_date,
            )
        )


class InMemoryInstrumentCoverageRepository:
    def __init__(self) -> None:
        self.attempts: list[InstrumentCoverageAttempt] = []

    async def record(self, attempt: InstrumentCoverageAttempt) -> None:
        self.attempts.append(attempt)

    async def get_attempts(
        self,
        capability: str,
        market: Market,
        instrument: InstrumentIdentity | None,
        start: date | None,
        end: date | None,
    ) -> tuple[InstrumentCoverageAttempt, ...]:
        return tuple(
            v
            for v in self.attempts
            if v.capability == capability
            and v.market is market
            and v.instrument == instrument
            and (start is None or v.interval is not None and v.interval.end >= start)
            and (end is None or v.interval is not None and v.interval.start <= end)
        )
