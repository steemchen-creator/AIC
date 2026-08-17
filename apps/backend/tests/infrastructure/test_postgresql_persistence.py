import asyncio
import os
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.ports import (
    PersistedDailyBar,
    PersistenceError,
    PersistenceErrorCode,
    SaveStatus,
)
from aic_backend.application.use_cases import IngestDailyBars, PersistIngestionSuccess
from aic_backend.data_foundation import DataIngestionPipeline
from aic_backend.data_foundation.quality import (
    DailyBarQualityAssessor,
    DataQualityAssessment,
)
from aic_backend.data_foundation.tushare_normalization import TushareDailyBarNormalizer
from aic_backend.data_foundation.validation import DailyBarValidator, ValidationContext
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)
from aic_backend.infrastructure.canonical_persistence import (
    PostgreSQLCanonicalDailyBarRepository,
    _translate_error,
    canonical_daily_bars,
)
from aic_backend.provider_runtime import ProviderInvocationResult, ProviderRequestContext
from aic_backend.providers.tushare import TUSHARE_DAILY

NOW = datetime(2026, 1, 2, tzinfo=UTC)
RECEIVED = datetime(2026, 1, 3, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return RECEIVED


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


class FixtureDailyRuntime:
    async def execute(
        self, context: ProviderRequestContext, payload: Mapping[str, Any]
    ) -> ProviderInvocationResult:
        del payload
        row = {
            "ts_code": "600000.SH", "trade_date": "20260102",
            "open": "10.1", "high": "10.5", "low": "9.9", "close": "10.2",
            "vol": "1234", "amount": "1",
        }
        return ProviderInvocationResult(
            context.request_id, "tushare_pro", True, {"rows": [row]}, None,
            1.0, RECEIVED, RECEIVED,
        )


def migration_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    return environment


def stored(*, close: str = "10.20", quality: float = 100.0) -> PersistedDailyBar:
    provenance = DataProvenance(
        "fixture", "source-1", "https://fixture.test/1", NOW, True, 1, "a" * 64, "v1"
    )
    record = DailyBar(
        "record-1", "1.0", InstrumentIdentity(Market.CN_SSE, "600519", InstrumentType.EQUITY),
        date(2026, 1, 2), NOW, NOW, NOW, provenance,
        Decimal("10.10"), Decimal("10.50"), Decimal("9.90"), Decimal(close),
        100, Decimal("1010.1234567890"),
    )
    assessment = DataQualityAssessment(quality, 100, 100, 100, 100)
    return PersistedDailyBar("obs-1", record, assessment)


@pytest.fixture
async def engine() -> AsyncEngine:
    url = os.environ["AIC_DATABASE_URL"]
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=migration_environment())
    value = create_async_engine(url, pool_pre_ping=True)
    async with value.begin() as connection:
        await connection.execute(delete(canonical_daily_bars))
    yield value
    await value.dispose()


@pytest.mark.asyncio
async def test_postgresql_round_trip_duplicate_and_first_snapshot(engine: AsyncEngine) -> None:
    repository = PostgreSQLCanonicalDailyBarRepository(engine)
    value = stored()
    assert (await repository.save(value)).status is SaveStatus.INSERTED
    assert (await repository.save(stored(quality=70))).status is SaveStatus.ALREADY_EXISTS
    loaded = await repository.get_by_record_id("record-1")
    assert loaded == value
    assert loaded is not None
    assert loaded.record.turnover == Decimal("1010.1234567890")
    assert loaded.record.event_time.tzinfo is not None
    async with engine.connect() as connection:
        count = await connection.scalar(select(func.count()).select_from(canonical_daily_bars))
    assert count == 1


