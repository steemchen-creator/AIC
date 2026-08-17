from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest

from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.instruments import InstrumentCoverageAttempt
from aic_backend.application.ports.persistence import PersistenceError
from aic_backend.application.use_cases.instruments import (
    BackfillInstrumentTradingStatus,
    InstrumentService,
    SyncInstrumentMaster,
)
from aic_backend.data_foundation.tushare_instruments import (
    TushareInstrumentMasterNormalizer,
    TushareTradingStatusNormalizer,
)
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentTradingState,
    InstrumentType,
    ListingStatus,
    Market,
)
from aic_backend.infrastructure.instrument_persistence import (
    InMemoryInstrumentCoverageRepository,
    InMemoryInstrumentMasterRepository,
    InMemoryInstrumentTradingStatusRepository,
)
from aic_backend.provider_runtime import (
    ProviderInvocationResult,
    ProviderRequestContext,
)
from aic_backend.providers.tushare import TUSHARE_INSTRUMENT_MASTER, TUSHARE_TRADING_STATUS

NOW = datetime(2026, 8, 17, tzinfo=UTC)
SZ = InstrumentIdentity(Market.CN_SZSE, "000001", InstrumentType.EQUITY)


class Clock:
    def now(self):
        return NOW


class Ids:
    def __init__(self):
        self.i = 0

    def new_id(self, prefix: str):
        self.i += 1
        return f"{prefix}_{self.i}"


class Runtime:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def execute(self, context: ProviderRequestContext, payload):
        self.calls += 1
        return ProviderInvocationResult(
            context.request_id, "tushare", True, {"rows": self.rows}, None, 1, NOW, NOW
        )


class FailingRuntime:
    async def execute(self, context: ProviderRequestContext, payload):
        raise ValueError("fixture failure")


def master_row(**overrides):
    value = {
        "ts_code": "000001.SZ",
        "symbol": "000001",
        "name": "平安银行",
        "exchange": "SZSE",
        "list_status": "L",
        "list_date": "19910403",
        "delist_date": None,
    }
    value.update(overrides)
    return value


def status_row(**overrides):
    value = {
        "ts_code": "000001.SZ",
        "trade_date": "20260817",
        "suspend_type": "S",
        "suspend_timing": "全天",
    }
    value.update(overrides)
    return value


def test_master_normalizes_sz_sh_listing_and_delisting() -> None:
    normalizer = TushareInstrumentMasterNormalizer()
    listed = normalizer.normalize(master_row(), provider_id="fixture", retrieved_at=NOW)
    delisted = normalizer.normalize(
        master_row(
            ts_code="600000.SH",
            symbol="600000",
            name="浦发银行",
            exchange="SSE",
            list_status="D",
            delist_date="20260817",
        ),
        provider_id="fixture",
        retrieved_at=NOW,
    )
    assert listed.instrument == SZ and listed.listing_date == date(1991, 4, 3)
    assert listed.listing_status is ListingStatus.LISTED
    assert delisted.instrument.market is Market.CN_SSE
    assert delisted.listing_status is ListingStatus.DELISTED
    assert delisted.delisting_date == date(2026, 8, 17)


@pytest.mark.parametrize(
    "change",
    [
        {"exchange": "SSE"},
        {"list_status": "X"},
        {"list_date": "bad"},
        {"list_date": "20260818", "delist_date": "20260817"},
        {"name": " "},
    ],
)
def test_master_rejects_invalid_vendor_or_lifecycle(change) -> None:
    with pytest.raises(ValueError):
        TushareInstrumentMasterNormalizer().normalize(
            master_row(**change), provider_id="fixture", retrieved_at=NOW
        )


def test_status_normalizes_suspend_resume_and_rejects_unknown() -> None:
    normalizer = TushareTradingStatusNormalizer()
    suspended = normalizer.normalize(status_row(), provider_id="fixture", retrieved_at=NOW)
    resumed = normalizer.normalize(
        status_row(suspend_type="R"), provider_id="fixture", retrieved_at=NOW
    )
    assert suspended.state is InstrumentTradingState.SUSPENDED
    assert resumed.state is InstrumentTradingState.TRADING
    with pytest.raises(ValueError):
        normalizer.normalize(status_row(suspend_type="X"), provider_id="fixture", retrieved_at=NOW)


