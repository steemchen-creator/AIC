"""Policy/document/event ingestion through the existing Provider Runtime and canonical path."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from aic_backend.application.ports.evidence import PolicyEventEvidenceRepository
from aic_backend.application.ports.market_intelligence import RawObservationRepository
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.data_foundation.canonical import create_raw_observation
from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.data_foundation.policy_events import PolicyEventNormalizer
from aic_backend.domain.evidence import (
    EntityIdentity,
    EventCandidate,
    EvidenceQuarantine,
    SourceDocument,
)
from aic_backend.domain.market_data import AuthorityLevel, DataCapability, SourceLineage, SourceType
from aic_backend.provider_runtime import (
    ProviderCapability,
    ProviderRequestContext,
    ProviderRuntimePort,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class PolicyEventIngestionResult:
    raw_observation_id: str
    entities: tuple[EntityIdentity, ...] = ()
    documents: tuple[SourceDocument, ...] = ()
    candidates: tuple[EventCandidate, ...] = ()


class PolicyEventIngestionService:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        raw_repository: RawObservationRepository,
        evidence_repository: PolicyEventEvidenceRepository,
        normalizer: PolicyEventNormalizer,
        clock: Clock,
        *,
        timeout_ms: int = 5000,
    ) -> None:
        self._runtime = runtime
        self._raw = raw_repository
        self._evidence = evidence_repository
        self._normalizer = normalizer
        self._clock = clock
        self._timeout_ms = timeout_ms

    async def ingest(
        self,
        capability: ProviderCapability,
        request_payload: Mapping[str, object],
        *,
        request_id: str,
        preferred_provider_ids: tuple[str, ...] = (),
    ) -> PolicyEventIngestionResult:
        result = await self._runtime.execute(
            ProviderRequestContext(
                request_id,
                capability,
                self._timeout_ms,
                preferred_provider_ids=preferred_provider_ids,
            ),
            request_payload,
        )
        if not result.success or result.data is None:
            raise RuntimeError("policy/event provider invocation failed")
        payload = dict(result.data)
        upstream = str(payload.get("upstream_source_id", "")).strip()
        if upstream not in {"FEDERAL_RESERVE", "SEC_EDGAR", "GDELT"}:
            raise ValueError("policy/event upstream identity is unsupported")
        observed_at = result.finished_at.astimezone(UTC)
        ingested_at = max(observed_at, self._clock.now().astimezone(UTC))
        raw_hash = raw_payload_hash(result.data)
        raw_id = (
            "obs_"
            + hashlib.sha256(f"{result.provider_id}:{upstream}:{raw_hash}".encode()).hexdigest()
        )
        source_timestamp = observed_at
        radar = upstream == "GDELT"
        raw = create_raw_observation(
            observation_id=raw_id,
            provider_id=result.provider_id,
            capability=(
                DataCapability.EVENT_CANDIDATE if radar else DataCapability.SOURCE_DOCUMENT
            ),
            received_at=ingested_at,
            payload=result.data,
            source_metadata={
                "request_id": result.request_id,
                "failover_count": result.failover_count,
            },
            lineage=SourceLineage(
                result.provider_id,
                upstream,
                AuthorityLevel.RADAR if radar else AuthorityLevel.PRIMARY,
                SourceType.RADAR_FEED if radar else SourceType.OFFICIAL_FEED,
                source_timestamp,
                observed_at,
                ingested_at,
                raw_hash,
                self._normalizer.transformation_version,
                published_at=source_timestamp,
                source_uri=self._source_uri(upstream),
                license_id=(
                    "GDELT-UNRESTRICTED-WITH-ATTRIBUTION" if radar else "OFFICIAL-PUBLIC-SOURCE"
                ),
            ),
        )
        existing = await self._raw.get_raw(raw_id)
        if existing is None:
            await self._raw.save_raw(raw)
        else:
            if existing.lineage is None:
                raise RuntimeError("stored policy/event raw evidence has no lineage")
            observed_at = existing.lineage.observed_at
            ingested_at = existing.lineage.ingested_at
        payload["raw_observation_id"] = raw_id
        if radar:
            try:
                candidates = self._normalizer.normalize_radar_candidates(
                    payload,
                    adapter_id=result.provider_id,
                    observed_at=observed_at,
                    ingested_at=ingested_at,
                    raw_hash=raw_hash,
                )
            except ValueError as error:
                await self._quarantine(raw_id, upstream, observed_at, ingested_at, error)
                raise
            try:
                for candidate in candidates:
                    await self._evidence.save_event_candidate(candidate)
            except PersistenceError as error:
                await self._quarantine(raw_id, upstream, observed_at, ingested_at, error)
                raise
            return PolicyEventIngestionResult(raw_id, candidates=candidates)
        try:
            entities, documents = self._normalizer.normalize_official_documents(
                payload,
                adapter_id=result.provider_id,
                expected_upstream_source_id=upstream,
                observed_at=observed_at,
                ingested_at=ingested_at,
                raw_hash=raw_hash,
            )
        except ValueError as error:
            await self._quarantine(raw_id, upstream, observed_at, ingested_at, error)
            raise
        try:
            for entity in entities:
                await self._evidence.save_entity(entity)
            for document in documents:
                await self._evidence.save_document(document)
        except PersistenceError as error:
            await self._quarantine(raw_id, upstream, observed_at, ingested_at, error)
            raise
        return PolicyEventIngestionResult(raw_id, entities, documents)

    async def _quarantine(
        self,
        raw_observation_id: str,
        upstream_source_id: str,
        observed_at: datetime,
        ingested_at: datetime,
        error: Exception,
    ) -> None:
        reason = "CANONICAL_VALIDATION_FAILED"
        quarantine_id = (
            "quarantine_" + hashlib.sha256(f"{raw_observation_id}:{reason}".encode()).hexdigest()
        )
        await self._evidence.save_quarantine(
            EvidenceQuarantine(
                quarantine_id,
                raw_observation_id,
                upstream_source_id,
                reason,
                str(error)[:500],
                observed_at,
                ingested_at,
            )
        )

    @staticmethod
    def _source_uri(upstream: str) -> str:
        return {
            "FEDERAL_RESERVE": "https://www.federalreserve.gov/feeds/feeds.htm",
            "SEC_EDGAR": "https://data.sec.gov/",
            "GDELT": "https://api.gdeltproject.org/api/v2/doc/doc",
        }[upstream]
