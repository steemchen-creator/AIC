from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityMode,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.data_foundation.policy_events import PolicyEventNormalizer
from aic_backend.domain.evidence import EvidenceVerification
from aic_backend.domain.market_data import AuthorityLevel
from aic_backend.infrastructure.evidence_persistence import InMemoryEvidenceRepository

OBSERVED = datetime(2026, 9, 22, 12, tzinfo=UTC)


def official_payload() -> dict[str, object]:
    return {
        "upstream_source_id": "FEDERAL_RESERVE",
        "license_id": "FEDERAL-RESERVE-PUBLIC-RSS",
        "raw_observation_id": "raw-fed",
        "entities": (
            {
                "entity_id": "institution:FEDERAL_RESERVE_BOARD",
                "entity_type": "INSTITUTION",
                "namespace": "OFFICIAL_US_AGENCY",
                "official_identifier": "FEDERAL_RESERVE_BOARD",
                "canonical_name": "Federal Reserve Board",
                "aliases": ("Board of Governors",),
            },
        ),
        "documents": (
            {
                "document_id": "fed-statement-1",
                "source_record_id": "fed-statement-1",
                "publisher_entity_id": "institution:FEDERAL_RESERVE_BOARD",
                "document_type": "POLICY_DECISION",
                "title": "Federal Reserve issues FOMC statement",
                "language": "en",
                "event_time": "2026-09-16T18:00:00+00:00",
                "published_at": "2026-09-16T18:00:00+00:00",
                "source_uri": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
                "content_hash": "a" * 64,
                "version": 1,
            },
        ),
    }


def radar_payload() -> dict[str, object]:
    return {
        "upstream_source_id": "GDELT",
        "candidates": (
            {
                "source_uri": "https://example.test/report",
                "source_record_id": "report-1",
                "event_category": "NEWS_MENTION",
                "event_time": "2026-09-16T18:00:00+00:00",
                "detected_at": "2026-09-16T18:01:00+00:00",
                "entity_ids": (),
                "location_codes": ("US",),
                "confidence": "0.5",
            },
        ),
    }


@pytest.mark.asyncio
async def test_official_document_versions_are_immutable_pit_evidence() -> None:
    normalizer = PolicyEventNormalizer()
    entities, documents = normalizer.normalize_official_documents(
        official_payload(),
        adapter_id="fed_official",
        expected_upstream_source_id="FEDERAL_RESERVE",
        observed_at=OBSERVED,
        ingested_at=OBSERVED + timedelta(seconds=1),
        raw_hash="b" * 64,
    )
    repository = InMemoryEvidenceRepository()
    await repository.save_entity(entities[0])
    await repository.save_document(documents[0])

    assert not await repository.documents_as_of(datetime(2026, 9, 17, tzinfo=UTC))
    assert await repository.documents_as_of(OBSERVED) == documents
    assert not await repository.documents_as_of(OBSERVED, operational_replay=True)
    assert (
        await repository.documents_as_of(OBSERVED + timedelta(seconds=1), operational_replay=True)
        == documents
    )
    assert documents[0].verification is EvidenceVerification.VERIFIED_OFFICIAL
    before_observation = PointInTimeContext(
        OBSERVED - timedelta(seconds=1), AvailabilityMode.HISTORICAL_RESEARCH
    )
    assert (
        DataAvailabilityPolicy().source_document(documents[0], before_observation).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )

    revision_payload = official_payload()
    revision_payload["raw_observation_id"] = "raw-fed-revision"
    revision_payload["documents"] = (
        {
            **revision_payload["documents"][0],  # type: ignore[index]
            "content_hash": "9" * 64,
            "version": 2,
            "predecessor_version_id": documents[0].document_version_id,
        },
    )
    _, revisions = normalizer.normalize_official_documents(
        revision_payload,
        adapter_id="fed_official",
        expected_upstream_source_id="FEDERAL_RESERVE",
        observed_at=OBSERVED + timedelta(minutes=1),
        ingested_at=OBSERVED + timedelta(minutes=1),
        raw_hash="9" * 64,
    )
    await repository.save_document(revisions[0])
    assert revisions[0].predecessor_version_id == documents[0].document_version_id
    assert await repository.documents_as_of(OBSERVED + timedelta(minutes=1)) == revisions
    with pytest.raises(PersistenceError, match="predecessor"):
        await repository.save_document(
            replace(
                revisions[0],
                document_version_id="docv_invalid",
                version=3,
                predecessor_version_id="docv_missing",
            )
        )

    changed = replace(documents[0], title="silently rewritten")
    with pytest.raises(PersistenceError, match="immutable evidence"):
        await repository.save_document(changed)


