from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.application.ports import PersistedDailyBar
from aic_backend.application.ports.historical import BackfillAttemptStatus
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.application.use_cases.adjusted_daily_bars import (
    AdjustmentCoverageIncomplete,
    AdjustmentService,
)
from aic_backend.application.use_cases.corporate_actions import (
    BackfillAdjustmentFactors,
    BackfillCorporateActions,
)
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.data_foundation.tushare_corporate_actions import (
    TushareAdjustmentFactorNormalizer,
    TushareCorporateActionNormalizer,
)
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)
from aic_backend.domain.market_data.corporate_actions import AdjustmentMode, CorporateActionType
from aic_backend.infrastructure.corporate_action_persistence import (
    InMemoryAdjustmentFactorRepository,
    InMemoryCorporateActionRepository,
)
from aic_backend.infrastructure.historical_persistence import InMemoryBackfillMetadataRepository
from aic_backend.provider_runtime import ProviderInvocationResult, ProviderRequestContext
from aic_backend.providers.tushare import TUSHARE_ADJUSTMENT_FACTOR, TUSHARE_CORPORATE_ACTION

NOW = datetime(2026, 8, 17, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)
PROVENANCE = DataProvenance("fixture", "source", "fixture://source", None, False, 0, "0" * 64, "v1")


class Clock:
    def now(self) -> datetime:
        return NOW


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value}"


class Runtime:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def execute(self, context: ProviderRequestContext, payload):
        self.calls += 1
        return ProviderInvocationResult(
            context.request_id, "fixture", True, {"rows": self.rows}, None, 1, NOW, NOW
        )


class FailingRuntime:
    async def execute(self, context: ProviderRequestContext, payload):
        raise ValueError("fixture failure")


def factor_row(day: str, value: str):
    return {"ts_code": "600000.SH", "trade_date": day, "adj_factor": value}


def dividend_row(**changes):
    row = {
        "ts_code": "600000.SH",
        "ann_date": "20260810",
        "record_date": "20260814",
        "ex_date": "20260815",
        "pay_date": "20260817",
        "cash_div_tax": "0.25",
        "stk_bo_rate": "0.10",
        "stk_co_rate": "0.05",
    }
    row.update(changes)
    return row


def stored(day: int, price: str) -> PersistedDailyBar:
    value = Decimal(price)
    record = DailyBar(
        f"record-{day}",
        "1.0",
        INSTRUMENT,
        date(2026, 8, day),
        datetime(2026, 8, day, 7, tzinfo=UTC),
        NOW,
        NOW,
        PROVENANCE,
        value,
        value + 1,
        value - 1,
        value,
        100,
        Decimal("1000"),
    )
    return PersistedDailyBar("observation", record, DataQualityAssessment(100, 100, 100, 100, 100))


def test_normalizers_preserve_decimal_dates_identity_and_provenance() -> None:
    normalizer = TushareAdjustmentFactorNormalizer()
    factor = normalizer.normalize(
        factor_row("20260815", "2.5000"), provider_id="fixture", retrieved_at=NOW
    )
    assert factor.factor == Decimal("2.5000")
    assert factor.factor_id == "CN.SSE.600000:2026-08-15"
    actions = TushareCorporateActionNormalizer().normalize_many(
        dividend_row(), provider_id="fixture", retrieved_at=NOW
    )
    assert tuple(item.action_type for item in actions) == (
        CorporateActionType.CASH_DIVIDEND,
        CorporateActionType.STOCK_DIVIDEND,
        CorporateActionType.CAPITALIZATION,
    )
    assert actions[0].cash_amount == Decimal("0.25")
    assert actions[0].record_date == date(2026, 8, 14)
    assert actions[0].ex_date == date(2026, 8, 15)
    assert actions[0].pay_date == date(2026, 8, 17)


@pytest.mark.parametrize(
    "row",
    [
        factor_row("bad", "1"),
        factor_row("20260815", "0"),
        factor_row("20260815", "x"),
        {"ts_code": "bad", "trade_date": "20260815", "adj_factor": "1"},
    ],
)
def test_factor_normalizer_rejects_malformed_values(row) -> None:
    with pytest.raises(ValueError):
        TushareAdjustmentFactorNormalizer().normalize(row, provider_id="fixture", retrieved_at=NOW)


