from datetime import UTC, date, datetime, timedelta

import pytest

from aic_backend.application.ports import DateInterval
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.application.use_cases import (
    BackfillDailyBars,
    BackfillStatus,
    DailyBarBatchSummary,
    HistoricalDailyBarService,
    chunk_intervals,
)
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.infrastructure.canonical_persistence import InMemoryCanonicalDailyBarRepository
from aic_backend.infrastructure.historical_persistence import InMemoryBackfillMetadataRepository
from aic_backend.provider_runtime.errors import (
    AuthenticationConfigurationError,
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
)

NOW = datetime(2026, 1, 10, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(Market.CN_SZSE, "000001", InstrumentType.EQUITY)


class AdvancingClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


class FakeIngestion:
    def __init__(self, outcomes: list[DailyBarBatchSummary | Exception]) -> None:
        self.outcomes = outcomes
        self.parameters: list[dict[str, object]] = []

    async def execute(self, parameters, *, timeout_ms: int = 5000):
        del timeout_ms
        self.parameters.append(dict(parameters))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def summary(*, failed: int = 0, conflicts: int = 0) -> DailyBarBatchSummary:
    return DailyBarBatchSummary(1, 2, 2, failed, 2, 0, "tushare_pro", conflicts)


def service(
    outcomes: list[DailyBarBatchSummary | Exception], *, chunk_days: int = 3
) -> tuple[BackfillDailyBars, FakeIngestion, InMemoryBackfillMetadataRepository]:
    canonical = InMemoryCanonicalDailyBarRepository()
    metadata = InMemoryBackfillMetadataRepository()
    ingestion = FakeIngestion(outcomes)
    historical = HistoricalDailyBarService(canonical, metadata)
    return (
        BackfillDailyBars(
            historical, ingestion, metadata, AdvancingClock(), SequentialIds(),
            chunk_days=chunk_days,
        ),
        ingestion,
        metadata,
    )


def test_chunking_is_inclusive_deterministic_and_rejects_invalid_size() -> None:
    interval = DateInterval(date(2026, 1, 1), date(2026, 1, 7))
    assert chunk_intervals((interval,), 3) == (
        DateInterval(date(2026, 1, 1), date(2026, 1, 3)),
        DateInterval(date(2026, 1, 4), date(2026, 1, 6)),
        DateInterval(date(2026, 1, 7), date(2026, 1, 7)),
    )
    with pytest.raises(ValueError):
        chunk_intervals((interval,), 0)
    with pytest.raises(ValueError):
        service([], chunk_days=0)


async def test_multiple_chunks_complete_and_second_run_avoids_network() -> None:
    backfill, ingestion, metadata = service([summary(), summary(), summary()])
    first = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 7))
    second = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 7))
    assert first.final_status is BackfillStatus.COMPLETED
    assert first.chunks_attempted == first.chunks_succeeded == 3
    assert second.chunks_attempted == 0
    assert len(ingestion.parameters) == 3
    assert ingestion.parameters[0]["start_date"] == "2026-01-01"
    assert len(await metadata.get_attempts(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 7))) == 3


async def test_middle_chunk_failure_stops_and_resume_skips_completed_chunk() -> None:
    timeout = ProviderTimeoutError("timeout", request_id="r", provider_id="p")
    backfill, ingestion, _ = service([summary(), timeout, summary(), summary()])
    first = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 7))
    assert first.final_status is BackfillStatus.PARTIAL
    assert first.chunks_attempted == 2
    assert first.failed_intervals[0].error_code == "PROVIDER_TIMEOUT"
    second = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 7))
    assert second.final_status is BackfillStatus.COMPLETED
    assert ingestion.parameters[2]["start_date"] == "2026-01-04"


@pytest.mark.parametrize(
    "error",
    [
        ProviderRateLimitedError("rate", request_id="r", provider_id="p"),
        AuthenticationConfigurationError("auth", provider_id="p"),
        ProviderInvalidResponseError("bad", request_id="r", provider_id="p"),
    ],
)
async def test_provider_failures_are_structured(error: Exception) -> None:
    backfill, _, _ = service([error])
    result = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 1))
    assert result.final_status is BackfillStatus.FAILED
    assert result.failed_intervals[0].error_code


async def test_partial_row_failure_and_identity_conflict_are_not_success() -> None:
    backfill, _, _ = service([summary(failed=1, conflicts=1)])
    result = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 1))
    assert result.final_status is BackfillStatus.PARTIAL
    assert result.rows_failed == 1
    assert result.identity_conflicts == 1


async def test_empty_provider_result_confirms_range_and_force_refresh_requeries() -> None:
    empty = DailyBarBatchSummary(1, 0, 0, 0, 0, 0, "tushare_pro")
    backfill, ingestion, _ = service([empty, empty])
    first = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 1))
    assert first.final_status is BackfillStatus.COMPLETED
    assert first.series.bars == ()
    assert first.series.coverage.known_missing_intervals == ()
    await backfill.execute(
        INSTRUMENT, date(2026, 1, 1), date(2026, 1, 1), force_refresh=True
    )
    assert len(ingestion.parameters) == 2


async def test_persistence_and_invalid_request_failures_are_structured() -> None:
    persistence = PersistenceError(
        PersistenceErrorCode.UNAVAILABLE, "persistence unavailable"
    )
    backfill, _, _ = service([persistence])
    result = await backfill.execute(INSTRUMENT, date(2026, 1, 1), date(2026, 1, 1))
    assert result.failed_intervals[0].error_code == "PERSISTENCE_UNAVAILABLE"
    with pytest.raises(ValueError):
        await backfill.execute(INSTRUMENT, date(2026, 1, 2), date(2026, 1, 1))
