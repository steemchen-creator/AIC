import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.etf import ETFDataIngestionService, ETFPointInTimeService
from aic_backend.application.point_in_time import (
    AvailabilityMode,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.application.ports.persistence import (
    PersistedDailyBar,
    PersistenceError,
    PersistenceErrorCode,
    SaveStatus,
)
from aic_backend.data_foundation import create_raw_observation
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.data_foundation.tushare_etf import (
    ETFClassificationEvidence,
    TushareETFAdjustmentFactorNormalizer,
    TushareETFDailyBarNormalizer,
    TushareETFMasterNormalizer,
    TushareETFValuationNormalizer,
    TushareIndexReferenceNormalizer,
)
from aic_backend.data_foundation.validation import (
    CanonicalRecordValidator,
    DailyBarValidator,
    DataValidationService,
    ValidationContext,
)
from aic_backend.domain.market_data import (
    Currency,
    DataCapability,
    DataProvenance,
    ETFChannel,
    ETFInstrumentProfile,
    ETFTracksIndex,
    ETFValuationSnapshot,
    ExposureCategory,
    ExposureFamily,
    ExposureMarket,
    IndexReference,
    InstrumentExecutionProfile,
    InstrumentIdentity,
    InstrumentType,
    ListingStatus,
    Market,
    SettlementCapability,
)
from aic_backend.infrastructure.canonical_persistence import (
    PostgreSQLCanonicalDailyBarRepository,
    canonical_daily_bars,
)
from aic_backend.infrastructure.corporate_action_persistence import (
    PostgreSQLAdjustmentFactorRepository,
)
from aic_backend.infrastructure.etf_persistence import (
    PostgreSQLETFDataRepository,
    etf_index_relationships,
    etf_instrument_profiles,
    etf_valuation_snapshots,
    index_references,
    instrument_execution_profiles,
)
from aic_backend.infrastructure.instrument_persistence import (
    PostgreSQLInstrumentMasterRepository,
)

NOW = datetime(2026, 9, 6, 8, tzinfo=UTC)
DAY = date(2026, 9, 4)
ETF = InstrumentIdentity(Market.CN_SSE, "513100", InstrumentType.ETF)
INDEX = InstrumentIdentity(Market.INDEX_REFERENCE, "NDX-GI", InstrumentType.INDEX)


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    return environment


@pytest.fixture
async def engine() -> AsyncEngine:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=clean_environment(),
    )
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        for table in (
            instrument_execution_profiles,
            etf_valuation_snapshots,
            etf_index_relationships,
            etf_instrument_profiles,
            index_references,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


def provenance() -> DataProvenance:
    return DataProvenance(
        "fixture", "source", "fixture://etf/source", NOW, False, 0, "c" * 64, "fixture/v1"
    )


def profile() -> ETFInstrumentProfile:
    return ETFInstrumentProfile(
        ETF,
        "纳指ETF",
        "纳斯达克100ETF",
        date(2013, 4, 25),
        None,
        ListingStatus.LISTED,
        ETFChannel.QDII,
        INDEX,
        "基金管理人",
        Decimal("0.006"),
        ExposureMarket.US,
        Currency.USD,
        Currency.CNY,
        ExposureCategory.NASDAQ_100,
        provenance(),
        NOW,
        ExposureFamily.NASDAQ,
    )


def index() -> IndexReference:
    return IndexReference(
        INDEX,
        "NASDAQ 100",
        "NASDAQ",
        date(1985, 1, 31),
        Decimal("125"),
        ExposureMarket.US,
        Currency.USD,
        provenance(),
        NOW,
    )


def relationship() -> ETFTracksIndex:
    return ETFTracksIndex(
        "relationship-postgresql",
        ETF,
        INDEX,
        date(2013, 4, 25),
        None,
        False,
        provenance(),
        NOW,
    )


def valuation() -> ETFValuationSnapshot:
    return ETFValuationSnapshot(
        "valuation-postgresql",
        ETF,
        DAY,
        Decimal("1.2"),
        Decimal("1.23"),
        Decimal("100000"),
        Decimal("2.5"),
        provenance(),
        NOW,
    )


def execution_profile() -> InstrumentExecutionProfile:
    return InstrumentExecutionProfile(
        "execution-postgresql",
        ETF,
        Currency.CNY,
        100,
        SettlementCapability.T0,
        "exchange-rule/v1",
        Market.CN_SSE,
        "fixture://exchange-rule",
        NOW,
        DAY,
        "etf-execution/v1",
    )


class ValidationClock:
    def now(self) -> datetime:
        return NOW + timedelta(hours=1)


def raw(
    suffix: str, capability: DataCapability, payload: dict[str, object]
):
    return create_raw_observation(
        observation_id=f"spec009-e2e-{suffix}",
        provider_id="tushare_pro",
        capability=capability,
        received_at=NOW,
        payload=payload,
        source_metadata={"provider_timestamp": NOW},
    )


@pytest.mark.asyncio
async def test_postgresql_etf_index_round_trip_idempotency_and_conflict(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLETFDataRepository(engine)
    values = (profile(), index(), relationship(), valuation(), execution_profile())
    methods = (
        repository.save_etf_profile,
        repository.save_index_reference,
        repository.save_relationship,
        repository.save_valuation,
        repository.save_execution_profile,
    )
    for method, value in zip(methods, values, strict=True):
        assert (await method(value)).status is SaveStatus.INSERTED  # type: ignore[arg-type]
        assert (await method(value)).status is SaveStatus.ALREADY_EXISTS  # type: ignore[arg-type]
    assert await repository.get_etf_profile(ETF) == profile()
    assert await repository.get_index_reference(INDEX) == index()
    assert await repository.get_index_reference(
        InstrumentIdentity(Market.INDEX_REFERENCE, "MISSING", InstrumentType.INDEX)
    ) is None
    assert await repository.list_relationships(ETF) == (relationship(),)
    assert await repository.list_valuations(ETF, DAY, DAY) == (valuation(),)
    with pytest.raises(ValueError, match="end"):
        await repository.list_valuations(ETF, DAY, date(2026, 9, 3))
    assert await repository.list_execution_profiles(ETF) == (execution_profile(),)
    with pytest.raises(PersistenceError) as captured:
        await repository.save_etf_profile(replace(profile(), display_name="冲突名称"))
    assert captured.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


@pytest.mark.asyncio
async def test_tushare_like_etf_data_runs_raw_to_validated_postgresql_and_pit(
    engine: AsyncEngine,
) -> None:
    etf_repository = PostgreSQLETFDataRepository(engine)
    instrument_repository = PostgreSQLInstrumentMasterRepository(engine)
    bar_repository = PostgreSQLCanonicalDailyBarRepository(engine)
    factor_repository = PostgreSQLAdjustmentFactorRepository(engine)
    ingestion = ETFDataIngestionService(
        etf_repository, instrument_repository, bar_repository, factor_repository
    )
    master_observation = raw(
        "master",
        DataCapability.ETF_INSTRUMENT_MASTER,
        {
            "ts_code": "588880.SH",
            "csname": "境内QDII ETF样例",
            "extname": "纳斯达克指数暴露样例",
            "index_code": "NDXFIX.GI",
            "list_date": "20200102",
            "list_status": "L",
            "mgr_name": "样例管理人",
            "mgt_fee": "0.50",
            "etf_type": "QDII",
        },
    )
    bundle = TushareETFMasterNormalizer(
        {
            "588880.SH": ETFClassificationEvidence(
                ExposureMarket.US,
                Currency.USD,
                ExposureCategory.NASDAQ_100,
                ExposureFamily.NASDAQ,
            )
        }
    ).normalize(master_observation)
    index_value = TushareIndexReferenceNormalizer(
        {"NDXFIX.GI": (ExposureMarket.US, Currency.USD)}
    ).normalize(
        raw(
            "index",
            DataCapability.INDEX_REFERENCE,
            {
                "ts_code": "NDXFIX.GI",
                "indx_name": "纳斯达克指数参考样例",
                "pub_party_name": "样例指数发布方",
                "base_date": "19850131",
                "bp": "125",
            },
        )
    )
    bar_value = TushareETFDailyBarNormalizer().normalize(
        raw(
            "bar",
            DataCapability.ETF_DAILY_BAR,
            {
                "ts_code": "588880.SH",
                "trade_date": "20260904",
                "open": "1.20",
                "high": "1.25",
                "low": "1.18",
                "close": "1.23",
                "vol": "1234",
                "amount": "456.7",
            },
        )
    )
    validation = DataValidationService(
        CanonicalRecordValidator(
            ValidationContext(ValidationClock(), timedelta(minutes=5), frozenset({"1.0"}))
        ),
        DailyBarValidator(
            ValidationContext(ValidationClock(), timedelta(minutes=5), frozenset({"1.0"}))
        ),
    ).validate(bar_value)
    assert validation.valid is True
    persisted_bar = PersistedDailyBar(
        master_observation.observation_id,
        bar_value,
        DataQualityAssessment(100, 100, 100, 100, 100),
    )
    factor_value = TushareETFAdjustmentFactorNormalizer().normalize(
        raw(
            "factor",
            DataCapability.ETF_ADJUSTMENT_FACTOR,
            {"ts_code": "588880.SH", "trade_date": "20260904", "adj_factor": "1.25"},
        )
    )
    valuation_value = TushareETFValuationNormalizer().normalize(
        raw(
            "valuation",
            DataCapability.ETF_VALUATION,
            {
                "ts_code": "588880.SH",
                "trade_date": "20260904",
                "nav": "1.20",
                "close": "1.23",
                "total_share": "15.5",
            },
        )
    )

    await ingestion.save_master(bundle)
    await ingestion.save_index_reference(index_value)
    await ingestion.save_daily_bar(persisted_bar)
    await ingestion.save_adjustment_factor(factor_value)
    await ingestion.save_valuation(valuation_value)

    assert await instrument_repository.get_instrument(bundle.master.instrument) == bundle.master
    assert await bar_repository.get_by_record_id(bar_value.record_id) == persisted_bar
    assert (
        await factor_repository.get_adjustment_factor(
            factor_value.instrument, factor_value.trading_date
        )
        == factor_value
    )
    pit = ETFPointInTimeService(etf_repository, DataAvailabilityPolicy())
    context = PointInTimeContext(NOW, AvailabilityMode.HISTORICAL_RESEARCH)
    assert await pit.profile_as_of(bundle.profile.instrument, context) == bundle.profile
    assert await pit.index_reference_as_of(index_value.index_identity, context) == index_value
    assert await pit.valuation_as_of(bundle.profile.instrument, DAY, context) == valuation_value


@pytest.mark.asyncio
async def test_etf_index_migration_is_reversible_and_full_chain_rebuilds(
    engine: AsyncEngine,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(delete(canonical_daily_bars))
    environment = clean_environment()
    for command in (
        ("downgrade", "20260906_0012"),
        ("upgrade", "20260906_0013"),
        ("downgrade", "20260906_0012"),
        ("upgrade", "head"),
        ("downgrade", "base"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            check=True,
            env=environment,
        )
