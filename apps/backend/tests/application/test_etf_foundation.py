from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.application.etf import ETFDataIngestionService, ETFPointInTimeService
from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityMode,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.instruments import InstrumentCoverageAttempt
from aic_backend.application.ports.persistence import (
    PersistedDailyBar,
    PersistenceError,
    SaveStatus,
)
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.domain.market_data import (
    AdjustmentFactor,
    Currency,
    DailyBar,
    DataCapability,
    DataProvenance,
    ETFChannel,
    ETFInstrumentProfile,
    ETFMasterBundle,
    ETFTracksIndex,
    ETFValuationSnapshot,
    ExposureCategory,
    ExposureFamily,
    ExposureMarket,
    IndexReference,
    InstrumentExecutionProfile,
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentType,
    ListingStatus,
    Market,
    SettlementCapability,
)
from aic_backend.infrastructure.canonical_persistence import (
    InMemoryCanonicalDailyBarRepository,
)
from aic_backend.infrastructure.corporate_action_persistence import (
    InMemoryAdjustmentFactorRepository,
)
from aic_backend.infrastructure.etf_persistence import InMemoryETFDataRepository
from aic_backend.infrastructure.instrument_persistence import (
    InMemoryInstrumentCoverageRepository,
    InMemoryInstrumentMasterRepository,
)

EARLY = datetime(2026, 9, 5, 8, tzinfo=UTC)
LATE = datetime(2026, 9, 7, 8, tzinfo=UTC)
ETF = InstrumentIdentity(Market.CN_SSE, "513100", InstrumentType.ETF)
INDEX = InstrumentIdentity(Market.INDEX_REFERENCE, "NDX-GI", InstrumentType.INDEX)
DAY = date(2026, 9, 4)


def provenance(at: datetime = EARLY) -> DataProvenance:
    return DataProvenance(
        "fixture", "source", "fixture://etf/source", at, False, 0, "b" * 64, "fixture/v1"
    )


def master_bundle(at: datetime = EARLY) -> ETFMasterBundle:
    master = InstrumentMaster(
        ETF, "纳指ETF", date(2013, 4, 25), None, ListingStatus.LISTED, at, provenance(at)
    )
    profile = ETFInstrumentProfile(
        ETF,
        "纳指ETF",
        None,
        date(2013, 4, 25),
        None,
        ListingStatus.LISTED,
        ETFChannel.QDII,
        INDEX,
        None,
        None,
        ExposureMarket.US,
        Currency.USD,
        Currency.CNY,
        ExposureCategory.NASDAQ_100,
        provenance(at),
        at,
        ExposureFamily.NASDAQ,
    )
    relationship = ETFTracksIndex(
        f"relationship-{at.date()}",
        ETF,
        INDEX,
        date(2013, 4, 25),
        None,
        False,
        provenance(at),
        at,
    )
    return ETFMasterBundle(master, profile, relationship)


def index_reference(at: datetime = EARLY) -> IndexReference:
    return IndexReference(
        INDEX,
        "NASDAQ 100",
        "NASDAQ",
        date(1985, 1, 31),
        Decimal("125"),
        ExposureMarket.US,
        Currency.USD,
        provenance(at),
        at,
    )


def valuation(at: datetime = EARLY, suffix: str = "early") -> ETFValuationSnapshot:
    return ETFValuationSnapshot(
        f"valuation-{suffix}",
        ETF,
        DAY,
        Decimal("1.2"),
        Decimal("1.23"),
        Decimal("100000"),
        Decimal("2.5"),
        provenance(at),
        at,
    )


def execution_profile(
    at: datetime = EARLY,
    settlement: SettlementCapability = SettlementCapability.T0,
    effective: date = date(2026, 1, 1),
) -> InstrumentExecutionProfile:
    return InstrumentExecutionProfile(
        f"execution-{settlement.value}-{at.date()}-{effective}",
        ETF,
        Currency.CNY,
        100,
        settlement,
        "exchange-rule/v1",
        Market.CN_SSE,
        "fixture://exchange-rule",
        at,
        effective,
        "etf-execution/v1",
    )


