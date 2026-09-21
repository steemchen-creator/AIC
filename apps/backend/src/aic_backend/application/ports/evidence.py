"""Application-owned persistence contracts for SPEC-011 Checkpoint B."""

from datetime import date, datetime, timedelta
from typing import Protocol

from aic_backend.application.ports.persistence import SaveResult
from aic_backend.domain.evidence import (
    AcquisitionCheckpoint,
    AcquisitionClaim,
    AcquisitionPlan,
    EntityIdentity,
    EventCandidate,
    EventDocumentLink,
    EvidenceQuarantine,
    MacroObservation,
    MacroQueryMode,
    MacroSeriesIdentity,
    ScheduledEvent,
    SourceDocument,
)


class MacroObservationRepository(Protocol):
    async def save_series(self, value: MacroSeriesIdentity) -> SaveResult: ...
    async def save_macro(self, raw_observation_id: str, value: MacroObservation) -> SaveResult: ...
    async def query_macro(
        self,
        series_id: str,
        mode: MacroQueryMode,
        *,
        as_of: datetime | None = None,
        vintage_date: date | None = None,
    ) -> tuple[MacroObservation, ...]: ...


class ScheduledEventRepository(Protocol):
    async def save_scheduled_event(self, value: ScheduledEvent) -> SaveResult: ...
    async def scheduled_events_as_of(
        self, as_of: datetime, *, operational_replay: bool = False
    ) -> tuple[ScheduledEvent, ...]: ...


class AcquisitionPlanRepository(Protocol):
    async def register_plan(
        self, plan: AcquisitionPlan, *, first_due_at: datetime
    ) -> SaveResult: ...
    async def get_checkpoint(self, plan_id: str) -> AcquisitionCheckpoint | None: ...
    async def claim_due(
        self, plan_id: str, worker_id: str, now: datetime, lease_for: timedelta
    ) -> AcquisitionClaim | None: ...
    async def complete_claim(
        self,
        claim: AcquisitionClaim,
        *,
        completed_at: datetime,
        persisted_id: str,
        cursor: str | None,
        watermark: datetime | None,
        next_due_at: datetime,
    ) -> AcquisitionCheckpoint: ...
    async def fail_claim(
        self,
        claim: AcquisitionClaim,
        *,
        failed_at: datetime,
        retry_not_before: datetime,
        rate_limit_reset_at: datetime | None = None,
    ) -> AcquisitionCheckpoint: ...


class PolicyEventEvidenceRepository(Protocol):
    async def save_entity(self, value: EntityIdentity) -> SaveResult: ...
    async def save_document(self, value: SourceDocument) -> SaveResult: ...
    async def save_event_candidate(self, value: EventCandidate) -> SaveResult: ...
    async def save_event_document_link(self, value: EventDocumentLink) -> SaveResult: ...
    async def save_quarantine(self, value: EvidenceQuarantine) -> SaveResult: ...
    async def quarantines_for_raw(
        self, raw_observation_id: str
    ) -> tuple[EvidenceQuarantine, ...]: ...
    async def documents_as_of(
        self,
        as_of: datetime,
        *,
        operational_replay: bool = False,
        publisher_entity_id: str | None = None,
    ) -> tuple[SourceDocument, ...]: ...
    async def event_candidates_as_of(
        self, as_of: datetime, *, operational_replay: bool = False
    ) -> tuple[EventCandidate, ...]: ...
    async def links_for_candidate(self, candidate_id: str) -> tuple[EventDocumentLink, ...]: ...
