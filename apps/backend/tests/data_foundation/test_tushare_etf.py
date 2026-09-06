from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aic_backend.data_foundation import create_raw_observation
from aic_backend.data_foundation.normalization import NormalizationError
from aic_backend.data_foundation.tushare_etf import (
    ETFClassificationEvidence,
    TushareETFAdjustmentFactorNormalizer,
    TushareETFDailyBarNormalizer,
    TushareETFMasterNormalizer,
    TushareETFValuationNormalizer,
    TushareIndexDailyBarNormalizer,
    TushareIndexReferenceNormalizer,
)
from aic_backend.domain.market_data import (
    Currency,
    DataCapability,
    ETFChannel,
    ExposureCategory,
    ExposureFamily,
    ExposureMarket,
    InstrumentType,
    Market,
)

RECEIVED = datetime(2026, 9, 6, 8, tzinfo=UTC)


def observation(
    capability: DataCapability,
    row: dict[str, object],
    *,
    metadata: dict[str, object] | None = None,
):
    return create_raw_observation(
        observation_id=f"obs-{capability.value}",
        provider_id="tushare_pro",
        capability=capability,
        received_at=RECEIVED,
        payload=row,
        source_metadata=metadata or {},
    )


def master_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "513100.SH",
        "csname": "纳指ETF",
        "extname": "纳斯达克100ETF",
        "index_code": "NDX.GI",
        "list_date": "20130425",
        "list_status": "L",
        "mgr_name": "基金管理人",
        "mgt_fee": "0.60",
        "etf_type": "QDII",
    }
    row.update(changes)
    return row


def daily_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "513100.SH",
        "trade_date": "20260904",
        "open": "1.20",
        "high": "1.25",
        "low": "1.18",
        "close": "1.24",
        "vol": "1234",
        "amount": "456.7",
    }
    row.update(changes)
    return row


def test_master_normalization_uses_explicit_qdii_classification_and_relationship() -> None:
    normalizer = TushareETFMasterNormalizer(
        {
            "513100.SH": ETFClassificationEvidence(
                ExposureMarket.US,
                Currency.USD,
                ExposureCategory.NASDAQ_100,
                ExposureFamily.NASDAQ,
            )
        }
    )
    first = normalizer.normalize(
        observation(DataCapability.ETF_INSTRUMENT_MASTER, master_row())
    )
    second = normalizer.normalize(
        observation(DataCapability.ETF_INSTRUMENT_MASTER, master_row())
    )
    assert first == second
    assert first.master.instrument.instrument_type is InstrumentType.ETF
    assert first.profile.channel is ETFChannel.QDII
    assert first.profile.underlying_market is ExposureMarket.US
    assert first.profile.underlying_currency is Currency.USD
    assert first.profile.trading_currency is Currency.CNY
    assert first.profile.exposure_family is ExposureFamily.NASDAQ
    assert first.relationship is not None
    assert first.relationship.benchmark_index.market is Market.INDEX_REFERENCE
    assert first.relationship.current_relationship_only is True


def test_master_never_guesses_exposure_from_product_name() -> None:
    result = TushareETFMasterNormalizer().normalize(
        observation(DataCapability.ETF_INSTRUMENT_MASTER, master_row())
    )
    assert result.profile.exposure_category is ExposureCategory.UNKNOWN
    assert result.profile.underlying_market is ExposureMarket.UNKNOWN
    assert result.profile.underlying_currency is Currency.UNKNOWN


def test_domestic_master_without_benchmark_is_preserved() -> None:
    row = master_row(
        ts_code="510300.SH",
        csname="沪深300ETF",
        index_code=None,
        etf_type="境内",
        mgt_fee=None,
    )
    result = TushareETFMasterNormalizer().normalize(
        observation(DataCapability.ETF_INSTRUMENT_MASTER, row)
    )
    assert result.profile.channel is ETFChannel.DOMESTIC
    assert result.profile.management_fee is None
    assert result.relationship is None


def test_index_reference_and_daily_bar_use_non_tradable_namespace() -> None:
    reference = TushareIndexReferenceNormalizer(
        {"NDX.GI": (ExposureMarket.US, Currency.USD)}
    ).normalize(
        observation(
            DataCapability.INDEX_REFERENCE,
            {
                "ts_code": "NDX.GI",
                "indx_name": "NASDAQ 100",
                "pub_party_name": "NASDAQ",
                "base_date": "19850131",
                "bp": "125",
            },
        )
    )
    bar = TushareIndexDailyBarNormalizer().normalize(
        observation(DataCapability.INDEX_DAILY_BAR, daily_row(ts_code="NDX.GI"))
    )
    assert reference.index_identity == bar.instrument
    assert reference.tradable is False
    assert reference.point_currency is Currency.USD
    assert bar.volume == 123400
    assert bar.turnover == Decimal("456700.0")


