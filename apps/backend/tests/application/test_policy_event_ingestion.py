from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aic_backend.application.acquisition import PolicyEventIngestionService
from aic_backend.data_foundation.policy_events import PolicyEventNormalizer
from aic_backend.infrastructure.evidence_persistence import InMemoryEvidenceRepository
from aic_backend.infrastructure.market_intelligence_persistence import (
    InMemoryMarketIntelligenceRepository,
)
from aic_backend.provider_runtime import ProviderInvocationResult, ProviderRequestContext
from aic_backend.providers.policy_events import EVENT_RADAR_READ, OFFICIAL_FEED_READ

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW + timedelta(seconds=1)


class Runtime:
    def __init__(self, payload: Mapping[str, Any], provider_id: str) -> None:
        self.payload, self.provider_id = payload, provider_id

    async def execute(
        self, context: ProviderRequestContext, payload: Mapping[str, Any]
    ) -> ProviderInvocationResult:
        del payload
        return ProviderInvocationResult(
            context.request_id,
            self.provider_id,
            True,
            self.payload,
            None,
            1,
            NOW,
            NOW,
        )


def official_payload() -> dict[str, object]:
    return {
        "upstream_source_id": "FEDERAL_RESERVE",
        "entities": (
            {
                "entity_id": "institution:FEDERAL_RESERVE_BOARD",
                "entity_type": "INSTITUTION",
                "namespace": "OFFICIAL_US_AGENCY",
                "official_identifier": "FEDERAL_RESERVE_BOARD",
                "canonical_name": "Federal Reserve Board",
                "aliases": (),
            },
        ),
        "documents": (
            {
                "document_id": "statement-1",
                "source_record_id": "statement-1",
                "publisher_entity_id": "institution:FEDERAL_RESERVE_BOARD",
                "document_type": "POLICY_DECISION",
                "title": "FOMC statement",
                "language": "en",
                "event_time": "2026-09-21T18:00:00+00:00",
                "published_at": "2026-09-21T18:00:00+00:00",
                "source_uri": "https://www.federalreserve.gov/newsevents/a.htm",
                "content_hash": "a" * 64,
                "version": 1,
            },
        ),
    }


@pytest.mark.asyncio
async def test_official_ingestion_persists_raw_before_canonical_and_is_idempotent() -> None:
    raw = InMemoryMarketIntelligenceRepository()
    evidence = InMemoryEvidenceRepository()
    service = PolicyEventIngestionService(
        Runtime(official_payload(), "fed_official"),
        raw,
        evidence,
        PolicyEventNormalizer(),
        Clock(),
    )
    first = await service.ingest(OFFICIAL_FEED_READ, {}, request_id="fed-1")
    second = await service.ingest(OFFICIAL_FEED_READ, {}, request_id="fed-2")
    assert first == second
    assert len(raw.raw) == 1
    assert len(evidence.documents) == 1
    assert first.documents[0].raw_observation_id == first.raw_observation_id

    empty_payload = official_payload()
    empty_payload["documents"] = ()
    await PolicyEventIngestionService(
        Runtime(empty_payload, "fed_official"),
        raw,
        evidence,
        PolicyEventNormalizer(),
        Clock(),
    ).ingest(OFFICIAL_FEED_READ, {}, request_id="fed-empty")
    assert len(evidence.documents) == 1


@pytest.mark.asyncio
async def test_radar_ingestion_retains_discovery_authority() -> None:
    payload = {
        "upstream_source_id": "GDELT",
        "candidates": (
            {
                "source_uri": "https://news.example.test/event",
                "source_record_id": "event-1",
                "event_category": "NEWS_MENTION",
                "event_time": "2026-09-22T11:00:00+00:00",
                "detected_at": "2026-09-22T11:01:00+00:00",
                "entity_ids": (),
                "location_codes": ("US",),
                "confidence": "0.5",
            },
        ),
    }
    evidence = InMemoryEvidenceRepository()
    result = await PolicyEventIngestionService(
        Runtime(payload, "gdelt_radar"),
        InMemoryMarketIntelligenceRepository(),
        evidence,
        PolicyEventNormalizer(),
        Clock(),
    ).ingest(EVENT_RADAR_READ, {"query": "policy"}, request_id="radar-1")
    assert result.documents == ()
    assert len(result.candidates) == 1
    assert len(evidence.event_candidates) == 1


@pytest.mark.asyncio
async def test_unsupported_upstream_never_reaches_canonical_persistence() -> None:
    evidence = InMemoryEvidenceRepository()
    service = PolicyEventIngestionService(
        Runtime({"upstream_source_id": "USER_SUPPLIED"}, "unknown_provider"),
        InMemoryMarketIntelligenceRepository(),
        evidence,
        PolicyEventNormalizer(),
        Clock(),
    )
    with pytest.raises(ValueError, match="unsupported"):
        await service.ingest(OFFICIAL_FEED_READ, {}, request_id="bad-1")
    assert not evidence.documents


@pytest.mark.asyncio
async def test_unverifiable_official_publisher_retains_raw_quarantine_reason() -> None:
    payload = official_payload()
    payload["documents"] = (
        {
            **payload["documents"][0],  # type: ignore[index]
            "publisher_entity_id": "institution:UNVERIFIED",
        },
    )
    raw = InMemoryMarketIntelligenceRepository()
    evidence = InMemoryEvidenceRepository()
    service = PolicyEventIngestionService(
        Runtime(payload, "fed_official"),
        raw,
        evidence,
        PolicyEventNormalizer(),
        Clock(),
    )
    with pytest.raises(ValueError, match="publisher"):
        await service.ingest(OFFICIAL_FEED_READ, {}, request_id="quarantine-1")
    assert len(raw.raw) == 1
    quarantine = next(iter(evidence.quarantines.values()))
    assert quarantine.reason_code == "CANONICAL_VALIDATION_FAILED"
    assert "publisher" in quarantine.detail
