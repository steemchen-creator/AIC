import asyncio
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.data_foundation.macro import MacroNormalizer
from aic_backend.domain.evidence import (
    AcquisitionCadenceKind,
    AcquisitionPlan,
    MacroQueryMode,
    ScheduledEvent,
    ScheduledEventStatus,
    ScheduledEventType,
)
from aic_backend.domain.market_data import AuthorityLevel, SourceLineage, SourceType
from aic_backend.infrastructure.evidence_persistence import (
    PostgreSQLEvidenceRepository,
    acquisition_checkpoints,
    acquisition_plans,
    macro_observations,
    macro_series,
    scheduled_events,
)

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


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
            acquisition_checkpoints,
            acquisition_plans,
            scheduled_events,
            macro_observations,
            macro_series,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


def macro_payload() -> dict[str, object]:
    return {
        "series": {
            "series_id": "CPIAUCSL",
            "title": "Consumer Price Index",
            "geography": "US",
            "source_agency_id": "BLS",
            "unit": "Index",
            "frequency": "M",
            "seasonal_adjustment": "SA",
        },
        "observations": [
            {
                "date": "2026-01-01",
                "value": "100",
                "realtime_start": "2026-02-10",
                "realtime_end": "2026-03-09",
                "release_at": "2026-02-10",
            },
            {
                "date": "2026-01-01",
                "value": "100.2",
                "realtime_start": "2026-03-10",
                "realtime_end": "9999-12-31",
                "release_at": "2026-03-10",
            },
        ],
    }


def scheduled_event() -> ScheduledEvent:
    published = datetime(2026, 1, 1, tzinfo=UTC)
    lineage = SourceLineage(
        "federal_reserve_calendar",
        "FEDERAL_RESERVE",
        AuthorityLevel.PRIMARY,
        SourceType.OFFICIAL_API,
        published,
        published,
        published,
        "c" * 64,
        "scheduled-event/v1",
        published_at=published,
        source_uri="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    )
    return ScheduledEvent(
        "event-v1",
        "event",
        ScheduledEventType.CENTRAL_BANK_MEETING,
        "FOMC",
        datetime(2026, 9, 16, 18, tzinfo=UTC),
        None,
        "America/New_York",
        ScheduledEventStatus.SCHEDULED,
        1,
        None,
        published,
        published,
        published,
        (),
        lineage,
    )


@pytest.mark.asyncio
async def test_postgresql_macro_calendar_round_trip_and_restart(engine: AsyncEngine) -> None:
    repository = PostgreSQLEvidenceRepository(engine)
    series, observations = MacroNormalizer().normalize_fred(
        macro_payload(),
        adapter_id="fred_official",
        observed_at=NOW,
        ingested_at=NOW,
        raw_hash="d" * 64,
    )
    await repository.save_series(series)
    for value in observations:
        await repository.save_macro("raw-cpi", value)
    await repository.save_scheduled_event(scheduled_event())

    restarted = PostgreSQLEvidenceRepository(engine)
    historical = await restarted.query_macro(
        "CPIAUCSL", MacroQueryMode.AS_PUBLISHED, vintage_date=date(2026, 2, 20)
    )
    latest = await restarted.query_macro("CPIAUCSL", MacroQueryMode.LATEST_REVISED)
    events = await restarted.scheduled_events_as_of(datetime(2026, 1, 2, tzinfo=UTC))
    assert historical[0].value == Decimal("100")
    assert latest[0].value == Decimal("100.2")
    assert events == (scheduled_event(),)


@pytest.mark.asyncio
async def test_postgresql_multi_worker_fence_and_checkpoint_restart(engine: AsyncEngine) -> None:
    repository = PostgreSQLEvidenceRepository(engine)
    plan = AcquisitionPlan(
        "cpi-release",
        1,
        "macro.vintage.read",
        "CPIAUCSL",
        ("fred_official",),
        AcquisitionCadenceKind.RELEASE_WINDOW,
        timedelta(hours=1),
        timedelta(days=2),
    )
    await repository.register_plan(plan, first_due_at=NOW)
    claims = await asyncio.gather(
        repository.claim_due(plan.plan_id, "worker-a", NOW, timedelta(minutes=2)),
        repository.claim_due(plan.plan_id, "worker-b", NOW, timedelta(minutes=2)),
    )
    owned = [claim for claim in claims if claim is not None]
    assert len(owned) == 1
    claim = owned[0]
    completed = await repository.complete_claim(
        claim,
        completed_at=NOW + timedelta(seconds=1),
        persisted_id="macro-1",
        cursor="1000",
        watermark=NOW,
        next_due_at=NOW + timedelta(hours=1),
    )
    assert completed.cursor == "1000"
    restarted = PostgreSQLEvidenceRepository(engine)
    assert await restarted.get_checkpoint(plan.plan_id) == completed


def test_spec011_checkpoint_b_migration_round_trip() -> None:
    environment = migration_environment()
    for operation, revision in (
        ("upgrade", "head"),
        ("downgrade", "20260921_0016"),
        ("upgrade", "head"),
        ("downgrade", "20260921_0016"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", operation, revision],
            check=True,
            env=environment,
        )
