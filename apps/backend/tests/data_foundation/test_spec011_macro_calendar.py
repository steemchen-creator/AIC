from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityMode,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.data_foundation.macro import MacroNormalizer
from aic_backend.domain.evidence import (
    MacroQueryMode,
    ScheduledEvent,
    ScheduledEventStatus,
    ScheduledEventType,
)
from aic_backend.domain.market_data import AuthorityLevel, SourceLineage, SourceType
from aic_backend.infrastructure.evidence_persistence import InMemoryEvidenceRepository

OBSERVED = datetime(2026, 9, 21, 12, tzinfo=UTC)


def macro_payload() -> dict[str, object]:
    return {
        "series": {
            "series_id": "PAYEMS",
            "title": "All Employees",
            "geography": "US",
            "source_agency_id": "BLS",
            "unit": "Thousands",
            "frequency": "M",
            "seasonal_adjustment": "SA",
        },
        "observations": [
            {
                "date": "2020-01-01",
                "value": "100",
                "realtime_start": "2020-02-07",
                "realtime_end": "2020-03-05",
                "release_at": "2020-02-07",
            },
            {
                "date": "2020-01-01",
                "value": "102",
                "realtime_start": "2020-03-06",
                "realtime_end": "9999-12-31",
                "release_at": "2020-03-06",
            },
        ],
    }