def persisted_bar() -> PersistedDailyBar:
    bar = DailyBar(
        "etf-bar",
        "1.0",
        ETF,
        DAY,
        datetime(2026, 9, 4, 7, tzinfo=UTC),
        EARLY,
        EARLY,
        provenance(),
        Decimal("1.2"),
        Decimal("1.25"),
        Decimal("1.18"),
        Decimal("1.23"),
        100000,
        Decimal("123000"),
    )
    return PersistedDailyBar(
        "observation-etf", bar, DataQualityAssessment(100, 100, 100, 100, 100)
    )


@pytest.mark.asyncio
async def test_ingestion_service_reuses_owned_repositories_and_is_idempotent() -> None:
    etf = InMemoryETFDataRepository()
    instruments = InMemoryInstrumentMasterRepository()
    bars = InMemoryCanonicalDailyBarRepository()
    factors = InMemoryAdjustmentFactorRepository()
    service = ETFDataIngestionService(etf, instruments, bars, factors)
    bundle = master_bundle()
    factor = AdjustmentFactor(
        "etf-factor", ETF, DAY, Decimal("1.25"), "factor/v1", EARLY, provenance()
    )
    first = await service.save_master(bundle)
    duplicate = await service.save_master(bundle)
    assert first.master.status is first.profile.status is SaveStatus.INSERTED
    assert first.relationship is not None and first.relationship.status is SaveStatus.INSERTED
    assert duplicate.master.status is duplicate.profile.status is SaveStatus.ALREADY_EXISTS
    assert (await service.save_index_reference(index_reference())).status is SaveStatus.INSERTED
    assert (await service.save_daily_bar(persisted_bar())).status is SaveStatus.INSERTED
    assert (await service.save_adjustment_factor(factor)).status is SaveStatus.INSERTED
    assert (await service.save_valuation(valuation())).status is SaveStatus.INSERTED
    assert (await service.save_execution_profile(execution_profile())).status is SaveStatus.INSERTED
    assert await instruments.get_instrument(ETF) == bundle.master
    assert await bars.get_by_record_id("etf-bar") == persisted_bar()


@pytest.mark.asyncio
async def test_in_memory_repository_filters_orders_and_rejects_identity_conflicts() -> None:
    repository = InMemoryETFDataRepository()
    value = master_bundle().profile
    assert (await repository.save_etf_profile(value)).status is SaveStatus.INSERTED
    assert (await repository.save_etf_profile(value)).status is SaveStatus.ALREADY_EXISTS
    assert await repository.get_etf_profile(ETF) == value
    with pytest.raises(PersistenceError):
        await repository.save_etf_profile(replace(value, display_name="冲突名称"))
    await repository.save_valuation(valuation(LATE, "late"))
    await repository.save_valuation(valuation(EARLY, "early"))
    values = await repository.list_valuations(ETF, DAY, DAY)
    assert [item.valuation_id for item in values] == ["valuation-early", "valuation-late"]
    with pytest.raises(ValueError):
        await repository.list_valuations(ETF, DAY, date(2026, 9, 3))


@pytest.mark.asyncio
async def test_etf_point_in_time_excludes_future_evidence_and_selects_effective_profile() -> None:
    repository = InMemoryETFDataRepository()
    policy = DataAvailabilityPolicy()
    service = ETFPointInTimeService(repository, policy)
    await repository.save_etf_profile(master_bundle(LATE).profile)
    await repository.save_index_reference(index_reference(LATE))
    await repository.save_relationship(master_bundle(LATE).relationship)  # type: ignore[arg-type]
    await repository.save_valuation(valuation(LATE, "late"))
    await repository.save_execution_profile(execution_profile(EARLY, SettlementCapability.T1))
    await repository.save_execution_profile(
        execution_profile(EARLY, SettlementCapability.T0, date(2026, 9, 1))
    )
    context = PointInTimeContext(
        datetime(2026, 9, 6, 8, tzinfo=UTC), AvailabilityMode.HISTORICAL_RESEARCH
    )
    assert await service.index_reference_as_of(INDEX, context) is None
    assert await service.profile_as_of(ETF, context) is None
    assert await service.relationship_as_of(ETF, DAY, context) is None
    assert await service.valuation_as_of(ETF, DAY, context) is None
    selected = await service.execution_profile_as_of(ETF, DAY, context)
    assert selected is not None and selected.settlement_capability is SettlementCapability.T0
    assert selected.effective_from == date(2026, 9, 1)


