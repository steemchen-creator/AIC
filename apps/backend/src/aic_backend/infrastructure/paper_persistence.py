"""Persistence adapters for forward paper-trading state and evidence."""

from collections.abc import Mapping
from typing import Any, cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import JSON, Column, Date, DateTime, MetaData, Numeric, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from aic_backend.application.ports.paper import PaperTradingRecord, PaperTradingRepository
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.paper import (
    PaperPerformanceSnapshot,
    PaperSession,
    PaperSessionStatus,
)

metadata = MetaData()

paper_accounts = Table(
    "paper_accounts",
    metadata,
    Column("account_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False, unique=True),
    Column("display_name", String(160), nullable=False),
    Column("initial_capital", Numeric(38, 10), nullable=False),
    Column("mode", String(32), nullable=False),
    Column("capital_mode", String(48), nullable=False),
    Column("status", String(24), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_finalized_date", Date, nullable=True),
    Column("recovery_projection", JSON, nullable=False),
)

paper_account_state_events = Table(
    "paper_account_state_events",
    metadata,
    Column("event_id", String(80), primary_key=True),
    Column("account_id", String(80), nullable=False),
    Column("session_id", String(80), nullable=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("operational_status", String(48), nullable=False),
    Column("from_status", String(32), nullable=True),
    Column("to_status", String(32), nullable=True),
    Column("payload", JSON, nullable=False),
)

paper_sessions = Table(
    "paper_sessions",
    metadata,
    Column("session_id", String(80), primary_key=True),
    Column("account_id", String(80), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("status", String(24), nullable=False),
    Column("planned_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finalized_at", DateTime(timezone=True), nullable=True),
    Column("policy_version", String(128), nullable=False),
    Column("payload", JSON, nullable=False),
)

paper_order_intents = Table(
    "paper_order_intents",
    metadata,
    Column("intent_id", String(80), primary_key=True),
    Column("account_id", String(80), nullable=False),
    Column("session_id", String(80), nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=False),
    Column("effective_trading_date", Date, nullable=False),
    Column("instrument_key", String(128), nullable=False),
    Column("source_reference", String(160), nullable=False),
    Column("timing", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
)

paper_performance_snapshots = Table(
    "paper_performance_snapshots",
    metadata,
    Column("snapshot_id", String(80), primary_key=True),
    Column("account_id", String(80), nullable=False),
    Column("session_id", String(80), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("cash", Numeric(38, 10), nullable=False),
    Column("market_value", Numeric(38, 10), nullable=False),
    Column("nav", Numeric(38, 10), nullable=False),
    Column("benchmark_value", Numeric(38, 10), nullable=False),
    Column("payload", JSON, nullable=False),
)

paper_trade_episodes = Table(
    "paper_trade_episodes",
    metadata,
    Column("episode_id", String(80), primary_key=True),
    Column("account_id", String(80), nullable=False),
    Column("instrument_key", String(128), nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True), nullable=False),
    Column("net_pnl", Numeric(38, 10), nullable=False),
    Column("payload", JSON, nullable=False),
)

_RECORD_ADAPTER = TypeAdapter(PaperTradingRecord)
_PERFORMANCE_ADAPTER = TypeAdapter(PaperPerformanceSnapshot)


def _record_json(record: PaperTradingRecord) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _RECORD_ADAPTER.dump_python(
            record,
            mode="json",
            warnings="none",
            fallback=_json_fallback,
        ),
    )


def _json_fallback(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"unsupported recovery projection value: {type(value).__name__}")


def _stored_record(value: Mapping[str, Any]) -> PaperTradingRecord:
    return _RECORD_ADAPTER.validate_python(value)


def _validate_update(existing: PaperTradingRecord, value: PaperTradingRecord) -> None:
    immutable_identity = (
        "portfolio_id",
        "display_name",
        "initial_capital",
        "mode",
        "capital_mode",
        "created_at",
    )
    if any(
        getattr(existing.account, field) != getattr(value.account, field)
        for field in immutable_identity
    ):
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT,
            "paper account identity identifies different evidence",
        )
    finalized = {
        item.session_id: item
        for item in existing.sessions
        if item.status is PaperSessionStatus.FINALIZED
    }
    incoming = {item.session_id: item for item in value.sessions}
    if any(incoming.get(key) != session for key, session in finalized.items()):
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT,
            "finalized paper session is immutable",
        )
    for collection_name in ("intents", "outcomes", "performance", "episodes", "events"):
        old_items = getattr(existing, collection_name)
        new_items = getattr(value, collection_name)
        if any(item not in new_items for item in old_items):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                f"paper {collection_name} evidence is append-only",
            )


class InMemoryPaperTradingRepository(PaperTradingRepository):
    def __init__(self) -> None:
        self._records: dict[str, PaperTradingRecord] = {}

    async def save(self, record: PaperTradingRecord) -> None:
        key = record.account.account_id
        existing = self._records.get(key)
        if existing is not None:
            _validate_update(existing, record)
        self._records[key] = record

    async def get(self, account_id: str) -> PaperTradingRecord | None:
        return self._records.get(account_id)


class PostgreSQLPaperTradingRepository(PaperTradingRepository):
    """Atomic current-state projection plus append-only normalized evidence."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, record: PaperTradingRecord) -> None:
        try:
            async with self._engine.begin() as connection:
                await self._save_account(connection, record)
                for session in record.sessions:
                    await self._save_session(connection, session)
                for intent in record.intents:
                    session_id = next(
                        item.session_id
                        for item in record.sessions
                        if item.trading_date == intent.effective_trading_date
                    )
                    await _insert_or_verify(
                        connection,
                        paper_order_intents,
                        "intent_id",
                        {
                            "intent_id": intent.intent_id,
                            "account_id": intent.account_id,
                            "session_id": session_id,
                            "submitted_at": intent.submitted_at,
                            "effective_trading_date": intent.effective_trading_date,
                            "instrument_key": intent.instrument.canonical_key,
                            "source_reference": intent.source_reference,
                            "timing": intent.timing.value,
                            "payload": {
                                "market": intent.instrument.market.value,
                                "symbol": intent.instrument.symbol,
                                "instrument_type": intent.instrument.instrument_type.value,
                                "side": intent.side.value,
                                "quantity": str(intent.quantity.value),
                                "requested_price": (
                                    None
                                    if intent.requested_price is None
                                    else str(intent.requested_price.value)
                                ),
                            },
                        },
                    )
                for snapshot in record.performance:
                    await _insert_or_verify(
                        connection,
                        paper_performance_snapshots,
                        "snapshot_id",
                        {
                            "snapshot_id": snapshot.snapshot_id,
                            "account_id": snapshot.account_id,
                            "session_id": snapshot.session_id,
                            "trading_date": snapshot.trading_date,
                            "as_of": snapshot.as_of,
                            "cash": snapshot.cash.amount,
                            "market_value": snapshot.market_value.amount,
                            "nav": snapshot.nav.amount,
                            "benchmark_value": snapshot.benchmark_value,
                            "payload": _PERFORMANCE_ADAPTER.dump_python(snapshot, mode="json"),
                        },
                    )
                for episode in record.episodes:
                    await _insert_or_verify(
                        connection,
                        paper_trade_episodes,
                        "episode_id",
                        {
                            "episode_id": episode.episode_id,
                            "account_id": episode.account_id,
                            "instrument_key": episode.instrument.canonical_key,
                            "opened_at": episode.opened_at,
                            "closed_at": episode.closed_at,
                            "net_pnl": episode.net_pnl.amount,
                            "payload": {
                                "market": episode.instrument.market.value,
                                "symbol": episode.instrument.symbol,
                                "instrument_type": episode.instrument.instrument_type.value,
                                "entry_cost": str(episode.entry_cost.amount),
                                "exit_proceeds": str(episode.exit_proceeds.amount),
                                "return_value": str(episode.return_value),
                                "holding_trading_days": episode.holding_trading_days,
                                "source_fill_ids": list(episode.source_fill_ids),
                            },
                        },
                    )
                for event in record.events:
                    await _insert_or_verify(
                        connection,
                        paper_account_state_events,
                        "event_id",
                        {
                            "event_id": event.event_id,
                            "account_id": event.account_id,
                            "session_id": event.session_id,
                            "occurred_at": event.occurred_at,
                            "event_type": event.event_type,
                            "source_id": event.source_id,
                            "operational_status": event.operational_status.value,
                            "from_status": event.from_status,
                            "to_status": event.to_status,
                            "payload": dict(event.payload),
                        },
                    )
        except PersistenceError:
            raise
        except (
            SQLAlchemyError,
            ValidationError,
            ValueError,
            TypeError,
            StopIteration,
        ) as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR,
                "paper trading persistence transaction failed",
            ) from error

    async def get(self, account_id: str) -> PaperTradingRecord | None:
        try:
            async with self._engine.connect() as connection:
                value = (
                    await connection.execute(
                        select(paper_accounts.c.recovery_projection).where(
                            paper_accounts.c.account_id == account_id
                        )
                    )
                ).scalar_one_or_none()
            return None if value is None else _stored_record(value)
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR,
                "stored paper trading recovery projection is invalid",
            ) from error

    async def _save_account(self, connection: AsyncConnection, record: PaperTradingRecord) -> None:
        account = record.account
        values = {
            "account_id": account.account_id,
            "portfolio_id": account.portfolio_id.value,
            "display_name": account.display_name,
            "initial_capital": account.initial_capital.amount,
            "mode": account.mode.value,
            "capital_mode": account.capital_mode.value,
            "status": account.status.value,
            "created_at": account.created_at,
            "updated_at": account.updated_at,
            "last_finalized_date": account.last_finalized_date,
            "recovery_projection": _record_json(record),
        }
        existing = (
            (
                await connection.execute(
                    select(paper_accounts).where(paper_accounts.c.account_id == account.account_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is None:
            await connection.execute(paper_accounts.insert().values(**values))
            return
        _validate_update(_stored_record(existing["recovery_projection"]), record)
        await connection.execute(
            paper_accounts.update()
            .where(paper_accounts.c.account_id == account.account_id)
            .values(**values)
        )

    @staticmethod
    async def _save_session(connection: AsyncConnection, session: PaperSession) -> None:
        values = {
            "session_id": session.session_id,
            "account_id": session.account_id,
            "trading_date": session.trading_date,
            "status": session.status.value,
            "planned_at": session.planned_at,
            "started_at": session.started_at,
            "finalized_at": session.finalized_at,
            "policy_version": session.policy_version,
            "payload": {},
        }
        existing = (
            (
                await connection.execute(
                    select(paper_sessions).where(paper_sessions.c.session_id == session.session_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is None:
            await connection.execute(paper_sessions.insert().values(**values))
            return
        if existing["status"] == PaperSessionStatus.FINALIZED.value:
            if any(existing[key] != value for key, value in values.items()):
                raise PersistenceError(
                    PersistenceErrorCode.IDENTITY_CONFLICT,
                    "finalized paper session is immutable",
                )
            return
        await connection.execute(
            paper_sessions.update()
            .where(paper_sessions.c.session_id == session.session_id)
            .values(**values)
        )


async def _insert_or_verify(
    connection: AsyncConnection,
    table: Table,
    identity_column: str,
    values: dict[str, Any],
) -> None:
    inserted = (
        await connection.execute(
            pg_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[identity_column])
            .returning(table.c[identity_column])
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return
    existing = (
        (
            await connection.execute(
                select(table).where(table.c[identity_column] == values[identity_column])
            )
        )
        .mappings()
        .one()
    )
    if any(existing[key] != value for key, value in values.items()):
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT,
            f"{table.name} identity identifies different evidence",
        )
