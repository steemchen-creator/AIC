"""PostgreSQL and deterministic in-memory corporate-action persistence."""

from datetime import UTC, date
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, MetaData, Numeric, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.domain.market_data import (
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)
from aic_backend.domain.market_data.corporate_actions import (
    AdjustmentFactor,
    CorporateAction,
    CorporateActionType,
)

metadata = MetaData()

adjustment_factors = Table(
    "adjustment_factors",
    metadata,
    Column("factor_id", String(128), primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("factor", Numeric(38, 18), nullable=False),
    Column("factor_version", String(128), nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("provider_timestamp", DateTime(timezone=True)),
    Column("provider_id", String(255), nullable=False),
    Column("source_record_id", String(255)),
    Column("source_uri", String(2048)),
    Column("raw_payload_hash", String(64), nullable=False),
    Column("transformation_version", String(255), nullable=False),
)

corporate_actions = Table(
    "corporate_actions",
    metadata,
    Column("action_id", String(160), primary_key=True),
    Column("market", String(32), nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("action_type", String(48), nullable=False),
    Column("record_date", Date),
    Column("ex_date", Date),
    Column("pay_date", Date),
    Column("effective_date", Date),
    Column("cash_amount", Numeric(38, 18)),
    Column("share_ratio", Numeric(38, 18)),
    Column("rights_price", Numeric(38, 18)),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("provider_timestamp", DateTime(timezone=True)),
    Column("provider_id", String(255), nullable=False),
    Column("source_record_id", String(255)),
    Column("source_uri", String(2048)),
    Column("raw_payload_hash", String(64), nullable=False),
    Column("transformation_version", String(255), nullable=False),
)


def _identity(row: RowMapping) -> InstrumentIdentity:
    return InstrumentIdentity(
        Market(row["market"]), row["symbol"], InstrumentType(row["instrument_type"])
    )


def _provenance(row: RowMapping) -> DataProvenance:
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


def _base(value: AdjustmentFactor | CorporateAction) -> dict[str, object]:
    return {
        "market": value.instrument.market.value,
        "symbol": value.instrument.symbol,
        "instrument_type": value.instrument.instrument_type.value,
        "retrieved_at": value.retrieved_at,
        "provider_timestamp": value.provenance.provider_timestamp,
        "provider_id": value.provenance.provider_id,
        "source_record_id": value.provenance.source_record_id,
        "source_uri": value.provenance.source_uri,
        "raw_payload_hash": value.provenance.raw_payload_hash,
        "transformation_version": value.provenance.transformation_version,
    }


class PostgreSQLAdjustmentFactorRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, value: AdjustmentFactor) -> SaveResult:
        values = _base(value) | {
            "factor_id": value.factor_id,
            "trading_date": value.trading_date,
            "factor": value.factor,
            "factor_version": value.factor_version,
        }
        try:
            async with self._engine.begin() as connection:
                inserted = (
                    await connection.execute(
                        pg_insert(adjustment_factors)
                        .values(**values)
                        .on_conflict_do_nothing()
                        .returning(adjustment_factors.c.factor_id)
                    )
                ).scalar_one_or_none()
                if inserted is not None:
                    return SaveResult(SaveStatus.INSERTED, value.factor_id)
                row = (
                    (
                        await connection.execute(
                            select(adjustment_factors).where(
                                adjustment_factors.c.factor_id == value.factor_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                if row["factor"] != value.factor or row["factor_version"] != value.factor_version:
                    raise PersistenceError(
                        PersistenceErrorCode.IDENTITY_CONFLICT,
                        "adjustment factor identity conflict",
                    )
                return SaveResult(SaveStatus.ALREADY_EXISTS, value.factor_id)
        except PersistenceError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "adjustment factor persistence unavailable"
            ) from error

    async def get_adjustment_factor(
        self, instrument: InstrumentIdentity, trading_date: date
    ) -> AdjustmentFactor | None:
        rows = await self.list_adjustment_factors(instrument, trading_date, trading_date)
        return rows[0] if rows else None

    async def list_adjustment_factors(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[AdjustmentFactor, ...]:
        if end < start:
            raise ValueError("end must not precede start")
        try:
            async with self._engine.connect() as connection:
                rows = (
                    (
                        await connection.execute(
                            select(adjustment_factors)
                            .where(
                                adjustment_factors.c.market == instrument.market.value,
                                adjustment_factors.c.symbol == instrument.symbol,
                                adjustment_factors.c.trading_date >= start,
                                adjustment_factors.c.trading_date <= end,
                            )
                            .order_by(adjustment_factors.c.trading_date)
                        )
                    )
                    .mappings()
                    .all()
                )
            return tuple(
                AdjustmentFactor(
                    row["factor_id"],
                    _identity(row),
                    row["trading_date"],
                    Decimal(row["factor"]),
                    row["factor_version"],
                    row["retrieved_at"].astimezone(UTC),
                    _provenance(row),
                )
                for row in rows
            )
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "adjustment factor query unavailable"
            ) from error


class PostgreSQLCorporateActionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, value: CorporateAction) -> SaveResult:
        values = _base(value) | {
            "action_id": value.action_id,
            "action_type": value.action_type.value,
            "record_date": value.record_date,
            "ex_date": value.ex_date,
            "pay_date": value.pay_date,
            "effective_date": value.effective_date,
            "cash_amount": value.cash_amount,
            "share_ratio": value.share_ratio,
            "rights_price": value.rights_price,
        }
        try:
            async with self._engine.begin() as connection:
                inserted = (
                    await connection.execute(
                        pg_insert(corporate_actions)
                        .values(**values)
                        .on_conflict_do_nothing()
                        .returning(corporate_actions.c.action_id)
                    )
                ).scalar_one_or_none()
                if inserted is not None:
                    return SaveResult(SaveStatus.INSERTED, value.action_id)
                row = (
                    (
                        await connection.execute(
                            select(corporate_actions).where(
                                corporate_actions.c.action_id == value.action_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                facts = (
                    "action_type",
                    "record_date",
                    "ex_date",
                    "pay_date",
                    "effective_date",
                    "cash_amount",
                    "share_ratio",
                    "rights_price",
                )
                if any(row[key] != values[key] for key in facts):
                    raise PersistenceError(
                        PersistenceErrorCode.IDENTITY_CONFLICT, "corporate action identity conflict"
                    )
                return SaveResult(SaveStatus.ALREADY_EXISTS, value.action_id)
        except PersistenceError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "corporate action persistence unavailable"
            ) from error

    async def get_corporate_action(self, action_id: str) -> CorporateAction | None:
        try:
            async with self._engine.connect() as connection:
                row = (
                    (
                        await connection.execute(
                            select(corporate_actions).where(
                                corporate_actions.c.action_id == action_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            return None if row is None else self._stored(row)
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "corporate action query unavailable"
            ) from error

    async def list_corporate_actions(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[CorporateAction, ...]:
        if end < start:
            raise ValueError("end must not precede start")
        try:
            async with self._engine.connect() as connection:
                rows = (
                    (
                        await connection.execute(
                            select(corporate_actions)
                            .where(
                                corporate_actions.c.market == instrument.market.value,
                                corporate_actions.c.symbol == instrument.symbol,
                                corporate_actions.c.effective_date >= start,
                                corporate_actions.c.effective_date <= end,
                            )
                            .order_by(
                                corporate_actions.c.effective_date, corporate_actions.c.action_id
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
            return tuple(self._stored(row) for row in rows)
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "corporate action query unavailable"
            ) from error

    @staticmethod
    def _stored(row: RowMapping) -> CorporateAction:
        return CorporateAction(
            row["action_id"],
            _identity(row),
            CorporateActionType(row["action_type"]),
            row["record_date"],
            row["ex_date"],
            row["pay_date"],
            row["effective_date"],
            row["cash_amount"],
            row["share_ratio"],
            row["rights_price"],
            row["retrieved_at"].astimezone(UTC),
            _provenance(row),
        )


class InMemoryAdjustmentFactorRepository:
    def __init__(self) -> None:
        self.values: dict[str, AdjustmentFactor] = {}

    async def save(self, value: AdjustmentFactor) -> SaveResult:
        old = self.values.get(value.factor_id)
        if old is None:
            self.values[value.factor_id] = value
            return SaveResult(SaveStatus.INSERTED, value.factor_id)
        if (old.factor, old.factor_version) != (value.factor, value.factor_version):
            raise PersistenceError(PersistenceErrorCode.IDENTITY_CONFLICT, "factor conflict")
        return SaveResult(SaveStatus.ALREADY_EXISTS, value.factor_id)

    async def get_adjustment_factor(
        self, instrument: InstrumentIdentity, trading_date: date
    ) -> AdjustmentFactor | None:
        return next(
            (
                v
                for v in self.values.values()
                if v.instrument == instrument and v.trading_date == trading_date
            ),
            None,
        )

    async def list_adjustment_factors(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[AdjustmentFactor, ...]:
        return tuple(
            sorted(
                (
                    v
                    for v in self.values.values()
                    if v.instrument == instrument and start <= v.trading_date <= end
                ),
                key=lambda v: v.trading_date,
            )
        )


class InMemoryCorporateActionRepository:
    def __init__(self) -> None:
        self.values: dict[str, CorporateAction] = {}

    async def save(self, value: CorporateAction) -> SaveResult:
        old = self.values.get(value.action_id)
        if old is None:
            self.values[value.action_id] = value
            return SaveResult(SaveStatus.INSERTED, value.action_id)
        if old != value:
            raise PersistenceError(PersistenceErrorCode.IDENTITY_CONFLICT, "action conflict")
        return SaveResult(SaveStatus.ALREADY_EXISTS, value.action_id)

    async def get_corporate_action(self, action_id: str) -> CorporateAction | None:
        return self.values.get(action_id)

    async def list_corporate_actions(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[CorporateAction, ...]:
        return tuple(
            sorted(
                (
                    v
                    for v in self.values.values()
                    if v.instrument == instrument
                    and v.effective_date is not None
                    and start <= v.effective_date <= end
                ),
                key=lambda v: (v.effective_date, v.action_id),
            )
        )
