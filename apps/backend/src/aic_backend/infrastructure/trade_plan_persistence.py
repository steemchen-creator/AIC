"""PostgreSQL and in-memory persistence for append-only Trade Plan evidence."""

from typing import Any, cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import JSON, Column, DateTime, Index, Integer, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.application.ports.trade_plan import TradePlanRepository
from aic_backend.application.trade_plan_record import TradePlanRecord
from aic_backend.domain.trade_plan import (
    PlanExecutionEvidence,
    TradePlanDirective,
    TradePlanError,
    TradePlanErrorCode,
    TradePlanId,
    TradePlanOutcome,
    TradePlanRevision,
    TradePlanStatus,
)

metadata = MetaData()

trade_plans = Table(
    "trade_plans",
    metadata,
    Column("plan_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("instrument_key", String(128), nullable=False),
    Column("instrument_type", String(32), nullable=False),
    Column("horizon", String(32), nullable=False),
    Column("style", String(32), nullable=False),
    Column("status", String(24), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("recovery_projection", JSON, nullable=False),
)
Index(
    "uq_trade_plans_active_portfolio_instrument",
    trade_plans.c.portfolio_id,
    trade_plans.c.instrument_key,
    unique=True,
    postgresql_where=trade_plans.c.status == TradePlanStatus.ACTIVE.value,
)

trade_plan_revisions = Table(
    "trade_plan_revisions",
    metadata,
    Column("plan_id", String(80), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("reason", String(255), nullable=False),
    Column("actor", String(200), nullable=False),
    Column("source", String(255), nullable=False),
    Column("snapshot", JSON, nullable=False),
)

trade_plan_directives = Table(
    "trade_plan_directives",
    metadata,
    Column("directive_id", String(80), primary_key=True),
    Column("plan_id", String(80), nullable=False),
    Column("plan_version", Integer, nullable=False),
    Column("directive_type", String(24), nullable=False),
    Column("decision_as_of", DateTime(timezone=True), nullable=False),
    Column("not_before", DateTime(timezone=True)),
    Column("payload", JSON, nullable=False),
)

trade_plan_execution_evidence = Table(
    "trade_plan_execution_evidence",
    metadata,
    Column("evidence_id", String(80), primary_key=True),
    Column("plan_id", String(80), nullable=False),
    Column("directive_id", String(80), nullable=False, unique=True),
    Column("order_id", String(80), nullable=False),
    Column("fill_id", String(80)),
    Column("executed_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)

trade_plan_outcomes = Table(
    "trade_plan_outcomes",
    metadata,
    Column("outcome_id", String(80), primary_key=True),
    Column("plan_id", String(80), nullable=False, unique=True),
    Column("terminal_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)

_RECORD_ADAPTER = TypeAdapter(TradePlanRecord)
_REVISION_ADAPTER = TypeAdapter(TradePlanRevision)
_DIRECTIVE_ADAPTER = TypeAdapter(TradePlanDirective)
_EXECUTION_ADAPTER = TypeAdapter(PlanExecutionEvidence)
_OUTCOME_ADAPTER = TypeAdapter(TradePlanOutcome)


def _record_json(value: TradePlanRecord) -> dict[str, Any]:
    return cast(dict[str, Any], _RECORD_ADAPTER.dump_python(value, mode="json"))


def _stored_record(value: dict[str, Any]) -> TradePlanRecord:
    return _RECORD_ADAPTER.validate_python(value)


def _validate_update(existing: TradePlanRecord, incoming: TradePlanRecord) -> None:
    old = existing.plan
    new = incoming.plan
    immutable: tuple[str, ...] = ("plan_id", "portfolio_id", "instrument", "created_at")
    if old.status is not TradePlanStatus.DRAFT:
        immutable += ("horizon", "style", "thesis")
    if any(getattr(old, name) != getattr(new, name) for name in immutable):
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT,
            "Trade Plan immutable identity or anti-relabel fields changed",
        )
    for name in ("revisions", "directives", "executions"):
        previous = getattr(existing, name)
        current = getattr(incoming, name)
        if current[: len(previous)] != previous:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                f"Trade Plan {name} evidence is append-only",
            )
    if existing.outcome is not None and incoming.outcome != existing.outcome:
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT, "Trade Plan outcome is immutable"
        )
    if old.status not in (TradePlanStatus.DRAFT, TradePlanStatus.ACTIVE) and old != new:
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT, "terminal Trade Plan is immutable"
        )
    if new.version < old.version:
        raise PersistenceError(PersistenceErrorCode.IDENTITY_CONFLICT, "stale Trade Plan version")


class InMemoryTradePlanRepository(TradePlanRepository):
    def __init__(self) -> None:
        self._records: dict[str, TradePlanRecord] = {}

    async def save(self, record: TradePlanRecord) -> None:
        existing = self._records.get(record.plan.plan_id.value)
        if existing is not None:
            _validate_update(existing, record)
        if record.plan.status is TradePlanStatus.ACTIVE:
            duplicate = next(
                (
                    value
                    for key, value in self._records.items()
                    if key != record.plan.plan_id.value
                    and value.plan.status is TradePlanStatus.ACTIVE
                    and value.plan.portfolio_id == record.plan.portfolio_id
                    and value.plan.instrument == record.plan.instrument
                ),
                None,
            )
            if duplicate is not None:
                raise TradePlanError(
                    TradePlanErrorCode.DUPLICATE_ACTIVE_PLAN,
                    "portfolio and instrument already have an active plan",
                )
        self._records[record.plan.plan_id.value] = record

    async def get(self, plan_id: TradePlanId) -> TradePlanRecord | None:
        return self._records.get(plan_id.value)

    async def get_active(self, portfolio_id: str, instrument_key: str) -> TradePlanRecord | None:
        return next(
            (
                value
                for value in self._records.values()
                if value.plan.portfolio_id.value == portfolio_id
                and value.plan.instrument.canonical_key == instrument_key
                and value.plan.status is TradePlanStatus.ACTIVE
            ),
            None,
        )

    async def list_for_pair(
        self, portfolio_id: str, instrument_key: str
    ) -> tuple[TradePlanRecord, ...]:
        return tuple(
            sorted(
                (
                    value
                    for value in self._records.values()
                    if value.plan.portfolio_id.value == portfolio_id
                    and value.plan.instrument.canonical_key == instrument_key
                ),
                key=lambda value: (value.plan.created_at, value.plan.plan_id.value),
            )
        )

    async def get_by_directive(
        self, directive_id: str
    ) -> tuple[TradePlanRecord, TradePlanDirective] | None:
        for record in self._records.values():
            directive = next(
                (item for item in record.directives if item.directive_id == directive_id), None
            )
            if directive is not None:
                return record, directive
        return None


class PostgreSQLTradePlanRepository(TradePlanRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, record: TradePlanRecord) -> None:
        try:
            async with self._engine.begin() as connection:
                existing_row = (
                    (
                        await connection.execute(
                            select(trade_plans)
                            .where(trade_plans.c.plan_id == record.plan.plan_id.value)
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing_row is not None:
                    _validate_update(_stored_record(existing_row["recovery_projection"]), record)
                await self._save_projection(connection, record, existing_row is None)
                for revision in record.revisions:
                    await _insert_or_verify(
                        connection,
                        trade_plan_revisions,
                        ("plan_id", "version"),
                        {
                            "plan_id": revision.plan_id.value,
                            "version": revision.version,
                            "effective_at": revision.effective_at,
                            "recorded_at": revision.recorded_at,
                            "reason": revision.reason,
                            "actor": revision.actor,
                            "source": revision.source,
                            "snapshot": _REVISION_ADAPTER.dump_python(revision, mode="json"),
                        },
                    )
                for directive in record.directives:
                    await _insert_or_verify(
                        connection,
                        trade_plan_directives,
                        ("directive_id",),
                        {
                            "directive_id": directive.directive_id,
                            "plan_id": directive.plan_id.value,
                            "plan_version": directive.plan_version,
                            "directive_type": directive.directive_type.value,
                            "decision_as_of": directive.decision_as_of,
                            "not_before": directive.not_before,
                            "payload": _DIRECTIVE_ADAPTER.dump_python(
                                directive, mode="json", exclude_defaults=True
                            ),
                        },
                    )
                for evidence in record.executions:
                    await _insert_or_verify(
                        connection,
                        trade_plan_execution_evidence,
                        ("evidence_id",),
                        {
                            "evidence_id": evidence.evidence_id,
                            "plan_id": evidence.plan_id.value,
                            "directive_id": evidence.directive_id,
                            "order_id": evidence.order_id,
                            "fill_id": evidence.fill_id,
                            "executed_at": evidence.executed_at,
                            "payload": _EXECUTION_ADAPTER.dump_python(evidence, mode="json"),
                        },
                    )
                if record.outcome is not None:
                    await _insert_or_verify(
                        connection,
                        trade_plan_outcomes,
                        ("outcome_id",),
                        {
                            "outcome_id": record.outcome.outcome_id,
                            "plan_id": record.outcome.plan_id.value,
                            "terminal_at": record.outcome.terminal_at,
                            "payload": _OUTCOME_ADAPTER.dump_python(record.outcome, mode="json"),
                        },
                    )
        except (PersistenceError, TradePlanError):
            raise
        except IntegrityError as error:
            raise TradePlanError(
                TradePlanErrorCode.DUPLICATE_ACTIVE_PLAN,
                "database active-plan uniqueness rejected the write",
            ) from error
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR,
                "Trade Plan persistence transaction failed",
            ) from error

    async def get(self, plan_id: TradePlanId) -> TradePlanRecord | None:
        try:
            async with self._engine.connect() as connection:
                value = (
                    await connection.execute(
                        select(trade_plans.c.recovery_projection).where(
                            trade_plans.c.plan_id == plan_id.value
                        )
                    )
                ).scalar_one_or_none()
            return None if value is None else _stored_record(value)
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR,
                "stored Trade Plan projection is invalid",
            ) from error

    async def get_active(self, portfolio_id: str, instrument_key: str) -> TradePlanRecord | None:
        async with self._engine.connect() as connection:
            value = (
                await connection.execute(
                    select(trade_plans.c.recovery_projection).where(
                        trade_plans.c.portfolio_id == portfolio_id,
                        trade_plans.c.instrument_key == instrument_key,
                        trade_plans.c.status == TradePlanStatus.ACTIVE.value,
                    )
                )
            ).scalar_one_or_none()
        return None if value is None else _stored_record(value)

    async def list_for_pair(
        self, portfolio_id: str, instrument_key: str
    ) -> tuple[TradePlanRecord, ...]:
        async with self._engine.connect() as connection:
            values = (
                await connection.execute(
                    select(trade_plans.c.recovery_projection)
                    .where(
                        trade_plans.c.portfolio_id == portfolio_id,
                        trade_plans.c.instrument_key == instrument_key,
                    )
                    .order_by(trade_plans.c.created_at, trade_plans.c.plan_id)
                )
            ).scalars()
        return tuple(_stored_record(value) for value in values)

    async def get_by_directive(
        self, directive_id: str
    ) -> tuple[TradePlanRecord, TradePlanDirective] | None:
        async with self._engine.connect() as connection:
            plan_id = (
                await connection.execute(
                    select(trade_plan_directives.c.plan_id).where(
                        trade_plan_directives.c.directive_id == directive_id
                    )
                )
            ).scalar_one_or_none()
        if plan_id is None:
            return None
        record = await self.get(TradePlanId(plan_id))
        if record is None:
            return None
        directive = next(item for item in record.directives if item.directive_id == directive_id)
        return record, directive

    async def _save_projection(
        self, connection: AsyncConnection, record: TradePlanRecord, create: bool
    ) -> None:
        plan = record.plan
        values = {
            "plan_id": plan.plan_id.value,
            "portfolio_id": plan.portfolio_id.value,
            "instrument_key": plan.instrument.canonical_key,
            "instrument_type": plan.instrument.instrument_type.value,
            "horizon": plan.horizon.value,
            "style": plan.style.value,
            "status": plan.status.value,
            "version": plan.version,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
            "recovery_projection": _record_json(record),
        }
        if create:
            await connection.execute(trade_plans.insert().values(**values))
        else:
            await connection.execute(
                trade_plans.update()
                .where(trade_plans.c.plan_id == plan.plan_id.value)
                .values(**values)
            )


async def _insert_or_verify(
    connection: AsyncConnection,
    table: Table,
    identity_columns: tuple[str, ...],
    values: dict[str, Any],
) -> None:
    inserted = (
        await connection.execute(
            pg_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=list(identity_columns))
            .returning(table.c[identity_columns[0]])
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return
    predicate = [table.c[name] == values[name] for name in identity_columns]
    existing = (await connection.execute(select(table).where(*predicate))).mappings().one()
    if any(existing[name] != value for name, value in values.items()):
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT,
            f"{table.name} identity identifies different evidence",
        )
