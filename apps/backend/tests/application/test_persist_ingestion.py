from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.application.ports import (
    PersistedDailyBar,
    PersistenceError,
    PersistenceErrorCode,
    SaveResult,
    SaveStatus,
)
from aic_backend.application.use_cases import PersistIngestionSuccess
from aic_backend.data_foundation import IngestionFailure, IngestionFailureCode
from aic_backend.data_foundation.ingestion import IngestionSuccess
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.data_foundation.validation import ValidationResult
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)
from aic_backend.infrastructure.canonical_persistence import (
    InMemoryCanonicalDailyBarRepository,
)

NOW = datetime(2026, 1, 2, tzinfo=UTC)


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


@pytest.mark.asyncio
async def test_in_memory_contract_insert_duplicate_read_and_conflict() -> None:
    repository = InMemoryCanonicalDailyBarRepository()
    first = await repository.save(stored())
    duplicate = await repository.save(stored(quality=70))
    assert first.status is SaveStatus.INSERTED
    assert duplicate.status is SaveStatus.ALREADY_EXISTS
    assert await repository.get_by_record_id("record-1") == stored()
    assert await repository.get_by_record_id("missing") is None
    with pytest.raises(PersistenceError) as captured:
        await repository.save(stored(close="10.30"))
    assert captured.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


class CountingRepository(InMemoryCanonicalDailyBarRepository):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def save(self, value: PersistedDailyBar) -> SaveResult:
        self.calls += 1
        return await super().save(value)


@pytest.mark.asyncio
async def test_failed_ingestion_produces_zero_writes() -> None:
    repository = CountingRepository()
    result = await PersistIngestionSuccess(repository).execute(
        IngestionFailure("ing-1", "obs-1", "fixture", IngestionFailureCode.NORMALIZATION_ERROR)
    )
    assert result is None
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_success_is_persisted_without_reprocessing() -> None:
    repository = CountingRepository()
    value = stored()
    ingestion = IngestionSuccess(
        "ing-1", value.observation_id, value.record.record_id, value.record,
        value.record.provenance, ValidationResult(), value.quality,
    )
    result = await PersistIngestionSuccess(repository).execute(ingestion)
    assert result is not None and result.status is SaveStatus.INSERTED
    assert repository.calls == 1