def test_availability_policy_records_exact_etf_evidence_timestamp() -> None:
    context = PointInTimeContext(EARLY, AvailabilityMode.OPERATIONAL_REPLAY)
    policy = DataAvailabilityPolicy()
    values = (
        policy.etf_profile(master_bundle().profile, context),
        policy.index_reference(index_reference(), context),
        policy.etf_relationship(master_bundle().relationship, context),  # type: ignore[arg-type]
        policy.etf_valuation(valuation(), context),
        policy.execution_profile(execution_profile(), context),
    )
    assert all(value.classification is AvailabilityClassification.AVAILABLE for value in values)
    assert all(value.available_at == EARLY for value in values)
    assert all(value.availability_source == "available_at" for value in values)


def test_etf_daily_bar_future_and_unknown_availability_fail_closed() -> None:
    policy = DataAvailabilityPolicy()
    context = PointInTimeContext(EARLY, AvailabilityMode.HISTORICAL_RESEARCH)
    original = persisted_bar()
    future = replace(
        original,
        record=replace(
            original.record,
            provenance=replace(original.record.provenance, provider_timestamp=LATE),
        ),
    )
    unknown = replace(
        original,
        record=replace(
            original.record,
            record_id="etf-bar-unknown-availability",
            provenance=replace(original.record.provenance, provider_timestamp=None),
        ),
    )
    assert (
        policy.daily_bar(future, context).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )
    assert (
        policy.daily_bar(unknown, context).classification
        is AvailabilityClassification.UNKNOWN_AVAILABILITY
    )


@pytest.mark.asyncio
async def test_etf_sync_coverage_distinguishes_confirmed_empty_from_not_requested() -> None:
    repository = InMemoryInstrumentCoverageRepository()
    interval = DateInterval(DAY, DAY)
    capabilities = (
        (DataCapability.ETF_INSTRUMENT_MASTER, None, None),
        (DataCapability.ETF_DAILY_BAR, ETF, interval),
        (DataCapability.ETF_VALUATION, ETF, interval),
        (DataCapability.ETF_ADJUSTMENT_FACTOR, ETF, interval),
        (DataCapability.INDEX_REFERENCE, INDEX, None),
    )
    for index, (capability, instrument, requested_interval) in enumerate(capabilities):
        await repository.record(
            InstrumentCoverageAttempt(
                f"etf-empty-{index}",
                "tushare_pro",
                capability.value,
                Market.INDEX_REFERENCE if instrument == INDEX else Market.CN_SSE,
                instrument,
                requested_interval,
                EARLY,
                LATE,
                BackfillAttemptStatus.COMPLETED,
                0,
                0,
                0,
                0,
            )
        )
        attempts = await repository.get_attempts(
            capability.value,
            Market.INDEX_REFERENCE if instrument == INDEX else Market.CN_SSE,
            instrument,
            None if requested_interval is None else requested_interval.start,
            None if requested_interval is None else requested_interval.end,
        )
        assert len(attempts) == 1
        assert attempts[0].received_count == 0
        assert attempts[0].status is BackfillAttemptStatus.COMPLETED
    never_requested = await repository.get_attempts(
        DataCapability.ETF_DAILY_BAR.value,
        Market.CN_SSE,
        InstrumentIdentity(Market.CN_SSE, "ETF_NEVER_REQUESTED", InstrumentType.ETF),
        DAY,
        DAY,
    )
    assert never_requested == ()
