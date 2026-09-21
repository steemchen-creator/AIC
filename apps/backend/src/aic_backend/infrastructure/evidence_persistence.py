"""PostgreSQL and in-memory persistence for macro, schedules, and fenced acquisition."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.evidence import (
    AcquisitionPlanRepository,
    MacroObservationRepository,
    PolicyEventEvidenceRepository,
    ScheduledEventRepository,
)
from aic_backend.application.ports.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.domain.evidence import (
    AcquisitionCheckpoint,
    AcquisitionClaim,
    AcquisitionPlan,
    DocumentType,
    EntityIdentity,
    EntityType,
    EventCandidate,
    EventDocumentLink,
    EventDocumentRelation,
    EvidenceQuarantine,
    EvidenceVerification,
    MacroFrequency,
    MacroObservation,
    MacroQueryMode,
    MacroSeriesIdentity,
    ScheduledEvent,
    ScheduledEventStatus,
    ScheduledEventType,
    SeasonalAdjustment,
    SourceDocument,
)
from aic_backend.domain.market_data import AuthorityLevel, SourceLineage, SourceType

metadata = MetaData()

macro_series = Table(
    "macro_series",
    metadata,
    Column("series_id", String(96), primary_key=True),
    Column("title", Text, nullable=False),
    Column("geography", String(96), nullable=False),
    Column("source_agency_id", String(96), nullable=False),
    Column("unit", String(96), nullable=False),
    Column("frequency", String(32), nullable=False),
    Column("seasonal_adjustment", String(48), nullable=False),
)
macro_observations = Table(
    "macro_observations",
    metadata,
    Column("observation_id", String(96), primary_key=True),
    Column("raw_observation_id", String(96), nullable=False),
    Column(
        "series_id", String(96), ForeignKey("macro_series.series_id"), nullable=False, index=True
    ),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("value", Numeric(38, 12), nullable=False),
    Column("release_at", DateTime(timezone=True), nullable=False),
    Column("realtime_start", Date, nullable=False),
    Column("realtime_end", Date, nullable=False),
    Column("vintage_date", Date, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("predecessor_observation_id", String(96)),
    Column("adapter_id", String(64), nullable=False),
    Column("upstream_source_id", String(96), nullable=False),
    Column("authority_level", String(32), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("raw_hash", String(64), nullable=False),
    Column("transformation_version", String(96), nullable=False),
    Column("source_uri", String(2048)),
    Column("source_record_id", String(255)),
    Column("license_id", String(96)),
)
scheduled_events = Table(
    "scheduled_events",
    metadata,
    Column("event_version_id", String(96), primary_key=True),
    Column("event_id", String(96), nullable=False, index=True),
    Column("event_type", String(48), nullable=False),
    Column("subject_id", String(160), nullable=False),
    Column("scheduled_start", DateTime(timezone=True), nullable=False),
    Column("scheduled_end", DateTime(timezone=True)),
    Column("timezone", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("version", Integer, nullable=False),
    Column("predecessor_version_id", String(96)),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("actual_evidence_ids", ARRAY(String(96)), nullable=False),
    Column("adapter_id", String(64), nullable=False),
    Column("upstream_source_id", String(96), nullable=False),
    Column("authority_level", String(32), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("raw_hash", String(64), nullable=False),
    Column("transformation_version", String(96), nullable=False),
    Column("source_uri", String(2048)),
    Column("source_record_id", String(255)),
    Column("license_id", String(96)),
)
acquisition_plans = Table(
    "acquisition_plans",
    metadata,
    Column("plan_id", String(96), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("capability", String(96), nullable=False),
    Column("scope_id", String(160), nullable=False),
    Column("preferred_provider_ids", ARRAY(String(64)), nullable=False),
    Column("cadence_kind", String(32), nullable=False),
    Column("interval_seconds", BigInteger, nullable=False),
    Column("overlap_seconds", BigInteger, nullable=False),
    Column("release_window_interval_seconds", BigInteger, nullable=False),
    Column("release_window_before_seconds", BigInteger, nullable=False),
    Column("release_window_after_seconds", BigInteger, nullable=False),
)
acquisition_checkpoints = Table(
    "acquisition_checkpoints",
    metadata,
    Column("plan_id", String(96), primary_key=True),
    Column("plan_version", Integer, nullable=False),
    Column("next_due_at", DateTime(timezone=True), nullable=False),
    Column("cursor", Text),
    Column("watermark", DateTime(timezone=True)),
    Column("last_attempt_at", DateTime(timezone=True)),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_persisted_id", String(96)),
    Column("consecutive_failures", Integer, nullable=False, default=0),
    Column("retry_not_before", DateTime(timezone=True)),
    Column("rate_limit_reset_at", DateTime(timezone=True)),
    Column("lease_owner", String(96)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("fencing_token", BigInteger, nullable=False, default=0),
    Column("active", Boolean, nullable=False, default=True),
)
evidence_entities = Table(
    "evidence_entities",
    metadata,
    Column("entity_id", String(160), primary_key=True),
    Column("entity_type", String(32), nullable=False),
    Column("namespace", String(96), nullable=False),
    Column("official_identifier", String(255), nullable=False),
    Column("canonical_name", Text, nullable=False),
    Column("aliases", ARRAY(Text), nullable=False),
    UniqueConstraint("namespace", "official_identifier", name="uq_evidence_entity_authority"),
)
source_documents = Table(
    "source_documents",
    metadata,
    Column("document_version_id", String(96), primary_key=True),
    Column("document_id", String(160), nullable=False, index=True),
    Column(
        "publisher_entity_id",
        String(160),
        ForeignKey("evidence_entities.entity_id"),
        nullable=False,
    ),
    Column("document_type", String(48), nullable=False),
    Column("title", Text, nullable=False),
    Column("language", String(32), nullable=False),
    Column("speaker_entity_id", String(160), ForeignKey("evidence_entities.entity_id")),
    Column("source_declared_role", Text),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("source_uri", String(2048), nullable=False),
    Column("source_record_id", String(255), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("raw_observation_id", String(96), nullable=False),
    Column("normalized_text_hash", String(64)),
    Column("version", Integer, nullable=False),
    Column(
        "predecessor_version_id", String(96), ForeignKey("source_documents.document_version_id")
    ),
    Column("verification", String(32), nullable=False),
    Column("adapter_id", String(64), nullable=False),
    Column("upstream_source_id", String(96), nullable=False),
    Column("authority_level", String(32), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("raw_hash", String(64), nullable=False),
    Column("transformation_version", String(96), nullable=False),
    Column("license_id", String(96)),
)
event_candidates = Table(
    "event_candidates",
    metadata,
    Column("candidate_id", String(96), primary_key=True),
    Column("event_category", String(96), nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("detected_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("entity_ids", ARRAY(String(160)), nullable=False),
    Column("location_codes", ARRAY(String(64)), nullable=False),
    Column("source_document_version_ids", ARRAY(String(96)), nullable=False),
    Column("authority_level", String(32), nullable=False),
    Column("confidence", Numeric(8, 7), nullable=False),
    Column("verification", String(32), nullable=False),
    Column("adapter_id", String(64), nullable=False),
    Column("upstream_source_id", String(96), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("raw_hash", String(64), nullable=False),
    Column("transformation_version", String(96), nullable=False),
    Column("source_uri", String(2048)),
    Column("source_record_id", String(255)),
    Column("license_id", String(96)),
)
event_document_links = Table(
    "event_document_links",
    metadata,
    Column("link_id", String(96), primary_key=True),
    Column("candidate_id", String(96), ForeignKey("event_candidates.candidate_id"), nullable=False),
    Column(
        "document_version_id",
        String(96),
        ForeignKey("source_documents.document_version_id"),
        nullable=False,
    ),
    Column("relation", String(32), nullable=False),
    Column("linked_at", DateTime(timezone=True), nullable=False),
)
evidence_quarantines = Table(
    "evidence_quarantines",
    metadata,
    Column("quarantine_id", String(96), primary_key=True),
    Column("raw_observation_id", String(96), nullable=False, index=True),
    Column("upstream_source_id", String(96), nullable=False),
    Column("reason_code", String(96), nullable=False),
    Column("detail", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
)


def _lineage_values(value: SourceLineage) -> dict[str, object]:
    return {
        "adapter_id": value.adapter_id,
        "upstream_source_id": value.upstream_source_id,
        "authority_level": value.authority_level.value,
        "source_type": value.source_type.value,
        "event_time": value.event_time,
        "published_at": value.published_at,
        "raw_hash": value.raw_hash,
        "transformation_version": value.transformation_version,
        "source_uri": value.source_uri,
        "source_record_id": value.source_record_id,
        "license_id": value.license_id,
    }


def _lineage(
    row: Mapping[str, Any] | RowMapping, observed_at: datetime, ingested_at: datetime
) -> SourceLineage:
    return SourceLineage(
        row["adapter_id"],
        row["upstream_source_id"],
        AuthorityLevel(row["authority_level"]),
        SourceType(row["source_type"]),
        row["event_time"].astimezone(UTC),
        observed_at,
        ingested_at,
        row["raw_hash"],
        row["transformation_version"],
        row["published_at"].astimezone(UTC),
        row["source_uri"],
        row["source_record_id"],
        row["license_id"],
    )


async def _immutable_save(
    engine: AsyncEngine,
    table: Table,
    keys: tuple[str, ...],
    values: Mapping[str, object],
    record_id: str,
) -> SaveResult:
    async with engine.begin() as connection:
        statement = (
            postgresql_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=list(keys))
            .returning(table.c[keys[0]])
        )
        if (await connection.execute(statement)).scalar_one_or_none() is not None:
            return SaveResult(SaveStatus.INSERTED, record_id)
        predicate = and_(*(table.c[key] == values[key] for key in keys))
        stored = (await connection.execute(select(table).where(predicate))).mappings().one()
        if any(stored[name] != value for name, value in values.items()):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "immutable evidence identity conflict"
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, record_id)


def _series_values(value: MacroSeriesIdentity) -> dict[str, object]:
    return {
        "series_id": value.series_id,
        "title": value.title,
        "geography": value.geography,
        "source_agency_id": value.source_agency_id,
        "unit": value.unit,
        "frequency": value.frequency.value,
        "seasonal_adjustment": value.seasonal_adjustment.value,
    }


def _series(row: Mapping[str, Any] | RowMapping) -> MacroSeriesIdentity:
    return MacroSeriesIdentity(
        row["series_id"],
        row["title"],
        row["geography"],
        row["source_agency_id"],
        row["unit"],
        MacroFrequency(row["frequency"]),
        SeasonalAdjustment(row["seasonal_adjustment"]),
    )


def _macro(row: Mapping[str, Any] | RowMapping, series: MacroSeriesIdentity) -> MacroObservation:
    observed, ingested = row["observed_at"].astimezone(UTC), row["ingested_at"].astimezone(UTC)
    return MacroObservation(
        row["observation_id"],
        series,
        row["period_start"],
        row["period_end"],
        row["value"],
        row["release_at"].astimezone(UTC),
        row["realtime_start"],
        row["realtime_end"],
        row["vintage_date"],
        observed,
        ingested,
        _lineage(row, observed, ingested),
        row["predecessor_observation_id"],
    )


def _select_macro(
    values: tuple[MacroObservation, ...],
    mode: MacroQueryMode,
    as_of: datetime | None,
    vintage_date: date | None,
) -> tuple[MacroObservation, ...]:
    if mode is MacroQueryMode.KNOWN_AT:
        if as_of is None or as_of.tzinfo is None:
            raise ValueError("KNOWN_AT requires aware as_of")
        eligible = [
            value for value in values if max(value.source_known_at, value.observed_at) <= as_of
        ]
    elif mode is MacroQueryMode.AS_PUBLISHED:
        if vintage_date is None:
            raise ValueError("AS_PUBLISHED requires vintage_date")
        eligible = [
            value for value in values if value.realtime_start <= vintage_date <= value.realtime_end
        ]
    else:
        eligible = list(values)
    latest: dict[date, MacroObservation] = {}
    for value in eligible:
        current = latest.get(value.period_start)
        if current is None or (value.realtime_start, value.observation_id) > (
            current.realtime_start,
            current.observation_id,
        ):
            latest[value.period_start] = value
    return tuple(
        sorted(latest.values(), key=lambda value: (value.period_start, value.observation_id))
    )


def _checkpoint(row: Mapping[str, Any] | RowMapping) -> AcquisitionCheckpoint:
    def utc(value: datetime | None) -> datetime | None:
        return None if value is None else value.astimezone(UTC)

    return AcquisitionCheckpoint(
        row["plan_id"],
        row["plan_version"],
        row["next_due_at"].astimezone(UTC),
        row["cursor"],
        utc(row["watermark"]),
        utc(row["last_attempt_at"]),
        utc(row["last_success_at"]),
        row["last_persisted_id"],
        row["consecutive_failures"],
        utc(row["retry_not_before"]),
        utc(row["rate_limit_reset_at"]),
        row["lease_owner"],
        utc(row["lease_expires_at"]),
        row["fencing_token"],
    )


def _entity(row: Mapping[str, Any] | RowMapping) -> EntityIdentity:
    return EntityIdentity(
        row["entity_id"],
        EntityType(row["entity_type"]),
        row["namespace"],
        row["official_identifier"],
        row["canonical_name"],
        tuple(row["aliases"]),
    )


def _document(row: Mapping[str, Any] | RowMapping) -> SourceDocument:
    observed, ingested = row["observed_at"].astimezone(UTC), row["ingested_at"].astimezone(UTC)
    return SourceDocument(
        row["document_version_id"],
        row["document_id"],
        row["publisher_entity_id"],
        DocumentType(row["document_type"]),
        row["title"],
        row["language"],
        row["event_time"].astimezone(UTC),
        row["published_at"].astimezone(UTC),
        observed,
        ingested,
        row["source_uri"],
        row["source_record_id"],
        row["content_hash"],
        row["raw_observation_id"],
        row["version"],
        row["predecessor_version_id"],
        EvidenceVerification(row["verification"]),
        _lineage(row, observed, ingested),
        row["speaker_entity_id"],
        row["source_declared_role"],
        row["normalized_text_hash"],
    )


def _candidate(row: Mapping[str, Any] | RowMapping) -> EventCandidate:
    observed, ingested = row["observed_at"].astimezone(UTC), row["ingested_at"].astimezone(UTC)
    return EventCandidate(
        row["candidate_id"],
        row["event_category"],
        row["event_time"].astimezone(UTC),
        row["detected_at"].astimezone(UTC),
        observed,
        ingested,
        tuple(row["entity_ids"]),
        tuple(row["location_codes"]),
        tuple(row["source_document_version_ids"]),
        AuthorityLevel(row["authority_level"]),
        row["confidence"],
        EvidenceVerification(row["verification"]),
        _lineage(row, observed, ingested),
    )


class PostgreSQLEvidenceRepository(
    MacroObservationRepository,
    ScheduledEventRepository,
    AcquisitionPlanRepository,
    PolicyEventEvidenceRepository,
):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_series(self, value: MacroSeriesIdentity) -> SaveResult:
        return await _immutable_save(
            self._engine, macro_series, ("series_id",), _series_values(value), value.series_id
        )

    async def save_macro(self, raw_observation_id: str, value: MacroObservation) -> SaveResult:
        values = {
            "observation_id": value.observation_id,
            "raw_observation_id": raw_observation_id,
            "series_id": value.series.series_id,
            "period_start": value.period_start,
            "period_end": value.period_end,
            "value": value.value,
            "release_at": value.release_at,
            "realtime_start": value.realtime_start,
            "realtime_end": value.realtime_end,
            "vintage_date": value.vintage_date,
            "observed_at": value.observed_at,
            "ingested_at": value.ingested_at,
            "predecessor_observation_id": value.predecessor_observation_id,
            **_lineage_values(value.lineage),
        }
        return await _immutable_save(
            self._engine, macro_observations, ("observation_id",), values, value.observation_id
        )

    async def query_macro(
        self,
        series_id: str,
        mode: MacroQueryMode,
        *,
        as_of: datetime | None = None,
        vintage_date: date | None = None,
    ) -> tuple[MacroObservation, ...]:
        async with self._engine.connect() as connection:
            series_row = (
                (
                    await connection.execute(
                        select(macro_series).where(macro_series.c.series_id == series_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            rows = (
                (
                    await connection.execute(
                        select(macro_observations)
                        .where(macro_observations.c.series_id == series_id)
                        .order_by(
                            macro_observations.c.period_start, macro_observations.c.realtime_start
                        )
                    )
                )
                .mappings()
                .all()
            )
        if series_row is None:
            return ()
        identity = _series(series_row)
        return _select_macro(
            tuple(_macro(row, identity) for row in rows), mode, as_of, vintage_date
        )

    async def save_scheduled_event(self, value: ScheduledEvent) -> SaveResult:
        values = {
            "event_version_id": value.event_version_id,
            "event_id": value.event_id,
            "event_type": value.event_type.value,
            "subject_id": value.subject_id,
            "scheduled_start": value.scheduled_start,
            "scheduled_end": value.scheduled_end,
            "timezone": value.timezone,
            "status": value.status.value,
            "version": value.version,
            "predecessor_version_id": value.predecessor_version_id,
            "published_at": value.published_at,
            "observed_at": value.observed_at,
            "ingested_at": value.ingested_at,
            "actual_evidence_ids": list(value.actual_evidence_ids),
            **_lineage_values(value.lineage),
        }
        return await _immutable_save(
            self._engine, scheduled_events, ("event_version_id",), values, value.event_version_id
        )

    async def scheduled_events_as_of(
        self, as_of: datetime, *, operational_replay: bool = False
    ) -> tuple[ScheduledEvent, ...]:
        predicates = (
            (scheduled_events.c.ingested_at <= as_of,)
            if operational_replay
            else (
                scheduled_events.c.published_at <= as_of,
                scheduled_events.c.observed_at <= as_of,
            )
        )
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(scheduled_events)
                        .where(*predicates)
                        .order_by(scheduled_events.c.event_id, scheduled_events.c.version)
                    )
                )
                .mappings()
                .all()
            )
        latest: dict[str, ScheduledEvent] = {}
        for row in rows:
            observed, ingested = (
                row["observed_at"].astimezone(UTC),
                row["ingested_at"].astimezone(UTC),
            )
            value = ScheduledEvent(
                row["event_version_id"],
                row["event_id"],
                ScheduledEventType(row["event_type"]),
                row["subject_id"],
                row["scheduled_start"].astimezone(UTC),
                None if row["scheduled_end"] is None else row["scheduled_end"].astimezone(UTC),
                row["timezone"],
                ScheduledEventStatus(row["status"]),
                row["version"],
                row["predecessor_version_id"],
                row["published_at"].astimezone(UTC),
                observed,
                ingested,
                tuple(row["actual_evidence_ids"]),
                _lineage(row, observed, ingested),
            )
            latest[value.event_id] = value
        return tuple(
            sorted(latest.values(), key=lambda value: (value.scheduled_start, value.event_id))
        )

    async def register_plan(self, plan: AcquisitionPlan, *, first_due_at: datetime) -> SaveResult:
        values = {
            "plan_id": plan.plan_id,
            "version": plan.version,
            "capability": plan.capability,
            "scope_id": plan.scope_id,
            "preferred_provider_ids": list(plan.preferred_provider_ids),
            "cadence_kind": plan.cadence_kind.value,
            "interval_seconds": int(plan.interval.total_seconds()),
            "overlap_seconds": int(plan.overlap.total_seconds()),
            "release_window_interval_seconds": int(plan.release_window_interval.total_seconds()),
            "release_window_before_seconds": int(plan.release_window_before.total_seconds()),
            "release_window_after_seconds": int(plan.release_window_after.total_seconds()),
        }
        result = await _immutable_save(
            self._engine,
            acquisition_plans,
            ("plan_id", "version"),
            values,
            f"{plan.plan_id}:{plan.version}",
        )
        async with self._engine.begin() as connection:
            await connection.execute(
                postgresql_insert(acquisition_checkpoints)
                .values(
                    plan_id=plan.plan_id,
                    plan_version=plan.version,
                    next_due_at=first_due_at,
                    consecutive_failures=0,
                    fencing_token=0,
                    active=True,
                )
                .on_conflict_do_nothing(index_elements=["plan_id"])
            )
        return result

    async def get_checkpoint(self, plan_id: str) -> AcquisitionCheckpoint | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(acquisition_checkpoints).where(
                            acquisition_checkpoints.c.plan_id == plan_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _checkpoint(row)

    async def claim_due(
        self, plan_id: str, worker_id: str, now: datetime, lease_for: timedelta
    ) -> AcquisitionClaim | None:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(acquisition_checkpoints)
                        .where(acquisition_checkpoints.c.plan_id == plan_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or not row["active"]
                or row["next_due_at"] > now
                or (row["retry_not_before"] is not None and row["retry_not_before"] > now)
                or (row["lease_expires_at"] is not None and row["lease_expires_at"] > now)
            ):
                return None
            token, expiry = row["fencing_token"] + 1, now + lease_for
            await connection.execute(
                update(acquisition_checkpoints)
                .where(acquisition_checkpoints.c.plan_id == plan_id)
                .values(
                    lease_owner=worker_id,
                    lease_expires_at=expiry,
                    fencing_token=token,
                    last_attempt_at=now,
                )
            )
            return AcquisitionClaim(plan_id, row["plan_version"], worker_id, token, expiry)

    async def complete_claim(
        self,
        claim: AcquisitionClaim,
        *,
        completed_at: datetime,
        persisted_id: str,
        cursor: str | None,
        watermark: datetime | None,
        next_due_at: datetime,
    ) -> AcquisitionCheckpoint:
        statement = (
            update(acquisition_checkpoints)
            .where(
                acquisition_checkpoints.c.plan_id == claim.plan_id,
                acquisition_checkpoints.c.plan_version == claim.plan_version,
                acquisition_checkpoints.c.fencing_token == claim.fencing_token,
                acquisition_checkpoints.c.lease_owner == claim.worker_id,
                acquisition_checkpoints.c.lease_expires_at >= completed_at,
            )
            .values(
                cursor=cursor,
                watermark=watermark,
                last_success_at=completed_at,
                last_persisted_id=persisted_id,
                next_due_at=next_due_at,
                consecutive_failures=0,
                retry_not_before=None,
                rate_limit_reset_at=None,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        async with self._engine.begin() as connection:
            if (await connection.execute(statement)).rowcount != 1:
                raise PersistenceError(
                    PersistenceErrorCode.IDENTITY_CONFLICT, "stale acquisition fencing token"
                )
        result = await self.get_checkpoint(claim.plan_id)
        if result is None:
            raise PersistenceError(PersistenceErrorCode.TRANSACTION_ERROR, "checkpoint disappeared")
        return result

    async def fail_claim(
        self,
        claim: AcquisitionClaim,
        *,
        failed_at: datetime,
        retry_not_before: datetime,
        rate_limit_reset_at: datetime | None = None,
    ) -> AcquisitionCheckpoint:
        async with self._engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(acquisition_checkpoints)
                        .where(acquisition_checkpoints.c.plan_id == claim.plan_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["fencing_token"] != claim.fencing_token
                or row["lease_owner"] != claim.worker_id
            ):
                raise PersistenceError(
                    PersistenceErrorCode.IDENTITY_CONFLICT, "stale acquisition fencing token"
                )
            await connection.execute(
                update(acquisition_checkpoints)
                .where(acquisition_checkpoints.c.plan_id == claim.plan_id)
                .values(
                    consecutive_failures=row["consecutive_failures"] + 1,
                    retry_not_before=retry_not_before,
                    rate_limit_reset_at=rate_limit_reset_at,
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
        result = await self.get_checkpoint(claim.plan_id)
        if result is None:
            raise PersistenceError(PersistenceErrorCode.TRANSACTION_ERROR, "checkpoint disappeared")
        return result

    async def save_entity(self, value: EntityIdentity) -> SaveResult:
        async with self._engine.connect() as connection:
            collision = (
                (
                    await connection.execute(
                        select(evidence_entities.c.entity_id).where(
                            evidence_entities.c.namespace == value.namespace,
                            evidence_entities.c.official_identifier == value.official_identifier,
                            evidence_entities.c.entity_id != value.entity_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
        if collision is not None:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "official entity identity collision"
            )
        values = {
            "entity_id": value.entity_id,
            "entity_type": value.entity_type.value,
            "namespace": value.namespace,
            "official_identifier": value.official_identifier,
            "canonical_name": value.canonical_name,
            "aliases": list(value.aliases),
        }
        return await _immutable_save(
            self._engine, evidence_entities, ("entity_id",), values, value.entity_id
        )

    async def save_document(self, value: SourceDocument) -> SaveResult:
        async with self._engine.connect() as connection:
            collision = (
                (
                    await connection.execute(
                        select(source_documents.c.document_version_id).where(
                            source_documents.c.document_id == value.document_id,
                            source_documents.c.version == value.version,
                            source_documents.c.document_version_id != value.document_version_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            predecessor = None
            if value.predecessor_version_id is not None:
                predecessor = (
                    (
                        await connection.execute(
                            select(source_documents).where(
                                source_documents.c.document_version_id
                                == value.predecessor_version_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        if collision is not None:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "document version identity collision"
            )
        if value.predecessor_version_id is not None and (
            predecessor is None
            or predecessor["document_id"] != value.document_id
            or predecessor["version"] + 1 != value.version
        ):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "document predecessor identity mismatch"
            )
        values = {
            "document_version_id": value.document_version_id,
            "document_id": value.document_id,
            "publisher_entity_id": value.publisher_entity_id,
            "document_type": value.document_type.value,
            "title": value.title,
            "language": value.language,
            "speaker_entity_id": value.speaker_entity_id,
            "source_declared_role": value.source_declared_role,
            "observed_at": value.observed_at,
            "ingested_at": value.ingested_at,
            "content_hash": value.content_hash,
            "raw_observation_id": value.raw_observation_id,
            "normalized_text_hash": value.normalized_text_hash,
            "version": value.version,
            "predecessor_version_id": value.predecessor_version_id,
            "verification": value.verification.value,
            **_lineage_values(value.lineage),
        }
        return await _immutable_save(
            self._engine,
            source_documents,
            ("document_version_id",),
            values,
            value.document_version_id,
        )

    async def save_event_candidate(self, value: EventCandidate) -> SaveResult:
        if value.source_document_version_ids:
            async with self._engine.connect() as connection:
                known = set(
                    (
                        await connection.execute(
                            select(source_documents.c.document_version_id).where(
                                source_documents.c.document_version_id.in_(
                                    value.source_document_version_ids
                                )
                            )
                        )
                    ).scalars()
                )
            if known != set(value.source_document_version_ids):
                raise PersistenceError(
                    PersistenceErrorCode.IDENTITY_CONFLICT,
                    "event candidate source-document evidence is missing",
                )
        values = {
            "candidate_id": value.candidate_id,
            "event_category": value.event_category,
            "detected_at": value.detected_at,
            "observed_at": value.observed_at,
            "ingested_at": value.ingested_at,
            "entity_ids": list(value.entity_ids),
            "location_codes": list(value.location_codes),
            "source_document_version_ids": list(value.source_document_version_ids),
            "confidence": value.confidence,
            "verification": value.verification.value,
            **_lineage_values(value.lineage),
        }
        return await _immutable_save(
            self._engine, event_candidates, ("candidate_id",), values, value.candidate_id
        )

    async def save_event_document_link(self, value: EventDocumentLink) -> SaveResult:
        values = {
            "link_id": value.link_id,
            "candidate_id": value.candidate_id,
            "document_version_id": value.document_version_id,
            "relation": value.relation.value,
            "linked_at": value.linked_at,
        }
        return await _immutable_save(
            self._engine, event_document_links, ("link_id",), values, value.link_id
        )

    async def documents_as_of(
        self,
        as_of: datetime,
        *,
        operational_replay: bool = False,
        publisher_entity_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        predicates = [
            source_documents.c.ingested_at <= as_of
            if operational_replay
            else and_(
                source_documents.c.published_at <= as_of,
                source_documents.c.observed_at <= as_of,
            )
        ]
        if publisher_entity_id is not None:
            predicates.append(source_documents.c.publisher_entity_id == publisher_entity_id)
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(source_documents)
                        .where(*predicates)
                        .order_by(source_documents.c.document_id, source_documents.c.version)
                    )
                )
                .mappings()
                .all()
            )
        latest: dict[str, SourceDocument] = {}
        for row in rows:
            value = _document(row)
            latest[value.document_id] = value
        return tuple(sorted(latest.values(), key=lambda value: value.document_id))

    async def event_candidates_as_of(
        self, as_of: datetime, *, operational_replay: bool = False
    ) -> tuple[EventCandidate, ...]:
        predicates = (
            (event_candidates.c.ingested_at <= as_of,)
            if operational_replay
            else (
                event_candidates.c.detected_at <= as_of,
                event_candidates.c.observed_at <= as_of,
            )
        )
        async with self._engine.connect() as connection:
            rows = (
                (await connection.execute(select(event_candidates).where(*predicates)))
                .mappings()
                .all()
            )
        return tuple(
            sorted((_candidate(row) for row in rows), key=lambda value: value.candidate_id)
        )

    async def links_for_candidate(self, candidate_id: str) -> tuple[EventDocumentLink, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(event_document_links)
                        .where(event_document_links.c.candidate_id == candidate_id)
                        .order_by(event_document_links.c.linked_at, event_document_links.c.link_id)
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            EventDocumentLink(
                row["link_id"],
                row["candidate_id"],
                row["document_version_id"],
                EventDocumentRelation(row["relation"]),
                row["linked_at"].astimezone(UTC),
            )
            for row in rows
        )

    async def save_quarantine(self, value: EvidenceQuarantine) -> SaveResult:
        values = {
            "quarantine_id": value.quarantine_id,
            "raw_observation_id": value.raw_observation_id,
            "upstream_source_id": value.upstream_source_id,
            "reason_code": value.reason_code,
            "detail": value.detail,
            "observed_at": value.observed_at,
            "ingested_at": value.ingested_at,
        }
        return await _immutable_save(
            self._engine,
            evidence_quarantines,
            ("quarantine_id",),
            values,
            value.quarantine_id,
        )

    async def quarantines_for_raw(self, raw_observation_id: str) -> tuple[EvidenceQuarantine, ...]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(evidence_quarantines)
                        .where(evidence_quarantines.c.raw_observation_id == raw_observation_id)
                        .order_by(evidence_quarantines.c.observed_at)
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            EvidenceQuarantine(
                row["quarantine_id"],
                row["raw_observation_id"],
                row["upstream_source_id"],
                row["reason_code"],
                row["detail"],
                row["observed_at"].astimezone(UTC),
                row["ingested_at"].astimezone(UTC),
            )
            for row in rows
        )


class InMemoryEvidenceRepository(
    MacroObservationRepository,
    ScheduledEventRepository,
    AcquisitionPlanRepository,
    PolicyEventEvidenceRepository,
):
    def __init__(self) -> None:
        self.series: dict[str, MacroSeriesIdentity] = {}
        self.macro: dict[str, tuple[str, MacroObservation]] = {}
        self.events: dict[str, ScheduledEvent] = {}
        self.plans: dict[tuple[str, int], AcquisitionPlan] = {}
        self.checkpoints: dict[str, AcquisitionCheckpoint] = {}
        self.entities: dict[str, EntityIdentity] = {}
        self.documents: dict[str, SourceDocument] = {}
        self.event_candidates: dict[str, EventCandidate] = {}
        self.event_document_links: dict[str, EventDocumentLink] = {}
        self.quarantines: dict[str, EvidenceQuarantine] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _save(store: dict[Any, Any], key: Any, value: Any) -> SaveResult:
        existing = store.get(key)
        if existing is None:
            store[key] = value
            return SaveResult(SaveStatus.INSERTED, str(key))
        if existing != value:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "immutable evidence identity conflict"
            )
        return SaveResult(SaveStatus.ALREADY_EXISTS, str(key))

    async def save_series(self, value: MacroSeriesIdentity) -> SaveResult:
        return self._save(self.series, value.series_id, value)

    async def save_macro(self, raw_observation_id: str, value: MacroObservation) -> SaveResult:
        return self._save(self.macro, value.observation_id, (raw_observation_id, value))

    async def query_macro(
        self,
        series_id: str,
        mode: MacroQueryMode,
        *,
        as_of: datetime | None = None,
        vintage_date: date | None = None,
    ) -> tuple[MacroObservation, ...]:
        return _select_macro(
            tuple(value for _, value in self.macro.values() if value.series.series_id == series_id),
            mode,
            as_of,
            vintage_date,
        )

    async def save_scheduled_event(self, value: ScheduledEvent) -> SaveResult:
        return self._save(self.events, value.event_version_id, value)

    async def scheduled_events_as_of(
        self, as_of: datetime, *, operational_replay: bool = False
    ) -> tuple[ScheduledEvent, ...]:
        latest: dict[str, ScheduledEvent] = {}
        for value in sorted(
            self.events.values(), key=lambda value: (value.event_id, value.version)
        ):
            available_at = (
                value.ingested_at
                if operational_replay
                else max(value.published_at, value.observed_at)
            )
            if available_at <= as_of:
                latest[value.event_id] = value
        return tuple(
            sorted(latest.values(), key=lambda value: (value.scheduled_start, value.event_id))
        )

    async def register_plan(self, plan: AcquisitionPlan, *, first_due_at: datetime) -> SaveResult:
        result = self._save(self.plans, (plan.plan_id, plan.version), plan)
        self.checkpoints.setdefault(
            plan.plan_id, AcquisitionCheckpoint(plan.plan_id, plan.version, first_due_at)
        )
        return result

    async def get_checkpoint(self, plan_id: str) -> AcquisitionCheckpoint | None:
        return self.checkpoints.get(plan_id)

    async def claim_due(
        self, plan_id: str, worker_id: str, now: datetime, lease_for: timedelta
    ) -> AcquisitionClaim | None:
        async with self._lock:
            value = self.checkpoints.get(plan_id)
            if (
                value is None
                or value.next_due_at > now
                or (value.retry_not_before and value.retry_not_before > now)
                or (value.lease_expires_at and value.lease_expires_at > now)
            ):
                return None
            token, expiry = value.fencing_token + 1, now + lease_for
            self.checkpoints[plan_id] = AcquisitionCheckpoint(
                value.plan_id,
                value.plan_version,
                value.next_due_at,
                value.cursor,
                value.watermark,
                now,
                value.last_success_at,
                value.last_persisted_id,
                value.consecutive_failures,
                value.retry_not_before,
                value.rate_limit_reset_at,
                worker_id,
                expiry,
                token,
            )
            return AcquisitionClaim(plan_id, value.plan_version, worker_id, token, expiry)

    def _claimed(self, claim: AcquisitionClaim) -> AcquisitionCheckpoint:
        value = self.checkpoints[claim.plan_id]
        if value.fencing_token != claim.fencing_token or value.lease_owner != claim.worker_id:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "stale acquisition fencing token"
            )
        return value

    async def complete_claim(
        self,
        claim: AcquisitionClaim,
        *,
        completed_at: datetime,
        persisted_id: str,
        cursor: str | None,
        watermark: datetime | None,
        next_due_at: datetime,
    ) -> AcquisitionCheckpoint:
        value = self._claimed(claim)
        if value.lease_expires_at is None or value.lease_expires_at < completed_at:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "expired acquisition lease"
            )
        result = AcquisitionCheckpoint(
            value.plan_id,
            value.plan_version,
            next_due_at,
            cursor,
            watermark,
            value.last_attempt_at,
            completed_at,
            persisted_id,
            0,
            None,
            None,
            None,
            None,
            value.fencing_token,
        )
        self.checkpoints[claim.plan_id] = result
        return result

    async def fail_claim(
        self,
        claim: AcquisitionClaim,
        *,
        failed_at: datetime,
        retry_not_before: datetime,
        rate_limit_reset_at: datetime | None = None,
    ) -> AcquisitionCheckpoint:
        value = self._claimed(claim)
        result = AcquisitionCheckpoint(
            value.plan_id,
            value.plan_version,
            value.next_due_at,
            value.cursor,
            value.watermark,
            value.last_attempt_at,
            value.last_success_at,
            value.last_persisted_id,
            value.consecutive_failures + 1,
            retry_not_before,
            rate_limit_reset_at,
            None,
            None,
            value.fencing_token,
        )
        self.checkpoints[claim.plan_id] = result
        return result

    async def save_entity(self, value: EntityIdentity) -> SaveResult:
        if any(
            existing.authority_key == value.authority_key and existing.entity_id != value.entity_id
            for existing in self.entities.values()
        ):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "official entity identity collision"
            )
        return self._save(self.entities, value.entity_id, value)

    async def save_document(self, value: SourceDocument) -> SaveResult:
        if value.publisher_entity_id not in self.entities:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "document publisher is not registered"
            )
        if value.speaker_entity_id is not None and value.speaker_entity_id not in self.entities:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "document speaker is not registered"
            )
        if any(
            existing.document_id == value.document_id
            and existing.version == value.version
            and existing.document_version_id != value.document_version_id
            for existing in self.documents.values()
        ):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "document version identity collision"
            )
        if value.predecessor_version_id is not None:
            predecessor = self.documents.get(value.predecessor_version_id)
            if (
                predecessor is None
                or predecessor.document_id != value.document_id
                or predecessor.version + 1 != value.version
            ):
                raise PersistenceError(
                    PersistenceErrorCode.IDENTITY_CONFLICT,
                    "document predecessor identity mismatch",
                )
        return self._save(self.documents, value.document_version_id, value)

    async def save_event_candidate(self, value: EventCandidate) -> SaveResult:
        if any(
            document_id not in self.documents for document_id in value.source_document_version_ids
        ):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                "event candidate source-document evidence is missing",
            )
        return self._save(self.event_candidates, value.candidate_id, value)

    async def save_event_document_link(self, value: EventDocumentLink) -> SaveResult:
        if (
            value.candidate_id not in self.event_candidates
            or value.document_version_id not in self.documents
        ):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "event-document link target is missing"
            )
        return self._save(self.event_document_links, value.link_id, value)

    async def documents_as_of(
        self,
        as_of: datetime,
        *,
        operational_replay: bool = False,
        publisher_entity_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        latest: dict[str, SourceDocument] = {}
        for value in sorted(
            self.documents.values(), key=lambda item: (item.document_id, item.version)
        ):
            available_at = (
                value.ingested_at
                if operational_replay
                else max(value.published_at, value.observed_at)
            )
            if available_at <= as_of and (
                publisher_entity_id is None or value.publisher_entity_id == publisher_entity_id
            ):
                latest[value.document_id] = value
        return tuple(sorted(latest.values(), key=lambda value: value.document_id))

    async def event_candidates_as_of(
        self, as_of: datetime, *, operational_replay: bool = False
    ) -> tuple[EventCandidate, ...]:
        return tuple(
            sorted(
                (
                    value
                    for value in self.event_candidates.values()
                    if (
                        value.ingested_at
                        if operational_replay
                        else max(value.detected_at, value.observed_at)
                    )
                    <= as_of
                ),
                key=lambda value: value.candidate_id,
            )
        )

    async def links_for_candidate(self, candidate_id: str) -> tuple[EventDocumentLink, ...]:
        return tuple(
            sorted(
                (
                    value
                    for value in self.event_document_links.values()
                    if value.candidate_id == candidate_id
                ),
                key=lambda value: (value.linked_at, value.link_id),
            )
        )

    async def save_quarantine(self, value: EvidenceQuarantine) -> SaveResult:
        return self._save(self.quarantines, value.quarantine_id, value)

    async def quarantines_for_raw(self, raw_observation_id: str) -> tuple[EvidenceQuarantine, ...]:
        return tuple(
            sorted(
                (
                    value
                    for value in self.quarantines.values()
                    if value.raw_observation_id == raw_observation_id
                ),
                key=lambda value: (value.observed_at, value.quarantine_id),
            )
        )