@pytest.mark.asyncio
async def test_tushare_fixture_vertical_slice_is_idempotent(engine: AsyncEngine) -> None:
    repository = PostgreSQLCanonicalDailyBarRepository(engine)
    clock = FixedClock()
    pipeline = DataIngestionPipeline(
        {DailyBar.RECORD_TYPE: TushareDailyBarNormalizer()},
        DailyBarValidator(
            ValidationContext(clock, timedelta(minutes=5), frozenset({"1.0"}))
        ),
        DailyBarQualityAssessor(),
    )
    use_case = IngestDailyBars(
        FixtureDailyRuntime(), TUSHARE_DAILY, pipeline,
        PersistIngestionSuccess(repository), clock, SequentialIds(),
    )
    first = await use_case.execute({"ts_code": "600000.SH"})
    second = await use_case.execute({"ts_code": "600000.SH"})
    assert first.persisted == 1
    assert second.already_exists == 1
    async with engine.connect() as connection:
        count = await connection.scalar(select(func.count()).select_from(canonical_daily_bars))
    assert count == 1


@pytest.mark.asyncio
async def test_postgresql_identity_conflict_does_not_overwrite(engine: AsyncEngine) -> None:
    repository = PostgreSQLCanonicalDailyBarRepository(engine)
    await repository.save(stored())
    with pytest.raises(PersistenceError) as captured:
        await repository.save(stored(close="10.30"))
    assert captured.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    assert await repository.get_by_record_id("record-1") == stored()


@pytest.mark.asyncio
async def test_concurrent_duplicate_has_one_insert(engine: AsyncEngine) -> None:
    repository = PostgreSQLCanonicalDailyBarRepository(engine)
    outcomes = await asyncio.gather(repository.save(stored()), repository.save(stored()))
    assert sorted(result.status.value for result in outcomes) == [
        SaveStatus.ALREADY_EXISTS.value, SaveStatus.INSERTED.value
    ]
    async with engine.connect() as connection:
        count = await connection.scalar(select(func.count()).select_from(canonical_daily_bars))
    assert count == 1


@pytest.mark.asyncio
async def test_numeric_overflow_rolls_back_atomically(engine: AsyncEngine) -> None:
    repository = PostgreSQLCanonicalDailyBarRepository(engine)
    value = stored()
    oversized = replace(value, record=replace(value.record, open=Decimal("1E+30")))
    with pytest.raises(PersistenceError):
        await repository.save(oversized)
    assert await repository.get_by_record_id("record-1") is None


@pytest.mark.asyncio
async def test_unavailable_database_error_is_safe() -> None:
    engine = create_async_engine(
        "postgresql+asyncpg://aic:secret-value@127.0.0.1:1/missing",
        connect_args={"timeout": 0.1},
    )
    try:
        with pytest.raises(PersistenceError) as captured:
            await PostgreSQLCanonicalDailyBarRepository(engine).save(stored())
        assert captured.value.code is PersistenceErrorCode.UNAVAILABLE
        assert "secret-value" not in str(captured.value)
        with pytest.raises(PersistenceError) as read_captured:
            await PostgreSQLCanonicalDailyBarRepository(engine).get_by_record_id("record-1")
        assert read_captured.value.code is PersistenceErrorCode.UNAVAILABLE
    finally:
        await engine.dispose()


def test_migration_is_repeatable() -> None:
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=migration_environment())
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=migration_environment())


@pytest.mark.parametrize(
    ("error", "reading", "code"),
    [
        (
            IntegrityError("insert", {}, Exception("constraint")),
            False,
            PersistenceErrorCode.CONSTRAINT_VIOLATION,
        ),
        (ValueError("invalid"), False, PersistenceErrorCode.SERIALIZATION_ERROR),
        (TypeError("invalid"), True, PersistenceErrorCode.SERIALIZATION_ERROR),
        (SQLAlchemyError("transaction"), False, PersistenceErrorCode.TRANSACTION_ERROR),
        (SQLAlchemyError("transaction"), True, PersistenceErrorCode.TRANSACTION_ERROR),
    ],
)
def test_error_translation_is_stable_and_sanitized(
    error: SQLAlchemyError | ValueError | TypeError,
    reading: bool,
    code: PersistenceErrorCode,
) -> None:
    translated = _translate_error(error, reading=reading)
    assert translated.code is code
    assert "insert" not in str(translated)