async def test_master_sync_and_status_backfill_are_idempotent_and_covered() -> None:
    masters, statuses = (
        InMemoryInstrumentMasterRepository(),
        InMemoryInstrumentTradingStatusRepository(),
    )
    coverage, ids = InMemoryInstrumentCoverageRepository(), Ids()
    master_runtime = Runtime([master_row()])
    sync = SyncInstrumentMaster(
        master_runtime,
        TUSHARE_INSTRUMENT_MASTER,
        masters,
        coverage,
        TushareInstrumentMasterNormalizer(),
        Clock(),
        ids,
    )
    first = await sync.execute(Market.CN_SZSE)
    second = await sync.execute(Market.CN_SZSE)
    assert (first.persisted, second.already_exists) == (1, 1)
    status_runtime = Runtime([status_row()])
    backfill = BackfillInstrumentTradingStatus(
        status_runtime,
        TUSHARE_TRADING_STATUS,
        statuses,
        coverage,
        TushareTradingStatusNormalizer(),
        Clock(),
        ids,
    )
    result = await backfill.execute(SZ, date(2026, 8, 17), date(2026, 8, 17))
    repeated = await backfill.execute(SZ, date(2026, 8, 17), date(2026, 8, 17))
    service = InstrumentService(masters, statuses, coverage, TUSHARE_TRADING_STATUS)
    assert result.status is BackfillAttemptStatus.COMPLETED and repeated.received == 0
    assert status_runtime.calls == 1
    assert await service.status_coverage_complete(SZ, date(2026, 8, 17), date(2026, 8, 17))


async def test_empty_status_response_confirms_coverage_but_does_not_invent_trading() -> None:
    statuses, coverage = (
        InMemoryInstrumentTradingStatusRepository(),
        InMemoryInstrumentCoverageRepository(),
    )
    backfill = BackfillInstrumentTradingStatus(
        Runtime([]),
        TUSHARE_TRADING_STATUS,
        statuses,
        coverage,
        TushareTradingStatusNormalizer(),
        Clock(),
        Ids(),
    )
    result = await backfill.execute(SZ, date(2026, 8, 17), date(2026, 8, 17))
    assert result.status is BackfillAttemptStatus.COMPLETED
    assert await statuses.get_trading_status(SZ, date(2026, 8, 17)) is None


async def test_partial_status_row_stops_safe_resume_and_conflict_is_rejected() -> None:
    statuses, coverage = (
        InMemoryInstrumentTradingStatusRepository(),
        InMemoryInstrumentCoverageRepository(),
    )
    backfill = BackfillInstrumentTradingStatus(
        Runtime([status_row(), status_row(suspend_type="X")]),
        TUSHARE_TRADING_STATUS,
        statuses,
        coverage,
        TushareTradingStatusNormalizer(),
        Clock(),
        Ids(),
    )
    result = await backfill.execute(SZ, date(2026, 8, 17), date(2026, 8, 17))
    assert result.status is BackfillAttemptStatus.PARTIAL and result.failed == 1
    conflicting = TushareTradingStatusNormalizer().normalize(
        status_row(suspend_type="R"), provider_id="fixture", retrieved_at=NOW
    )
    with pytest.raises(PersistenceError, match="identity conflict"):
        await statuses.save(conflicting)


def test_instrument_models_validate_boundaries_and_normalize_reason() -> None:
    master = TushareInstrumentMasterNormalizer().normalize(
        master_row(), provider_id="fixture", retrieved_at=NOW
    )
    with pytest.raises(ValueError, match="market"):
        replace(
            master,
            instrument=InstrumentIdentity(cast(Market, "US"), "ABC", InstrumentType.EQUITY),
        )
    with pytest.raises(ValueError, match="equities"):
        replace(master, instrument=InstrumentIdentity(Market.CN_SZSE, "159001", InstrumentType.ETF))
    with pytest.raises(ValueError, match="requires"):
        replace(master, listing_date=None, delisting_date=date(2026, 8, 17))
    with pytest.raises(ValueError, match="timezone"):
        replace(master, retrieved_at=NOW.replace(tzinfo=None))
    status = TushareTradingStatusNormalizer().normalize(
        status_row(suspend_timing="  "), provider_id="fixture", retrieved_at=NOW
    )
    assert status.reason is None
    with pytest.raises(ValueError, match="market"):
        replace(
            status,
            instrument=InstrumentIdentity(cast(Market, "US"), "ABC", InstrumentType.EQUITY),
        )
    with pytest.raises(ValueError, match="timezone"):
        replace(status, retrieved_at=NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    "change",
    [
        {"attempt_id": ""},
        {"requested_at": NOW.replace(tzinfo=None)},
        {"completed_at": NOW.replace(tzinfo=None)},
        {"completed_at": NOW - timedelta(seconds=1)},
        {"failed_count": -1},
    ],
)
def test_instrument_coverage_attempt_validates_input(change) -> None:
    values = {
        "attempt_id": "attempt",
        "provider_id": "fixture",
        "capability": TUSHARE_TRADING_STATUS.name,
        "market": Market.CN_SZSE,
        "instrument": SZ,
        "interval": DateInterval(date(2026, 8, 17), date(2026, 8, 17)),
        "requested_at": NOW,
        "completed_at": NOW,
        "status": BackfillAttemptStatus.COMPLETED,
        "received_count": 0,
        "persisted_count": 0,
        "already_exists_count": 0,
        "failed_count": 0,
    }
    values.update(change)
    with pytest.raises(ValueError):
        InstrumentCoverageAttempt(**values)


