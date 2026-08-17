from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityMode,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.application.ports import PersistedDailyBar
from aic_backend.application.use_cases.point_in_time_market_data import (
    PointInTimeAdjustmentUnsupported,
    PointInTimeMarketDataService,
)
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.domain.market_data import (
    AdjustmentFactor,
    AdjustmentMode,
    CorporateAction,
    CorporateActionType,
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentTradingState,
    InstrumentTradingStatus,
    InstrumentType,
    ListingStatus,
    Market,
    TradingSessionDay,
    standard_a_share_session,
)
from aic_backend.infrastructure.calendar_persistence import InMemoryTradingCalendarRepository
from aic_backend.infrastructure.canonical_persistence import InMemoryCanonicalDailyBarRepository
from aic_backend.infrastructure.corporate_action_persistence import (
    InMemoryAdjustmentFactorRepository,
    InMemoryCorporateActionRepository,
)
from aic_backend.infrastructure.instrument_persistence import (
    InMemoryInstrumentMasterRepository,
    InMemoryInstrumentTradingStatusRepository,
)

INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)
AS_OF = datetime(2020, 1, 3, 16, tzinfo=UTC)
TODAY = datetime(2026, 8, 17, tzinfo=UTC)


def provenance(provider_time: datetime | None) -> DataProvenance:
    return DataProvenance(
        "fixture", "source", "fixture://pit", provider_time, False, 0, "0" * 64, "v1"
    )


def bar(
    day: int,
    *,
    provider_time: datetime | None,
    ingested_at: datetime = TODAY,
) -> PersistedDailyBar:
    event = datetime(2020, 1, day, 7, tzinfo=UTC)
    record = DailyBar(
        f"bar-{day}",
        "1.0",
        INSTRUMENT,
        date(2020, 1, day),
        event,
        ingested_at,
        ingested_at,
        provenance(provider_time),
        Decimal("10"),
        Decimal("11"),
        Decimal("9"),
        Decimal("10"),
        100,
        Decimal("1000"),
    )
    return PersistedDailyBar("observation", record, DataQualityAssessment(100, 100, 100, 100, 100))


def context(
    mode: AvailabilityMode = AvailabilityMode.HISTORICAL_RESEARCH,
    *,
    as_of: datetime = AS_OF,
    adjustment: AdjustmentMode = AdjustmentMode.RAW,
) -> PointInTimeContext:
    return PointInTimeContext(as_of, mode, adjustment)


def action(provider_time: datetime | None, retrieved_at: datetime = TODAY) -> CorporateAction:
    return CorporateAction(
        "action",
        INSTRUMENT,
        CorporateActionType.CASH_DIVIDEND,
        date(2020, 1, 2),
        date(2020, 1, 3),
        date(2020, 1, 6),
        date(2020, 1, 3),
        Decimal("0.1"),
        None,
        None,
        retrieved_at,
        provenance(provider_time),
    )


def factor(provider_time: datetime | None, retrieved_at: datetime = TODAY) -> AdjustmentFactor:
    return AdjustmentFactor(
        "factor",
        INSTRUMENT,
        date(2020, 1, 3),
        Decimal("2"),
        "v1",
        retrieved_at,
        provenance(provider_time),
    )


async def service() -> PointInTimeMarketDataService:
    return PointInTimeMarketDataService(
        InMemoryCanonicalDailyBarRepository(),
        InMemoryAdjustmentFactorRepository(),
        InMemoryCorporateActionRepository(),
        InMemoryInstrumentMasterRepository(),
        InMemoryInstrumentTradingStatusRepository(),
        InMemoryTradingCalendarRepository(),
        DataAvailabilityPolicy(),
    )


def test_context_requires_timezone_and_supported_policy() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PointInTimeContext(AS_OF.replace(tzinfo=None), AvailabilityMode.HISTORICAL_RESEARCH)
    with pytest.raises(ValueError, match="policy"):
        PointInTimeContext(AS_OF, AvailabilityMode.HISTORICAL_RESEARCH, policy_version="future")


def test_availability_boundaries_and_unknown_are_explicit() -> None:
    policy = DataAvailabilityPolicy()
    before = bar(2, provider_time=AS_OF.replace(hour=17))
    exact = bar(2, provider_time=AS_OF)
    unknown = bar(2, provider_time=None)
    assert (
        policy.daily_bar(before, context()).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )
    assert policy.daily_bar(exact, context()).classification is AvailabilityClassification.AVAILABLE
    decision = policy.daily_bar(unknown, context())
    assert decision.classification is AvailabilityClassification.UNKNOWN_AVAILABILITY
    assert decision.available_at is None
    assert decision.policy_version == "point-in-time-availability/v1"


async def test_daily_bars_filter_future_and_unknown_with_deterministic_order() -> None:
    value = await service()
    for item in (
        bar(3, provider_time=AS_OF),
        bar(1, provider_time=AS_OF.replace(day=2)),
        bar(2, provider_time=AS_OF.replace(hour=17)),
        bar(4, provider_time=None),
    ):
        await value._daily_bars.save(item)
    result = await value.get_daily_bars_as_of(
        INSTRUMENT, date(2020, 1, 1), date(2020, 1, 4), context()
    )
    assert tuple(item.record.record_id for item in result.records) == ("bar-1", "bar-3")
    assert (result.requested_count, result.available_count) == (4, 2)
    assert (result.excluded_future_count, result.unknown_count) == (1, 1)
    assert result.records[0].record.provenance.provider_id == "fixture"


