"""Trading-calendar persistence adapters."""

from collections.abc import Mapping
from datetime import UTC, date
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.calendar import (
    CalendarCoverageAttempt,
    CalendarCoverageRepository,
    TradingCalendarRepository,
)
from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.domain.market_data import DataProvenance, Market, TradingSession, TradingSessionDay

calendar_metadata = MetaData()
trading_calendar_days = Table(
    "trading_calendar_days",
    calendar_metadata,
    Column("market", String(32), primary_key=True),
    Column("trading_date", Date, primary_key=True),
    Column("is_open", Boolean, nullable=False),
    Column("morning_open", DateTime(timezone=True)),
    Column("break_start", DateTime(timezone=True)),
    Column("break_end", DateTime(timezone=True)),
    Column("session_close", DateTime(timezone=True)),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("provider_timestamp", DateTime(timezone=True)),
    Column("provider_id", String(255), nullable=False),
    Column("source_record_id", String(255)),
    Column("source_uri", String(2048)),
    Column("raw_payload_hash", String(64), nullable=False),
    Column("transformation_version", String(255), nullable=False),
)
calendar_backfill_attempts = Table(
    "calendar_backfill_attempts",
    calendar_metadata,
    Column("attempt_id", String(80), primary_key=True),
    Column("provider_id", String(255), nullable=False),
    Column("market", String(32), nullable=False),
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

_FACT_FIELDS = (
    "market",
    "trading_date",
    "is_open",
    "morning_open",
    "break_start",
    "break_end",
    "session_close",
)


def _values(day: TradingSessionDay) -> dict[str, object]:
    session, p = day.session, day.provenance
    return {
        "market": day.market.value,
        "trading_date": day.trading_date,
        "is_open": day.is_open,
        "morning_open": session.morning_open if session else None,
        "break_start": session.break_start if session else None,
        "break_end": session.break_end if session else None,
        "session_close": session.session_close if session else None,
        "retrieved_at": day.retrieved_at,
        "provider_timestamp": p.provider_timestamp,
        "provider_id": p.provider_id,
        "source_record_id": p.source_record_id,
        "source_uri": p.source_uri,
        "raw_payload_hash": p.raw_payload_hash,
        "transformation_version": p.transformation_version,
    }


def _stored(row: Mapping[str, Any] | RowMapping) -> TradingSessionDay:
    session = (
        None
        if not row["is_open"]
        else TradingSession(
            *(
                row[key].astimezone(UTC)
                for key in ("morning_open", "break_start", "break_end", "session_close")
            )
        )
    )
    p = DataProvenance(
        row["provider_id"],
        row["source_record_id"],
        row["source_uri"],
        row["provider_timestamp"],
        False,
        0,
        row["raw_payload_hash"],
        row["transformation_version"],
    )
    return TradingSessionDay(
        Market(row["market"]),
        row["trading_date"],
        row["is_open"],
        session,
        row["retrieved_at"].astimezone(UTC),
        p,
    )


class PostgreSQLTradingCalendarRepository(TradingCalendarRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, day: TradingSessionDay) -> SaveResult:
        values = _values(day)
        try:
            async with self._engine.begin() as c:
                inserted = (
                    await c.execute(
                        pg_insert(trading_calendar_days)
                        .values(**values)
                        .on_conflict_do_nothing()
                        .returning(trading_calendar_days.c.market)
                    )
                ).scalar_one_or_none()
                if inserted is not None:
                    return SaveResult(SaveStatus.INSERTED, day.identity)
                row = (
                    (
                        await c.execute(
                            select(trading_calendar_days).where(
                                trading_calendar_days.c.market == day.market.value,
                                trading_calendar_days.c.trading_date == day.trading_date,
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                if any(row[key] != values[key] for key in _FACT_FIELDS):
                    raise PersistenceError(
                        PersistenceErrorCode.IDENTITY_CONFLICT, "calendar identity conflict"
                    )
                return SaveResult(SaveStatus.ALREADY_EXISTS, day.identity)
        except PersistenceError:
            raise
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "calendar persistence unavailable"
            ) from error

    async def get_day(self, market: Market, trading_date: date) -> TradingSessionDay | None:
        rows = await self.list_days(market, trading_date, trading_date)
        return rows[0] if rows else None

    async def list_days(
        self, market: Market, start: date, end: date
    ) -> tuple[TradingSessionDay, ...]:
        if end < start:
            raise ValueError("end must not precede start")
        try:
            async with self._engine.connect() as c:
                rows = (
                    (
                        await c.execute(
                            select(trading_calendar_days)
                            .where(
                                trading_calendar_days.c.market == market.value,
                                trading_calendar_days.c.trading_date >= start,
                                trading_calendar_days.c.trading_date <= end,
                            )
                            .order_by(trading_calendar_days.c.trading_date)
                        )
                    )
                    .mappings()
                    .all()
                )
            return tuple(_stored(row) for row in rows)
        except (SQLAlchemyError, OSError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "calendar persistence unavailable"
            ) from error


class PostgreSQLCalendarCoverageRepository(CalendarCoverageRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, v: CalendarCoverageAttempt) -> None:
        try:
            async with self._engine.begin() as c:
                await c.execute(
                    insert(calendar_backfill_attempts).values(
                        attempt_id=v.attempt_id,
                        provider_id=v.provider_id,
                        market=v.market.value,
                        requested_start=v.interval.start,
                        requested_end=v.interval.end,
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
                PersistenceErrorCode.TRANSACTION_ERROR, "calendar metadata transaction failed"
            ) from error

    async def get_attempts(
        self, market: Market, start: date, end: date
    ) -> tuple[CalendarCoverageAttempt, ...]:
        try:
            async with self._engine.connect() as c:
                rows = (
                    (
                        await c.execute(
                            select(calendar_backfill_attempts)
                            .where(
                                calendar_backfill_attempts.c.market == market.value,
                                calendar_backfill_attempts.c.requested_end >= start,
                                calendar_backfill_attempts.c.requested_start <= end,
                            )
                            .order_by(calendar_backfill_attempts.c.requested_at)
                        )
                    )
                    .mappings()
                    .all()
                )
            return tuple(
                CalendarCoverageAttempt(
                    r["attempt_id"],
                    r["provider_id"],
                    Market(r["market"]),
                    DateInterval(r["requested_start"], r["requested_end"]),
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
        except (SQLAlchemyError, OSError) as error:
            raise PersistenceError(
                PersistenceErrorCode.UNAVAILABLE, "calendar metadata unavailable"
            ) from error


class InMemoryTradingCalendarRepository(TradingCalendarRepository):
    def __init__(self) -> None:
        self.days: dict[tuple[Market, date], TradingSessionDay] = {}

    async def save(self, day: TradingSessionDay) -> SaveResult:
        old = self.days.get((day.market, day.trading_date))
        if old is None:
            self.days[(day.market, day.trading_date)] = day
            return SaveResult(SaveStatus.INSERTED, day.identity)
        if old != day:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "calendar identity conflict"
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, day.identity)

    async def get_day(self, market: Market, trading_date: date) -> TradingSessionDay | None:
        return self.days.get((market, trading_date))

    async def list_days(
        self, market: Market, start: date, end: date
    ) -> tuple[TradingSessionDay, ...]:
        return tuple(
            sorted(
                (v for (m, d), v in self.days.items() if m is market and start <= d <= end),
                key=lambda v: v.trading_date,
            )
        )


class InMemoryCalendarCoverageRepository(CalendarCoverageRepository):
    def __init__(self) -> None:
        self.attempts: list[CalendarCoverageAttempt] = []

    async def record(self, attempt: CalendarCoverageAttempt) -> None:
        self.attempts.append(attempt)

    async def get_attempts(
        self, market: Market, start: date, end: date
    ) -> tuple[CalendarCoverageAttempt, ...]:
        return tuple(
            v
            for v in self.attempts
            if v.market is market and v.interval.end >= start and v.interval.start <= end
        )
