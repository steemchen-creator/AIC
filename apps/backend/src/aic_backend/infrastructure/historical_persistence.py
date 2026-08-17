"""PostgreSQL and in-memory operational backfill metadata adapters."""

from collections.abc import Mapping
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
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.historical import (
    BackfillAttempt,
    BackfillAttemptStatus,
    BackfillMetadataRepository,
    DateInterval,
)
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market

historical_metadata = MetaData()

daily_bar_backfill_attempts = Table(
    "daily_bar_backfill_attempts",
    historical_metadata,
    Column("attempt_id", String(80), primary_key=True),
    Column("provider_id", String(255), nullable=False),
    Column("capability", String(255), nullable=False),
    Column("market", String(32), nullable=False),
    Column("symbol", String(64), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("requested_start", Date, nullable=False),
    Column("requested_end", Date, nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False),
    Column("status", String(32), nullable=False),
    Column("received_count", BigInteger, nullable=False),
    Column("persisted_count", BigInteger, nullable=False),
    Column("already_exists_count", BigInteger, nullable=False),
    Column("failed_count", BigInteger, nullable=False),
    Column("error_code", String(128)),
)


def _values(attempt: BackfillAttempt) -> dict[str, object]:
    return {
        "attempt_id": attempt.attempt_id,
        "provider_id": attempt.provider_id,
        "capability": attempt.capability,
        "market": attempt.instrument.market.value,
        "symbol": attempt.instrument.symbol,
        "instrument_type": attempt.instrument.instrument_type.value,
        "requested_start": attempt.interval.start,
        "requested_end": attempt.interval.end,
        "requested_at": attempt.requested_at,
        "completed_at": attempt.completed_at,
        "status": attempt.status.value,
        "received_count": attempt.received_count,
        "persisted_count": attempt.persisted_count,
        "already_exists_count": attempt.already_exists_count,
        "failed_count": attempt.failed_count,
        "error_code": attempt.error_code,
    }


def _attempt(row: Mapping[str, Any] | RowMapping) -> BackfillAttempt:
    return BackfillAttempt(
        row["attempt_id"],
        row["provider_id"],
        row["capability"],
        InstrumentIdentity(
            Market(row["market"]), row["symbol"], InstrumentType(row["instrument_type"])
        ),
        DateInterval(row["requested_start"], row["requested_end"]),
        row["requested_at"].astimezone(UTC),
        row["completed_at"].astimezone(UTC),
        BackfillAttemptStatus(row["status"]),
        row["received_count"],
        row["persisted_count"],
        row["already_exists_count"],
        row["failed_count"],
        row["error_code"],
    )


class PostgreSQLBackfillMetadataRepository(BackfillMetadataRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, attempt: BackfillAttempt) -> None:
        try:
            async with self._engine.begin() as connection:
                await connection.execute(
                    insert(daily_bar_backfill_attempts).values(**_values(attempt))
                )
        except (SQLAlchemyError, OSError) as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR,
                "backfill metadata transaction failed",
            ) from error

    async def get_attempts(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
    ) -> tuple[BackfillAttempt, ...]:
        statement = (
            select(daily_bar_backfill_attempts)
            .where(
                daily_bar_backfill_attempts.c.market == instrument.market.value,
                daily_bar_backfill_attempts.c.symbol == instrument.symbol,
                daily_bar_backfill_attempts.c.instrument_type
                == instrument.instrument_type.value,
                daily_bar_backfill_attempts.c.requested_end >= start,
                daily_bar_backfill_attempts.c.requested_start <= end,
            )
            .order_by(daily_bar_backfill_attempts.c.requested_at.asc())
        )
        try:
            async with self._engine.connect() as connection:
                rows = (await connection.execute(statement)).mappings().all()
            return tuple(_attempt(row) for row in rows)
        except (SQLAlchemyError, OSError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE,
                "backfill metadata is unavailable",
            ) from error


class InMemoryBackfillMetadataRepository(BackfillMetadataRepository):
    def __init__(self) -> None:
        self._attempts: list[BackfillAttempt] = []

    async def record(self, attempt: BackfillAttempt) -> None:
        self._attempts.append(attempt)

    async def get_attempts(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
    ) -> tuple[BackfillAttempt, ...]:
        return tuple(
            item
            for item in self._attempts
            if item.instrument == instrument
            and item.interval.end >= start
            and item.interval.start <= end
        )