def event(
    version: int,
    status: ScheduledEventStatus,
    published_at: datetime,
    scheduled_start: datetime,
    *,
    evidence: tuple[str, ...] = (),
    observed_at: datetime | None = None,
) -> ScheduledEvent:
    version_id = f"fomc-2026-09-v{version}"
    observed_at = observed_at or published_at
    lineage = SourceLineage(
        "federal_reserve_calendar",
        "FEDERAL_RESERVE",
        AuthorityLevel.PRIMARY,
        SourceType.OFFICIAL_API,
        published_at,
        observed_at,
        observed_at,
        f"{version:064x}",
        "scheduled-event/v1",
        published_at=published_at,
        source_uri="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    )
    return ScheduledEvent(
        version_id,
        "fomc-2026-09",
        ScheduledEventType.CENTRAL_BANK_MEETING,
        "FOMC",
        scheduled_start,
        scheduled_start + timedelta(hours=2),
        "America/New_York",
        status,
        version,
        None if version == 1 else f"fomc-2026-09-v{version - 1}",
        published_at,
        observed_at,
        observed_at,
        evidence,
        lineage,
    )


@pytest.mark.asyncio
async def test_macro_latest_vintage_and_historical_as_of_are_distinct() -> None:
    series, observations = MacroNormalizer().normalize_fred(
        macro_payload(),
        adapter_id="fred_official",
        observed_at=OBSERVED,
        ingested_at=OBSERVED,
        raw_hash="a" * 64,
    )
    first_observed = datetime(2020, 2, 8, tzinfo=UTC)
    revised_observed = datetime(2020, 3, 7, tzinfo=UTC)
    observations = (
        replace(
            observations[0],
            observed_at=first_observed,
            ingested_at=first_observed,
            lineage=replace(
                observations[0].lineage,
                observed_at=first_observed,
                ingested_at=first_observed,
            ),
        ),
        replace(
            observations[1],
            observed_at=revised_observed,
            ingested_at=revised_observed,
            lineage=replace(
                observations[1].lineage,
                observed_at=revised_observed,
                ingested_at=revised_observed,
            ),
        ),
    )
    repository = InMemoryEvidenceRepository()
    await repository.save_series(series)
    for value in observations:
        await repository.save_macro("raw-1", value)

    historical = await repository.query_macro(
        "PAYEMS",
        MacroQueryMode.KNOWN_AT,
        as_of=datetime(2020, 2, 8, tzinfo=UTC),
    )
    latest = await repository.query_macro("PAYEMS", MacroQueryMode.LATEST_REVISED)
    published = await repository.query_macro(
        "PAYEMS", MacroQueryMode.AS_PUBLISHED, vintage_date=date(2020, 2, 20)
    )
    assert [item.value for item in historical] == [Decimal("100")]
    assert [item.value for item in published] == [Decimal("100")]
    assert [item.value for item in latest] == [Decimal("102")]
    assert observations[1].predecessor_observation_id == observations[0].observation_id
    assert observations[0].series.source_agency_id == "BLS"
    assert observations[0].lineage.upstream_source_id == "FRED_ALFRED"
    direct_bls = type(series)(
        series.series_id,
        series.title,
        series.geography,
        "BLS",
        series.unit,
        series.frequency,
        series.seasonal_adjustment,
    )
    assert direct_bls.authority_key == series.authority_key


@pytest.mark.asyncio
async def test_macro_known_at_excludes_a_later_observed_backfill() -> None:
    series, observations = MacroNormalizer().normalize_fred(
        macro_payload(),
        adapter_id="fred_official",
        observed_at=OBSERVED,
        ingested_at=OBSERVED,
        raw_hash="f" * 64,
    )
    repository = InMemoryEvidenceRepository()
    await repository.save_series(series)
    for value in observations:
        await repository.save_macro("raw-backfill", value)

    assert not await repository.query_macro(
        "PAYEMS",
        MacroQueryMode.KNOWN_AT,
        as_of=datetime(2020, 3, 7, tzinfo=UTC),
    )
    visible = await repository.query_macro("PAYEMS", MacroQueryMode.KNOWN_AT, as_of=OBSERVED)
    assert [item.value for item in visible] == [Decimal("102")]


def test_macro_pit_rejects_future_vintage_and_supports_operational_replay() -> None:
    _, observations = MacroNormalizer().normalize_fred(
        macro_payload(),
        adapter_id="fred_official",
        observed_at=OBSERVED,
        ingested_at=OBSERVED,
        raw_hash="b" * 64,
    )
    policy = DataAvailabilityPolicy()
    revised = observations[1]
    before = PointInTimeContext(
        datetime(2020, 3, 5, 23, 59, tzinfo=UTC), AvailabilityMode.HISTORICAL_RESEARCH
    )
    after = PointInTimeContext(OBSERVED, AvailabilityMode.HISTORICAL_RESEARCH)
    replay = PointInTimeContext(
        OBSERVED - timedelta(seconds=1), AvailabilityMode.OPERATIONAL_REPLAY
    )
    assert (
        policy.macro_observation(revised, before).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )
    assert (
        policy.macro_observation(revised, after).classification
        is AvailabilityClassification.AVAILABLE
    )
    assert (
        policy.macro_observation(revised, replay).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )


@pytest.mark.asyncio
async def test_schedule_history_reschedule_cancellation_and_actual_linkage() -> None:
    repository = InMemoryEvidenceRepository()
    first_published = datetime(2026, 1, 1, tzinfo=UTC)
    second_published = datetime(2026, 2, 1, tzinfo=UTC)
    cancelled_at = datetime(2026, 3, 1, tzinfo=UTC)
    original_time = datetime(2026, 9, 16, 18, tzinfo=UTC)
    moved_time = datetime(2026, 9, 17, 18, tzinfo=UTC)
    values = (
        event(1, ScheduledEventStatus.SCHEDULED, first_published, original_time),
        event(2, ScheduledEventStatus.RESCHEDULED, second_published, moved_time),
        event(3, ScheduledEventStatus.CANCELLED, cancelled_at, moved_time),
    )
    for value in values:
        await repository.save_scheduled_event(value)

    assert (await repository.scheduled_events_as_of(first_published))[0] == values[0]
    assert (await repository.scheduled_events_as_of(second_published))[0] == values[1]
    assert (await repository.scheduled_events_as_of(cancelled_at))[0] == values[2]

    completed = event(
        4,
        ScheduledEventStatus.COMPLETED,
        datetime(2026, 9, 17, 18, 1, tzinfo=UTC),
        moved_time,
        evidence=("raw_fomc_statement",),
    )
    await repository.save_scheduled_event(completed)
    assert (await repository.scheduled_events_as_of(completed.published_at))[
        0
    ].actual_evidence_ids == ("raw_fomc_statement",)
    with pytest.raises(ValueError, match="actual evidence"):
        event(4, ScheduledEventStatus.COMPLETED, completed.published_at, moved_time)


@pytest.mark.asyncio
async def test_schedule_as_of_excludes_a_later_observed_publication() -> None:
    repository = InMemoryEvidenceRepository()
    published_at = datetime(2026, 1, 1, tzinfo=UTC)
    observed_at = datetime(2026, 2, 1, tzinfo=UTC)
    value = event(
        1,
        ScheduledEventStatus.SCHEDULED,
        published_at,
        datetime(2026, 9, 16, 18, tzinfo=UTC),
        observed_at=observed_at,
    )
    await repository.save_scheduled_event(value)

    assert not await repository.scheduled_events_as_of(datetime(2026, 1, 15, tzinfo=UTC))
    assert await repository.scheduled_events_as_of(observed_at) == (value,)
    policy = DataAvailabilityPolicy()
    before = PointInTimeContext(
        datetime(2026, 1, 15, tzinfo=UTC), AvailabilityMode.HISTORICAL_RESEARCH
    )
    assert (
        policy.scheduled_event(value, before).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )
