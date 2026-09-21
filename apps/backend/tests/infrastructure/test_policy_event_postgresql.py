import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.data_foundation.policy_events import PolicyEventNormalizer
from aic_backend.domain.evidence import EvidenceQuarantine
from aic_backend.infrastructure.evidence_persistence import (
    PostgreSQLEvidenceRepository,
    event_candidates,
    event_document_links,
    evidence_entities,
    evidence_quarantines,
    source_documents,
)

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)


def migration_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    return environment


@pytest.fixture
async def engine() -> AsyncEngine:
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=migration_environment())
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        for table in (
            evidence_quarantines,
            event_document_links,
            event_candidates,
            source_documents,
            evidence_entities,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


def official_payload() -> dict[str, object]:
    return {
        "upstream_source_id": "SEC_EDGAR",
        "license_id": "SEC-FAIR-ACCESS",
        "raw_observation_id": "raw-sec",
        "entities": (
            {
                "entity_id": "issuer:SEC_CIK_0000320193",
                "entity_type": "ISSUER",
                "namespace": "SEC_CIK",
                "official_identifier": "0000320193",
                "canonical_name": "Apple Inc.",
                "aliases": (),
            },
        ),
        "documents": (
            {
                "document_id": "0000320193-26-000001",
                "source_record_id": "0000320193-26-000001:form8-k.htm",
                "publisher_entity_id": "issuer:SEC_CIK_0000320193",
                "document_type": "REGULATORY_FILING",
                "title": "8-K — Apple Inc.",
                "language": "en",
                "event_time": "2026-09-21T20:30:00+00:00",
                "published_at": "2026-09-21T20:30:00+00:00",
                "source_uri": "https://www.sec.gov/Archives/edgar/data/320193/a/form8-k.htm",
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
                "source_uri": "https://news.example.test/apple",
                "source_record_id": "apple-event",
                "event_category": "NEWS_MENTION",
                "event_time": "2026-09-21T20:00:00+00:00",
                "detected_at": "2026-09-21T20:01:00+00:00",
                "entity_ids": ("issuer:SEC_CIK_0000320193",),
                "location_codes": ("US",),
                "confidence": "0.5",
            },
        ),
    }


@pytest.mark.asyncio
async def test_policy_event_postgresql_restart_pit_and_link_round_trip(
    engine: AsyncEngine,
) -> None:
    normalizer = PolicyEventNormalizer()
    entities, documents = normalizer.normalize_official_documents(
        official_payload(),
        adapter_id="sec_edgar",
        expected_upstream_source_id="SEC_EDGAR",
        observed_at=NOW,
        ingested_at=NOW + timedelta(seconds=1),
        raw_hash="b" * 64,
    )
    (candidate,) = normalizer.normalize_radar_candidates(
        radar_payload(),
        adapter_id="gdelt_radar",
        observed_at=NOW,
        ingested_at=NOW,
        raw_hash="c" * 64,
    )
    repository = PostgreSQLEvidenceRepository(engine)
    await repository.save_entity(entities[0])
    await repository.save_document(documents[0])
    await repository.save_event_candidate(candidate)
    link = normalizer.verification_link(candidate, documents[0], linked_at=NOW)
    await repository.save_event_document_link(link)
    quarantine = EvidenceQuarantine(
        "quarantine-1",
        "raw-invalid",
        "SEC_EDGAR",
        "CANONICAL_VALIDATION_FAILED",
        "publisher identity mismatch",
        NOW,
        NOW,
    )
    await repository.save_quarantine(quarantine)

    restarted = PostgreSQLEvidenceRepository(engine)
    assert await restarted.documents_as_of(NOW) == documents
    assert not await restarted.documents_as_of(NOW, operational_replay=True)
    assert (
        await restarted.documents_as_of(NOW + timedelta(seconds=1), operational_replay=True)
        == documents
    )
    assert await restarted.event_candidates_as_of(NOW) == (candidate,)
    assert await restarted.links_for_candidate(candidate.candidate_id) == (link,)
    assert await restarted.quarantines_for_raw("raw-invalid") == (quarantine,)


def test_spec011_checkpoint_c_migration_round_trip() -> None:
    environment = migration_environment()
    for operation, revision in (
        ("upgrade", "head"),
        ("downgrade", "20260921_0017"),
        ("upgrade", "head"),
        ("downgrade", "20260921_0017"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", operation, revision],
            check=True,
            env=environment,
        )
