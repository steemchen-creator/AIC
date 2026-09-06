"""PostgreSQL and deterministic in-memory persistence for Shadow experiments."""

from typing import Any, cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import JSON, Column, Date, DateTime, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from aic_backend.application.ports.experiments import (
    ShadowExperimentRecord,
    ShadowExperimentRepository,
)
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode

metadata = MetaData()

shadow_experiment_groups = Table(
    "shadow_experiment_groups",
    metadata,
    Column("group_id", String(80), primary_key=True),
    Column("display_name", String(160), nullable=False),
    Column("policy_bundle_id", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("recovery_projection", JSON, nullable=False),
)

shadow_experiment_members = Table(
    "shadow_experiment_members",
    metadata,
    Column("account_id", String(80), primary_key=True),
    Column("group_id", String(80), nullable=False),
    Column("portfolio_id", String(80), nullable=False, unique=True),
    Column("portfolio_role", String(24), nullable=False),
    Column("role_identity", String(24), nullable=False),
    Column("manager_id", String(80), nullable=False),
    Column("decision_source_id", String(160), nullable=False),
    Column("policy_bundle_id", String(80), nullable=False),
    Column("payload", JSON, nullable=False),
)

shadow_group_sessions = Table(
    "shadow_group_sessions",
    metadata,
    Column("group_session_id", String(80), primary_key=True),
    Column("group_id", String(80), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("pit_cutoff", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finalized_at", DateTime(timezone=True), nullable=False),
    Column("status", String(40), nullable=False),
    Column("policy_bundle_id", String(80), nullable=False),
    Column("payload", JSON, nullable=False),
)

shadow_comparison_snapshots = Table(
    "shadow_comparison_snapshots",
    metadata,
    Column("comparison_id", String(80), primary_key=True),
    Column("group_id", String(80), nullable=False),
    Column("group_session_id", String(80), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("policy_bundle_id", String(80), nullable=False),
    Column("payload", JSON, nullable=False),
)

shadow_role_activities = Table(
    "shadow_role_activities",
    metadata,
    Column("activity_id", String(80), primary_key=True),
    Column("group_id", String(80), nullable=False),
    Column("group_session_id", String(80), nullable=True),
    Column("account_id", String(80), nullable=False),
    Column("manager_id", String(80), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("status", String(24), nullable=False),
    Column("reason_code", String(160), nullable=True),
    Column("payload", JSON, nullable=False),
)

shadow_role_profile_events = Table(
    "shadow_role_profile_events",
    metadata,
    Column("event_id", String(80), primary_key=True),
    Column("group_id", String(80), nullable=False),
    Column("account_id", String(80), nullable=False),
    Column("manager_id", String(80), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("previous_avatar_reference", String(512), nullable=False),
    Column("new_avatar_reference", String(512), nullable=False),
    Column("payload", JSON, nullable=False),
)

_RECORD_ADAPTER = TypeAdapter(ShadowExperimentRecord)


def _record_json(record: ShadowExperimentRecord) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _RECORD_ADAPTER.dump_python(record, mode="json", warnings="none"),
    )


def _stored_record(value: object) -> ShadowExperimentRecord:
    return _RECORD_ADAPTER.validate_python(value)


def _validate_update(
    existing: ShadowExperimentRecord, incoming: ShadowExperimentRecord
) -> None:
    if existing.manifest != incoming.manifest:
        raise PersistenceError(
            PersistenceErrorCode.IDENTITY_CONFLICT,
            "experiment group identity identifies a different immutable manifest",
        )
    for collection_name in ("sessions", "comparisons", "activities", "profile_events"):
        old_items = getattr(existing, collection_name)
        new_items = getattr(incoming, collection_name)
        if any(item not in new_items for item in old_items):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                f"experiment {collection_name} evidence is append-only",
            )


class InMemoryShadowExperimentRepository(ShadowExperimentRepository):
    def __init__(self) -> None:
        self._records: dict[str, ShadowExperimentRecord] = {}

    async def save(self, record: ShadowExperimentRecord) -> None:
        key = record.manifest.group_id
        existing = self._records.get(key)
        if existing is not None:
            _validate_update(existing, record)
        self._records[key] = record

    async def get(self, group_id: str) -> ShadowExperimentRecord | None:
        return self._records.get(group_id)


class PostgreSQLShadowExperimentRepository(ShadowExperimentRepository):
    """Atomic recovery projection with normalized immutable review evidence."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, record: ShadowExperimentRecord) -> None:
        projection = _record_json(record)
        manifest_json = cast(dict[str, Any], projection["manifest"])
        try:
            async with self._engine.begin() as connection:
                existing_value = (
                    await connection.execute(
                        select(shadow_experiment_groups.c.recovery_projection).where(
                            shadow_experiment_groups.c.group_id == record.manifest.group_id
                        )
                    )
                ).scalar_one_or_none()
                if existing_value is not None:
                    _validate_update(_stored_record(existing_value), record)
                    await connection.execute(
                        shadow_experiment_groups.update()
                        .where(
                            shadow_experiment_groups.c.group_id == record.manifest.group_id
                        )
                        .values(recovery_projection=projection)
                    )
                else:
                    await connection.execute(
                        shadow_experiment_groups.insert().values(
                            group_id=record.manifest.group_id,
                            display_name=record.manifest.display_name,
                            policy_bundle_id=record.manifest.policy_bundle.identity,
                            created_at=record.manifest.created_at,
                            recovery_projection=projection,
                        )
                    )
                members_json = cast(list[dict[str, Any]], manifest_json["members"])
                for member, payload in zip(record.manifest.members, members_json, strict=True):
                    await _insert_or_verify(
                        connection,
                        shadow_experiment_members,
                        "account_id",
                        {
                            "account_id": member.account_id,
                            "group_id": record.manifest.group_id,
                            "portfolio_id": member.portfolio_id.value,
                            "portfolio_role": member.definition.portfolio_role.value,
                            "role_identity": member.definition.profile.role_identity.value,
                            "manager_id": member.definition.profile.manager_id,
                            "decision_source_id": member.definition.decision_source.source_id,
                            "policy_bundle_id": member.policy_bundle_id,
                            "payload": payload,
                        },
                    )
                for session, payload in zip(
                    record.sessions,
                    cast(list[dict[str, Any]], projection["sessions"]),
                    strict=True,
                ):
                    await _insert_or_verify(
                        connection,
                        shadow_group_sessions,
                        "group_session_id",
                        {
                            "group_session_id": session.group_session_id,
                            "group_id": session.group_id,
                            "trading_date": session.trading_date,
                            "pit_cutoff": session.pit_cutoff,
                            "started_at": session.started_at,
                            "finalized_at": session.finalized_at,
                            "status": session.status.value,
                            "policy_bundle_id": session.policy_bundle_id,
                            "payload": payload,
                        },
                    )
                for comparison, payload in zip(
                    record.comparisons,
                    cast(list[dict[str, Any]], projection["comparisons"]),
                    strict=True,
                ):
                    await _insert_or_verify(
                        connection,
                        shadow_comparison_snapshots,
                        "comparison_id",
                        {
                            "comparison_id": comparison.comparison_id,
                            "group_id": comparison.group_id,
                            "group_session_id": comparison.group_session_id,
                            "trading_date": comparison.trading_date,
                            "as_of": comparison.as_of,
                            "policy_bundle_id": comparison.policy_bundle_id,
                            "payload": payload,
                        },
                    )
                for activity, payload in zip(
                    record.activities,
                    cast(list[dict[str, Any]], projection["activities"]),
                    strict=True,
                ):
                    await _insert_or_verify(
                        connection,
                        shadow_role_activities,
                        "activity_id",
                        {
                            "activity_id": activity.activity_id,
                            "group_id": activity.group_id,
                            "group_session_id": activity.group_session_id,
                            "account_id": activity.account_id,
                            "manager_id": activity.manager_id,
                            "occurred_at": activity.occurred_at,
                            "status": activity.status.value,
                            "reason_code": activity.reason_code,
                            "payload": payload,
                        },
                    )
                for event, payload in zip(
                    record.profile_events,
                    cast(list[dict[str, Any]], projection["profile_events"]),
                    strict=True,
                ):
                    await _insert_or_verify(
                        connection,
                        shadow_role_profile_events,
                        "event_id",
                        {
                            "event_id": event.event_id,
                            "group_id": event.group_id,
                            "account_id": event.account_id,
                            "manager_id": event.manager_id,
                            "occurred_at": event.occurred_at,
                            "previous_avatar_reference": event.previous_avatar_reference,
                            "new_avatar_reference": event.new_avatar_reference,
                            "payload": payload,
                        },
                    )
        except PersistenceError:
            raise
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR,
                "shadow experiment persistence transaction failed",
            ) from error

    async def get(self, group_id: str) -> ShadowExperimentRecord | None:
        try:
            async with self._engine.connect() as connection:
                value = (
                    await connection.execute(
                        select(shadow_experiment_groups.c.recovery_projection).where(
                            shadow_experiment_groups.c.group_id == group_id
                        )
                    )
                ).scalar_one_or_none()
            return None if value is None else _stored_record(value)
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR,
                "stored shadow experiment recovery projection is invalid",
            ) from error


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