def test_action_validation_rejects_unsupported_or_contradictory_rows() -> None:
    normalizer = TushareCorporateActionNormalizer()
    with pytest.raises(ValueError, match="no implemented"):
        normalizer.normalize_many(
            dividend_row(cash_div_tax=None, stk_bo_rate=None, stk_co_rate=None),
            provider_id="fixture",
            retrieved_at=NOW,
        )
    with pytest.raises(ValueError):
        normalizer.normalize_many(
            dividend_row(record_date="20260816", ex_date="20260815"),
            provider_id="fixture",
            retrieved_at=NOW,
        )
    action = normalizer.normalize_many(dividend_row(), provider_id="fixture", retrieved_at=NOW)[0]
    with pytest.raises(ValueError, match="non-negative"):
        replace(action, cash_amount=Decimal("-1"))


def test_domain_models_reject_invalid_identity_factor_dates_and_time() -> None:
    factor = TushareAdjustmentFactorNormalizer().normalize(
        factor_row("20260815", "2"), provider_id="fixture", retrieved_at=NOW
    )
    with pytest.raises(ValueError, match="identity"):
        replace(factor, factor_id="")
    with pytest.raises(ValueError, match="positive Decimal"):
        replace(factor, factor=Decimal("0"))
    with pytest.raises(ValueError, match="timezone"):
        replace(factor, retrieved_at=NOW.replace(tzinfo=None))
    action = TushareCorporateActionNormalizer().normalize_many(
        dividend_row(), provider_id="fixture", retrieved_at=NOW
    )[0]
    with pytest.raises(ValueError, match="action_id"):
        replace(action, action_id="")
    with pytest.raises(ValueError, match="pay_date"):
        replace(action, pay_date=date(2026, 8, 14))
    with pytest.raises(ValueError, match="timezone"):
        replace(action, retrieved_at=NOW.replace(tzinfo=None))


def test_action_normalizer_requires_a_dated_fact() -> None:
    with pytest.raises(ValueError, match="date"):
        TushareCorporateActionNormalizer().normalize_many(
            dividend_row(ann_date=None, record_date=None, ex_date=None, pay_date=None),
            provider_id="fixture",
            retrieved_at=NOW,
        )


async def test_adjustment_math_is_exact_deterministic_and_never_mutates_raw() -> None:
    repository = InMemoryAdjustmentFactorRepository()
    normalizer = TushareAdjustmentFactorNormalizer()
    for row in (factor_row("20260814", "2"), factor_row("20260815", "4")):
        await repository.save(normalizer.normalize(row, provider_id="fixture", retrieved_at=NOW))
    bars = (stored(14, "10"), stored(15, "20"))
    service = AdjustmentService(repository)
    raw = await service.adjust(bars, AdjustmentMode.RAW)
    forward = await service.adjust(bars, AdjustmentMode.FORWARD_ADJUSTED)
    backward = await service.adjust(bars, AdjustmentMode.BACKWARD_ADJUSTED)
    assert tuple(item.close for item in raw) == (Decimal("10"), Decimal("20"))
    assert tuple(item.close for item in forward) == (Decimal("5.0"), Decimal("20"))
    assert tuple(item.close for item in backward) == (Decimal("20"), Decimal("80"))
    assert forward == await service.adjust(bars, AdjustmentMode.FORWARD_ADJUSTED)
    assert all(item.volume == 100 and item.turnover == Decimal("1000") for item in forward)
    assert all(item.adjustment_version == "a-share-adjustment/v1" for item in forward)
    assert tuple(item.record.close for item in bars) == (Decimal("10"), Decimal("20"))


async def test_adjustment_requires_complete_factor_coverage() -> None:
    repository = InMemoryAdjustmentFactorRepository()
    await repository.save(
        TushareAdjustmentFactorNormalizer().normalize(
            factor_row("20260815", "4"), provider_id="fixture", retrieved_at=NOW
        )
    )
    with pytest.raises(AdjustmentCoverageIncomplete):
        await AdjustmentService(repository).adjust(
            (stored(14, "10"), stored(15, "20")), AdjustmentMode.FORWARD_ADJUSTED
        )


async def test_adjustment_accepts_empty_series() -> None:
    assert (
        await AdjustmentService(InMemoryAdjustmentFactorRepository()).adjust(
            (), AdjustmentMode.FORWARD_ADJUSTED
        )
        == ()
    )