@pytest.mark.asyncio
async def test_entity_collision_and_unverifiable_publisher_fail_closed() -> None:
    normalizer = PolicyEventNormalizer()
    entities, _ = normalizer.normalize_official_documents(
        official_payload(),
        adapter_id="fed_official",
        expected_upstream_source_id="FEDERAL_RESERVE",
        observed_at=OBSERVED,
        ingested_at=OBSERVED,
        raw_hash="c" * 64,
    )
    repository = InMemoryEvidenceRepository()
    await repository.save_entity(entities[0])
    collision = replace(entities[0], entity_id="institution:COLLISION")
    with pytest.raises(PersistenceError, match="collision"):
        await repository.save_entity(collision)

    invalid = official_payload()
    invalid["documents"] = (
        {**invalid["documents"][0], "publisher_entity_id": "institution:UNVERIFIED"},  # type: ignore[index]
    )
    with pytest.raises(ValueError, match="publisher"):
        normalizer.normalize_official_documents(
            invalid,
            adapter_id="fed_official",
            expected_upstream_source_id="FEDERAL_RESERVE",
            observed_at=OBSERVED,
            ingested_at=OBSERVED,
            raw_hash="d" * 64,
        )


@pytest.mark.asyncio
async def test_radar_candidate_cannot_become_official_and_links_append_only() -> None:
    normalizer = PolicyEventNormalizer()
    (candidate,) = normalizer.normalize_radar_candidates(
        radar_payload(),
        adapter_id="gdelt_radar",
        observed_at=OBSERVED,
        ingested_at=OBSERVED,
        raw_hash="e" * 64,
    )
    assert candidate.authority_level is AuthorityLevel.RADAR
    assert candidate.confidence == Decimal("0.5")
    assert candidate.verification is EvidenceVerification.RADAR_ONLY
    assert candidate.source_document_version_ids == ()
    before_detection = PointInTimeContext(
        datetime(2026, 9, 16, 18, tzinfo=UTC), AvailabilityMode.HISTORICAL_RESEARCH
    )
    assert (
        DataAvailabilityPolicy().event_candidate(candidate, before_detection).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )
    with pytest.raises(ValueError, match="radar-only"):
        replace(candidate, verification=EvidenceVerification.VERIFIED_OFFICIAL)

    entities, documents = normalizer.normalize_official_documents(
        official_payload(),
        adapter_id="fed_official",
        expected_upstream_source_id="FEDERAL_RESERVE",
        observed_at=OBSERVED,
        ingested_at=OBSERVED,
        raw_hash="f" * 64,
    )
    link = normalizer.verification_link(candidate, documents[0], linked_at=OBSERVED)
    repository = InMemoryEvidenceRepository()
    await repository.save_entity(entities[0])
    await repository.save_document(documents[0])
    await repository.save_event_candidate(candidate)
    await repository.save_event_document_link(link)
    assert await repository.links_for_candidate(candidate.candidate_id) == (link,)
    with pytest.raises(PersistenceError, match="immutable evidence"):
        await repository.save_event_document_link(
            replace(link, linked_at=OBSERVED + timedelta(seconds=1))
        )


def test_multilingual_title_unknown_speaker_and_upstream_mismatch() -> None:
    payload = official_payload()
    payload["documents"] = (
        {
            **payload["documents"][0],  # type: ignore[index]
            "title": "货币政策委员会公告",
            "language": "zh-CN",
        },
    )
    _, documents = PolicyEventNormalizer().normalize_official_documents(
        payload,
        adapter_id="official_policy",
        expected_upstream_source_id="FEDERAL_RESERVE",
        observed_at=OBSERVED,
        ingested_at=OBSERVED,
        raw_hash="1" * 64,
    )
    assert documents[0].title == "货币政策委员会公告"
    assert documents[0].speaker_entity_id is None
    with pytest.raises(ValueError, match="upstream identity"):
        PolicyEventNormalizer().normalize_official_documents(
            payload,
            adapter_id="official_policy",
            expected_upstream_source_id="PBOC",
            observed_at=OBSERVED,
            ingested_at=OBSERVED,
            raw_hash="1" * 64,
        )


def test_event_confidence_bounds() -> None:
    payload = radar_payload()
    payload["candidates"] = ({**payload["candidates"][0], "confidence": "1.1"},)  # type: ignore[index]
    with pytest.raises(ValueError, match="confidence"):
        PolicyEventNormalizer().normalize_radar_candidates(
            payload,
            adapter_id="gdelt_radar",
            observed_at=OBSERVED,
            ingested_at=OBSERVED,
            raw_hash="2" * 64,
        )