async def test_historical_research_and_operational_replay_are_not_conflated() -> None:
    value = await service()
    await value._daily_bars.save(bar(2, provider_time=datetime(2020, 1, 2, 8, tzinfo=UTC)))
    historical = await value.get_daily_bars_as_of(
        INSTRUMENT, date(2020, 1, 2), date(2020, 1, 2), context()
    )
    operational = await value.get_daily_bars_as_of(
        INSTRUMENT,
        date(2020, 1, 2),
        date(2020, 1, 2),
        context(AvailabilityMode.OPERATIONAL_REPLAY),
    )
    assert historical.available_count == 1
    assert operational.excluded_future_count == 1


async def test_point_in_time_adjusted_prices_are_explicitly_unsupported() -> None:
    value = await service()
    with pytest.raises(PointInTimeAdjustmentUnsupported, match="RAW"):
        await value.get_daily_bars_as_of(
            INSTRUMENT,
            date(2020, 1, 1),
            date(2020, 1, 2),
            context(adjustment=AdjustmentMode.FORWARD_ADJUSTED),
        )


async def test_corporate_action_and_factor_future_leakage_is_blocked() -> None:
    value = await service()
    await value._actions.save(action(AS_OF.replace(hour=17)))
    await value._factors.save(factor(AS_OF.replace(hour=15)))
    actions = await value.list_corporate_actions_as_of(
        INSTRUMENT, date(2020, 1, 1), date(2020, 1, 31), context()
    )
    factors = await value.list_adjustment_factors_as_of(
        INSTRUMENT, date(2020, 1, 1), date(2020, 1, 31), context()
    )
    assert actions.excluded_future_count == 1 and not actions.records
    assert factors.available_count == 1 and factors.records[0].factor == Decimal("2")


async def test_trading_status_and_calendar_apply_distinct_policies() -> None:
    value = await service()
    status = InstrumentTradingStatus(
        INSTRUMENT,
        date(2020, 1, 3),
        InstrumentTradingState.SUSPENDED,
        "fixture",
        TODAY,
        provenance(AS_OF.replace(hour=17)),
    )
    await value._trading_statuses.save(status)
    calendar = TradingSessionDay(
        Market.CN_SSE,
        date(2020, 1, 3),
        True,
        standard_a_share_session(date(2020, 1, 3)),
        TODAY,
        provenance(None),
    )
    await value._calendar.save(calendar)
    statuses = await value.list_trading_status_as_of(
        INSTRUMENT, date(2020, 1, 3), date(2020, 1, 3), context()
    )
    research_calendar = await value.list_calendar_as_of(
        Market.CN_SSE, date(2020, 1, 3), date(2020, 1, 3), context()
    )
    replay_calendar = await value.list_calendar_as_of(
        Market.CN_SSE,
        date(2020, 1, 3),
        date(2020, 1, 3),
        context(AvailabilityMode.OPERATIONAL_REPLAY),
    )
    assert statuses.excluded_future_count == 1
    assert research_calendar.available_count == 1
    assert replay_calendar.excluded_future_count == 1


async def test_instrument_universe_is_conservative_and_never_uses_current_name() -> None:
    value = await service()
    instruments = value._instruments
    listed = InstrumentMaster(
        INSTRUMENT,
        "Current Name",
        date(2010, 1, 1),
        None,
        ListingStatus.LISTED,
        TODAY,
        provenance(None),
    )
    delisted_identity = InstrumentIdentity(Market.CN_SSE, "600001", InstrumentType.EQUITY)
    delisted = InstrumentMaster(
        delisted_identity,
        "Old Name",
        date(2010, 1, 1),
        date(2019, 12, 31),
        ListingStatus.DELISTED,
        TODAY,
        provenance(datetime(2020, 1, 1, tzinfo=UTC)),
    )
    future_identity = InstrumentIdentity(Market.CN_SSE, "600002", InstrumentType.EQUITY)
    future = InstrumentMaster(
        future_identity,
        "Future",
        date(2021, 1, 1),
        None,
        ListingStatus.LISTED,
        TODAY,
        provenance(None),
    )
    for item in (listed, delisted, future):
        await instruments.save(item)
    result = await value.list_instruments_as_of(date(2020, 1, 3), context())
    assert result.records == (INSTRUMENT,)
    assert all(isinstance(item, InstrumentIdentity) for item in result.records)
    assert result.excluded_future_count == 2
    conservative = await value.list_instruments_as_of(
        date(2020, 1, 3), context(as_of=datetime(2019, 1, 1, tzinfo=UTC))
    )
    assert delisted_identity in conservative.records
    assert conservative.warnings == ("CN.SSE.600001: delisting knowledge unavailable as_of",)


def test_all_record_policies_use_operational_retrieval_evidence() -> None:
    policy = DataAvailabilityPolicy()
    replay = context(AvailabilityMode.OPERATIONAL_REPLAY, as_of=TODAY)
    assert (
        policy.corporate_action(action(None), replay).classification
        is AvailabilityClassification.AVAILABLE
    )
    assert policy.adjustment_factor(factor(None), replay).availability_source == "retrieved_at"
    master = InstrumentMaster(
        INSTRUMENT,
        "Name",
        date(2010, 1, 1),
        None,
        ListingStatus.LISTED,
        TODAY,
        provenance(None),
    )
    status = InstrumentTradingStatus(
        INSTRUMENT,
        date(2020, 1, 3),
        InstrumentTradingState.UNKNOWN,
        None,
        TODAY,
        provenance(None),
    )
    assert (
        policy.instrument_master(master, replay).classification
        is AvailabilityClassification.AVAILABLE
    )
    assert (
        policy.trading_status(status, replay).classification is AvailabilityClassification.AVAILABLE
    )