async def test_in_memory_repositories_are_idempotent_and_conflict_safe() -> None:
    factors = InMemoryAdjustmentFactorRepository()
    value = TushareAdjustmentFactorNormalizer().normalize(
        factor_row("20260815", "4"), provider_id="fixture", retrieved_at=NOW
    )
    assert (await factors.save(value)).status.value == "INSERTED"
    assert (await factors.save(value)).status.value == "ALREADY_EXISTS"
    with pytest.raises(PersistenceError, match="conflict"):
        await factors.save(replace(value, factor=Decimal("5")))
    assert await factors.get_adjustment_factor(INSTRUMENT, date(2026, 8, 15)) == value
    actions = InMemoryCorporateActionRepository()
    action = TushareCorporateActionNormalizer().normalize_many(
        dividend_row(), provider_id="fixture", retrieved_at=NOW
    )[0]
    assert (await actions.save(action)).status.value == "INSERTED"
    assert (await actions.save(action)).status.value == "ALREADY_EXISTS"
    with pytest.raises(PersistenceError, match="conflict"):
        await actions.save(replace(action, cash_amount=Decimal("1")))
    assert await actions.get_corporate_action(action.action_id) == action
    assert await actions.list_corporate_actions(
        INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31)
    ) == (action,)


async def test_factor_backfill_is_idempotent_resumable_and_records_coverage() -> None:
    runtime = Runtime([factor_row("20260815", "4")])
    repository = InMemoryAdjustmentFactorRepository()
    coverage = InMemoryBackfillMetadataRepository()
    use_case = BackfillAdjustmentFactors(
        runtime,
        TUSHARE_ADJUSTMENT_FACTOR,
        repository,
        coverage,
        TushareAdjustmentFactorNormalizer(),
        Clock(),
        Ids(),
        chunk_days=31,
    )
    first = await use_case.execute(INSTRUMENT, date(2026, 8, 15), date(2026, 8, 15))
    second = await use_case.execute(INSTRUMENT, date(2026, 8, 15), date(2026, 8, 15))
    assert (first.status, first.persisted, runtime.calls) == (BackfillAttemptStatus.COMPLETED, 1, 1)
    assert (second.received, second.persisted) == (0, 0)


async def test_factor_backfill_reports_partial_and_provider_failure() -> None:
    coverage = InMemoryBackfillMetadataRepository()
    partial = await BackfillAdjustmentFactors(
        Runtime([factor_row("20260815", "0")]),
        TUSHARE_ADJUSTMENT_FACTOR,
        InMemoryAdjustmentFactorRepository(),
        coverage,
        TushareAdjustmentFactorNormalizer(),
        Clock(),
        Ids(),
    ).execute(INSTRUMENT, date(2026, 8, 15), date(2026, 8, 15))
    failed = await BackfillAdjustmentFactors(
        FailingRuntime(),
        TUSHARE_ADJUSTMENT_FACTOR,
        InMemoryAdjustmentFactorRepository(),
        coverage,
        TushareAdjustmentFactorNormalizer(),
        Clock(),
        Ids(),
    ).execute(INSTRUMENT, date(2026, 8, 16), date(2026, 8, 16))
    assert (partial.status, partial.failed) == (BackfillAttemptStatus.PARTIAL, 1)
    assert failed.status is BackfillAttemptStatus.FAILED
    with pytest.raises(ValueError, match="chunk_days"):
        BackfillAdjustmentFactors(
            Runtime([]),
            TUSHARE_ADJUSTMENT_FACTOR,
            InMemoryAdjustmentFactorRepository(),
            coverage,
            TushareAdjustmentFactorNormalizer(),
            Clock(),
            Ids(),
            chunk_days=0,
        )


async def test_action_backfill_persists_supported_facts_and_reports_failures() -> None:
    coverage = InMemoryBackfillMetadataRepository()
    success = await BackfillCorporateActions(
        Runtime([dividend_row()]),
        TUSHARE_CORPORATE_ACTION,
        InMemoryCorporateActionRepository(),
        coverage,
        TushareCorporateActionNormalizer(),
        Clock(),
        Ids(),
    ).execute(INSTRUMENT, date(2026, 8, 1), date(2026, 8, 31))
    partial = await BackfillCorporateActions(
        Runtime([dividend_row(cash_div_tax="bad")]),
        TUSHARE_CORPORATE_ACTION,
        InMemoryCorporateActionRepository(),
        coverage,
        TushareCorporateActionNormalizer(),
        Clock(),
        Ids(),
    ).execute(INSTRUMENT, date(2026, 9, 1), date(2026, 9, 30))
    failed = await BackfillCorporateActions(
        FailingRuntime(),
        TUSHARE_CORPORATE_ACTION,
        InMemoryCorporateActionRepository(),
        coverage,
        TushareCorporateActionNormalizer(),
        Clock(),
        Ids(),
    ).execute(INSTRUMENT, date(2026, 10, 1), date(2026, 10, 31))
    assert (success.status, success.persisted) == (BackfillAttemptStatus.COMPLETED, 3)
    assert (partial.status, partial.failed) == (BackfillAttemptStatus.PARTIAL, 1)
    assert failed.status is BackfillAttemptStatus.FAILED
