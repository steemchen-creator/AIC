from datetime import UTC, datetime, timedelta

from aic_backend.application.use_cases import (
    DailyBarBatchSummary,
    IngestDailyBars,
    PersistIngestionSuccess,
)
from aic_backend.data_foundation import DataIngestionPipeline
from aic_backend.data_foundation.quality import DailyBarQualityAssessor
from aic_backend.data_foundation.tushare_normalization import TushareDailyBarNormalizer
from aic_backend.data_foundation.validation import DailyBarValidator, ValidationContext
from aic_backend.domain.market_data import DailyBar
from aic_backend.infrastructure.canonical_persistence import InMemoryCanonicalDailyBarRepository
from aic_backend.provider_runtime import (
    ProviderInvocationResult,
    ProviderRequestContext,
)
from aic_backend.providers.tushare import TUSHARE_DAILY

NOW = datetime(2026, 1, 3, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


class FixtureRuntime:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.context: ProviderRequestContext | None = None

    async def execute(self, context: ProviderRequestContext, payload):
        self.context = context
        return ProviderInvocationResult(
            context.request_id,
            "tushare_pro",
            True,
            {"rows": self.rows},
            None,
            1.0,
            NOW,
            NOW,
        )


def row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ts_code": "000001.SZ",
        "trade_date": "20260102",
        "open": "10.1",
        "high": "10.5",
        "low": "9.9",
        "close": "10.2",
        "vol": "1234",
        "amount": "1",
    }
    value.update(changes)
    return value


def service(rows: list[dict[str, object]]) -> tuple[IngestDailyBars, FixtureRuntime]:
    clock = FixedClock()
    runtime = FixtureRuntime(rows)
    pipeline = DataIngestionPipeline(
        {DailyBar.RECORD_TYPE: TushareDailyBarNormalizer()},
        DailyBarValidator(
            ValidationContext(clock, timedelta(minutes=5), frozenset({"1.0"}))
        ),
        DailyBarQualityAssessor(),
    )
    repository = InMemoryCanonicalDailyBarRepository()
    return (
        IngestDailyBars(
            runtime,
            TUSHARE_DAILY,
            pipeline,
            PersistIngestionSuccess(repository),
            clock,
            SequentialIds(),
        ),
        runtime,
    )


async def test_batch_partial_failure_does_not_drop_valid_row() -> None:
    use_case, runtime = service([row(), row(ts_code="INVALID")])
    summary = await use_case.execute({"ts_code": "000001.SZ"})
    assert summary.received == 2
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.persisted == 1
    assert runtime.context is not None
    assert runtime.context.preferred_provider_ids == ()


async def test_duplicate_batch_is_idempotent() -> None:
    use_case, _ = service([row()])
    first = await use_case.execute({"ts_code": "000001.SZ"})
    second = await use_case.execute({"ts_code": "000001.SZ"})
    assert first.persisted == 1
    assert second.persisted == 0
    assert second.already_exists == 1


async def test_empty_result_is_successful_empty_batch() -> None:
    use_case, _ = service([])
    assert await use_case.execute({"trade_date": "20260102"}) == DailyBarBatchSummary(
        1, 0, 0, 0, 0, 0
    )


async def test_malformed_runtime_rows_are_rejected() -> None:
    use_case, runtime = service([])
    runtime.rows = ["invalid"]
    try:
        await use_case.execute({"trade_date": "20260102"})
    except ValueError as error:
        assert "rows" in str(error)
    else:
        raise AssertionError("malformed rows must be rejected")