def test_etf_daily_units_event_time_and_provenance_are_canonical() -> None:
    provider_time = datetime(2026, 9, 5, 8, tzinfo=UTC)
    bar = TushareETFDailyBarNormalizer().normalize(
        observation(
            DataCapability.ETF_DAILY_BAR,
            daily_row(),
            metadata={"provider_timestamp": provider_time, "failover_count": 1},
        )
    )
    assert bar.volume == 123400
    assert bar.turnover == Decimal("456700.0")
    assert bar.event_time == datetime(2026, 9, 4, 7, tzinfo=UTC)
    assert bar.provenance.provider_timestamp == provider_time
    assert bar.provenance.received_via_failover is True
    assert bar.provenance.raw_payload_hash


def test_adjustment_factor_and_valuation_preserve_exact_decimal_units() -> None:
    factor = TushareETFAdjustmentFactorNormalizer().normalize(
        observation(
            DataCapability.ETF_ADJUSTMENT_FACTOR,
            {"ts_code": "513100.SH", "trade_date": "20260904", "adj_factor": "1.25"},
        )
    )
    valuation = TushareETFValuationNormalizer().normalize(
        observation(
            DataCapability.ETF_VALUATION,
            {
                "ts_code": "513100.SH",
                "trade_date": "20260904",
                "nav": "1.20",
                "close": "1.23",
                "total_share": "15.5",
            },
        )
    )
    missing = TushareETFValuationNormalizer().normalize(
        observation(
            DataCapability.ETF_VALUATION,
            {
                "ts_code": "513100.SH",
                "trade_date": "20260904",
                "nav": None,
                "close": None,
                "total_share": None,
            },
        )
    )
    discount = TushareETFValuationNormalizer().normalize(
        observation(
            DataCapability.ETF_VALUATION,
            {
                "ts_code": "513100.SH",
                "trade_date": "20260904",
                "nav": "1.25",
                "close": "1.20",
                "total_share": "15.5",
            },
        )
    )
    assert factor.factor == Decimal("1.25")
    assert valuation.share_size == Decimal("155000.0")
    assert valuation.premium_discount_pct == Decimal("2.500")
    assert discount.premium_discount_pct == Decimal("-4.00")
    assert missing.premium_discount_pct is None


@pytest.mark.parametrize(
    ("normalizer", "capability", "row"),
    [
        (TushareETFDailyBarNormalizer(), DataCapability.ETF_DAILY_BAR, daily_row(open="nan")),
        (TushareETFDailyBarNormalizer(), DataCapability.ETF_DAILY_BAR, daily_row(open=True)),
        (TushareETFDailyBarNormalizer(), DataCapability.ETF_DAILY_BAR, daily_row(high="bad")),
        (TushareETFDailyBarNormalizer(), DataCapability.ETF_DAILY_BAR, daily_row(amount=None)),
        (TushareETFDailyBarNormalizer(), DataCapability.ETF_DAILY_BAR, daily_row(vol="1.001")),
        (
            TushareIndexDailyBarNormalizer(),
            DataCapability.INDEX_DAILY_BAR,
            daily_row(ts_code="NDX.GI", vol="1.001"),
        ),
        (
            TushareETFMasterNormalizer(),
            DataCapability.ETF_INSTRUMENT_MASTER,
            master_row(ts_code="513100.NYSE"),
        ),
        (
            TushareETFMasterNormalizer(),
            DataCapability.ETF_INSTRUMENT_MASTER,
            master_row(list_status="BAD"),
        ),
        (
            TushareETFAdjustmentFactorNormalizer(),
            DataCapability.ETF_ADJUSTMENT_FACTOR,
            {"ts_code": "513100.SH", "trade_date": "bad", "adj_factor": "1"},
        ),
        (
            TushareIndexReferenceNormalizer(),
            DataCapability.INDEX_REFERENCE,
            {"ts_code": "", "indx_name": "index"},
        ),
    ],
)
def test_invalid_vendor_rows_fail_closed(normalizer, capability, row) -> None:
    with pytest.raises(NormalizationError):
        normalizer.normalize(observation(capability, row))


def test_capability_and_provenance_metadata_are_validated() -> None:
    wrong = observation(DataCapability.DAILY_BAR, daily_row())
    with pytest.raises(NormalizationError):
        TushareETFDailyBarNormalizer().normalize(wrong)
    with pytest.raises(NormalizationError):
        TushareETFDailyBarNormalizer().normalize(
            observation(
                DataCapability.ETF_DAILY_BAR,
                daily_row(),
                metadata={"failover_count": True},
            )
        )
    with pytest.raises(NormalizationError):
        TushareETFDailyBarNormalizer().normalize(
            observation(
                DataCapability.ETF_DAILY_BAR,
                daily_row(),
                metadata={"provider_timestamp": "not-a-datetime"},
            )
        )
