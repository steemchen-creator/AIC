from datetime import UTC, date, datetime

from aic_backend.application.ports.calendar import CalendarCoverageAttempt
from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.instruments import InstrumentCoverageAttempt
from aic_backend.application.use_cases.historical_daily_bars import (
    GapClassification,
    HistoricalDailyBarService,
)
from aic_backend.data_foundation.tushare_calendar import TushareCalendarNormalizer
from aic_backend.data_foundation.tushare_instruments import (
    TushareInstrumentMasterNormalizer,
    TushareTradingStatusNormalizer,
)
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.infrastructure.calendar_persistence import (
    InMemoryCalendarCoverageRepository,
    InMemoryTradingCalendarRepository,
)
from aic_backend.infrastructure.instrument_persistence import (
    InMemoryInstrumentCoverageRepository,
    InMemoryInstrumentMasterRepository,
    InMemoryInstrumentTradingStatusRepository,
)
from aic_backend.providers.tushare import TUSHARE_TRADING_STATUS

NOW = datetime(2026, 8, 20, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


class Bars:
    def __init__(self, dates=()):
        self.dates = dates

    async def get_daily_bars(self, instrument, start, end):
        return ()


class Metadata:
    async def get_attempts(self, instrument, start, end):
        return ()


async def build(
    *,
    calendar_complete=True,
    status_complete=True,
    list_date="20260802",
    delist_date=None,
    suspend=None,
):
    calendar, calendar_coverage = (
        InMemoryTradingCalendarRepository(),
        InMemoryCalendarCoverageRepository(),
    )
    masters, statuses, status_coverage = (
        InMemoryInstrumentMasterRepository(),
        InMemoryInstrumentTradingStatusRepository(),
        InMemoryInstrumentCoverageRepository(),
    )
    calendar_normalizer = TushareCalendarNormalizer()
    for value, opened in (
        (date(2026, 8, 1), "0"),
        (date(2026, 8, 2), "1"),
        (date(2026, 8, 3), "1"),
        (date(2026, 8, 4), "1"),
    ):
        await calendar.save(
            calendar_normalizer.normalize(
                {"exchange": "SSE", "cal_date": value.strftime("%Y%m%d"), "is_open": opened},
                provider_id="fixture",
                retrieved_at=NOW,
            )
        )
    if calendar_complete:
        await calendar_coverage.record(
            CalendarCoverageAttempt(
                "cal",
                "fixture",
                Market.CN_SSE,
                DateInterval(date(2026, 8, 1), date(2026, 8, 4)),
                NOW,
                NOW,
                BackfillAttemptStatus.COMPLETED,
                4,
                4,
                0,
                0,
            )
        )
    master = TushareInstrumentMasterNormalizer().normalize(
        {
            "ts_code": "600000.SH",
            "symbol": "600000",
            "name": "浦发银行",
            "exchange": "SSE",
            "list_status": "D" if delist_date else "L",
            "list_date": list_date,
            "delist_date": delist_date,
        },
        provider_id="fixture",
        retrieved_at=NOW,
    )
    await masters.save(master)
    if suspend:
        await statuses.save(
            TushareTradingStatusNormalizer().normalize(
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20260803",
                    "suspend_type": suspend,
                    "suspend_timing": "全天",
                },
                provider_id="fixture",
                retrieved_at=NOW,
            )
        )
    if status_complete:
        await status_coverage.record(
            InstrumentCoverageAttempt(
                "status",
                "fixture",
                TUSHARE_TRADING_STATUS.name,
                Market.CN_SSE,
                INSTRUMENT,
                DateInterval(date(2026, 8, 1), date(2026, 8, 4)),
                NOW,
                NOW,
                BackfillAttemptStatus.COMPLETED,
                1 if suspend else 0,
                1 if suspend else 0,
                0,
                0,
            )
        )
    return HistoricalDailyBarService(
        Bars(), Metadata(), calendar, calendar_coverage, masters, statuses, status_coverage
    )


async def test_gap_classifier_requires_layered_evidence() -> None:
    service = await build(suspend="S")
    result = await service.get_daily_bars(INSTRUMENT, date(2026, 8, 1), date(2026, 8, 4))
    actual = {
        item.trading_date: item.classification for item in result.coverage.gap_classifications
    }
    assert actual == {
        date(2026, 8, 1): GapClassification.NOT_EXPECTED_MARKET_CLOSED,
        date(2026, 8, 2): GapClassification.UNKNOWN,
        date(2026, 8, 3): GapClassification.NOT_EXPECTED_SUSPENDED,
        date(2026, 8, 4): GapClassification.UNKNOWN,
    }


async def test_resume_event_can_prove_probable_gap_for_that_day() -> None:
    service = await build(suspend="R")
    result = await service.get_daily_bars(INSTRUMENT, date(2026, 8, 3), date(2026, 8, 3))
    assert (
        result.coverage.gap_classifications[0].classification is GapClassification.PROBABLE_DATA_GAP
    )


async def test_lifecycle_and_incomplete_evidence_classification() -> None:
    before = await build(list_date="20260803")
    result = await before.get_daily_bars(INSTRUMENT, date(2026, 8, 2), date(2026, 8, 2))
    assert (
        result.coverage.gap_classifications[0].classification
        is GapClassification.NOT_EXPECTED_NOT_LISTED
    )
    after = await build(delist_date="20260802")
    result = await after.get_daily_bars(INSTRUMENT, date(2026, 8, 3), date(2026, 8, 3))
    assert (
        result.coverage.gap_classifications[0].classification
        is GapClassification.NOT_EXPECTED_DELISTED
    )
    unknown = await build(calendar_complete=False, status_complete=False, suspend="R")
    result = await unknown.get_daily_bars(INSTRUMENT, date(2026, 8, 3), date(2026, 8, 3))
    assert len(result.coverage.gap_classifications) == 1
    assert result.coverage.gap_classifications[0].classification is GapClassification.UNKNOWN