async def test_services_queries_failures_and_row_boundaries() -> None:
    masters = InMemoryInstrumentMasterRepository()
    statuses = InMemoryInstrumentTradingStatusRepository()
    coverage = InMemoryInstrumentCoverageRepository()
    service = InstrumentService(masters, statuses, coverage, TUSHARE_TRADING_STATUS)
    assert await service.get_instrument(SZ) is None
    assert await service.status_on(SZ, date(2026, 8, 17)) is None
    assert not await service.status_coverage_complete(SZ, date(2026, 8, 17), date(2026, 8, 17))

    failed_master = await SyncInstrumentMaster(
        FailingRuntime(),
        TUSHARE_INSTRUMENT_MASTER,
        masters,
        coverage,
        TushareInstrumentMasterNormalizer(),
        Clock(),
        Ids(),
    ).execute(Market.CN_SZSE)
    assert failed_master.status is BackfillAttemptStatus.FAILED
    assert failed_master.error_code == "ValueError"

    wrong_market = await SyncInstrumentMaster(
        Runtime([master_row(ts_code="600000.SH", symbol="600000", exchange="SSE")]),
        TUSHARE_INSTRUMENT_MASTER,
        masters,
        coverage,
        TushareInstrumentMasterNormalizer(),
        Clock(),
        Ids(),
    ).execute(Market.CN_SZSE)
    assert wrong_market.status is BackfillAttemptStatus.PARTIAL
    assert wrong_market.error_code == "ValueError"

    with pytest.raises(ValueError, match="positive"):
        BackfillInstrumentTradingStatus(
            Runtime([]),
            TUSHARE_TRADING_STATUS,
            statuses,
            coverage,
            TushareTradingStatusNormalizer(),
            Clock(),
            Ids(),
            chunk_days=0,
        )
    failed_status = await BackfillInstrumentTradingStatus(
        FailingRuntime(),
        TUSHARE_TRADING_STATUS,
        statuses,
        coverage,
        TushareTradingStatusNormalizer(),
        Clock(),
        Ids(),
    ).execute(SZ, date(2026, 8, 18), date(2026, 8, 18))
    assert failed_status.status is BackfillAttemptStatus.FAILED
    outside = await BackfillInstrumentTradingStatus(
        Runtime([status_row(trade_date="20260819")]),
        TUSHARE_TRADING_STATUS,
        statuses,
        coverage,
        TushareTradingStatusNormalizer(),
        Clock(),
        Ids(),
    ).execute(SZ, date(2026, 8, 18), date(2026, 8, 18))
    assert outside.status is BackfillAttemptStatus.PARTIAL
    assert outside.error_code == "ValueError"


async def test_in_memory_repositories_filter_order_and_conflicts() -> None:
    masters = InMemoryInstrumentMasterRepository()
    statuses = InMemoryInstrumentTradingStatusRepository()
    first = TushareInstrumentMasterNormalizer().normalize(
        master_row(), provider_id="fixture", retrieved_at=NOW
    )
    second = TushareInstrumentMasterNormalizer().normalize(
        master_row(ts_code="600000.SH", symbol="600000", exchange="SSE", name="浦发银行"),
        provider_id="fixture",
        retrieved_at=NOW,
    )
    await masters.save(second)
    await masters.save(first)
    assert await masters.find_instrument(Market.CN_SZSE, "000001") == first
    assert await masters.find_instrument(Market.CN_SZSE, "missing") is None
    assert await masters.list_instruments(Market.CN_SZSE) == (first,)
    with pytest.raises(PersistenceError):
        await masters.save(replace(first, display_name="冲突"))

    suspended = TushareTradingStatusNormalizer().normalize(
        status_row(), provider_id="fixture", retrieved_at=NOW
    )
    resumed = replace(
        suspended,
        trading_date=date(2026, 8, 18),
        state=InstrumentTradingState.TRADING,
    )
    await statuses.save(resumed)
    await statuses.save(suspended)
    assert await statuses.list_trading_status(SZ, date(2026, 8, 17), date(2026, 8, 18)) == (
        suspended,
        resumed,
    )

    coverage = InMemoryInstrumentCoverageRepository()
    matching = InstrumentCoverageAttempt(
        "matching",
        "fixture",
        TUSHARE_TRADING_STATUS.name,
        Market.CN_SZSE,
        SZ,
        DateInterval(date(2026, 8, 17), date(2026, 8, 18)),
        NOW,
        NOW,
        BackfillAttemptStatus.COMPLETED,
        0,
        0,
        0,
        0,
    )
    master_attempt = replace(
        matching,
        attempt_id="master",
        capability=TUSHARE_INSTRUMENT_MASTER.name,
        instrument=None,
        interval=None,
    )
    await coverage.record(matching)
    await coverage.record(master_attempt)
    assert await coverage.get_attempts(
        TUSHARE_TRADING_STATUS.name,
        Market.CN_SZSE,
        SZ,
        date(2026, 8, 18),
        date(2026, 8, 18),
    ) == (matching,)
    assert await coverage.get_attempts(
        TUSHARE_INSTRUMENT_MASTER.name, Market.CN_SZSE, None, None, None
    ) == (master_attempt,)
