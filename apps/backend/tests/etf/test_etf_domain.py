from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.application.etf import calculate_tracking_difference
from aic_backend.domain.market_data import (
    Currency,
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
from aic_backend.domain.portfolio.models import OrderSide, Price, Quantity
from aic_backend.domain.portfolio.policies import (
    ConfigurableFeePolicy,
    ConfiguredAssetFeePolicy,
)

AT = datetime(2026, 9, 6, 8, tzinfo=UTC)
ETF = InstrumentIdentity(Market.CN_SSE, "513100", InstrumentType.ETF)
OTHER_ETF = InstrumentIdentity(Market.CN_SZSE, "159941", InstrumentType.ETF)
INDEX = InstrumentIdentity(Market.INDEX_REFERENCE, "NDX", InstrumentType.INDEX)


def provenance() -> DataProvenance:
    return DataProvenance(
        "fixture",
        "source-1",
        "fixture://etf/source-1",
        AT,
        False,
        0,
        "a" * 64,
        "fixture/v1",
    )


def profile() -> ETFInstrumentProfile:
    return ETFInstrumentProfile(
        ETF,
        "纳指ETF",
        "纳斯达克100交易型开放式指数基金",
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
        AT,
        ExposureFamily.NASDAQ,
    )


def relationship() -> ETFTracksIndex:
    return ETFTracksIndex(
        "relationship-1",
        ETF,
        INDEX,
        date(2013, 4, 25),
        None,
        False,
        provenance(),
        AT,
    )


def execution_profile(
    settlement: SettlementCapability = SettlementCapability.T0,
) -> InstrumentExecutionProfile:
    return InstrumentExecutionProfile(
        f"profile-{settlement.value}",
        ETF,
        Currency.CNY,
        100,
        settlement,
        "exchange-product-rule/v1",
        Market.CN_SSE,
        "fixture://exchange-rule",
        AT,
        date(2026, 1, 1),
        "etf-execution/v1",
    )


def test_etf_index_and_relationship_models_are_explicit_and_immutable() -> None:
    index = IndexReference(
        INDEX,
        " Nasdaq 100 ",
        " Nasdaq ",
        date(1985, 1, 31),
        Decimal("125"),
        ExposureMarket.US,
        Currency.USD,
        provenance(),
        AT,
    )
    assert index.display_name == "Nasdaq 100"
    assert index.publisher == "Nasdaq"
    assert index.tradable is False
    assert profile().channel is ETFChannel.QDII
    assert relationship().benchmark_index is INDEX
    with pytest.raises(AttributeError):
        index.display_name = "changed"  # type: ignore[misc]


def test_bundle_requires_one_consistent_instrument_and_benchmark() -> None:
    master = InstrumentMaster(
        ETF,
        "纳指ETF",
        date(2013, 4, 25),
        None,
        ListingStatus.LISTED,
        AT,
        provenance(),
    )
    bundle = ETFMasterBundle(master, profile(), relationship())
    assert bundle.master.instrument == bundle.profile.instrument
    with pytest.raises(ValueError, match="same instrument"):
        ETFMasterBundle(replace(master, instrument=OTHER_ETF), profile(), relationship())
    with pytest.raises(ValueError, match="bundled instrument"):
        ETFMasterBundle(master, profile(), replace(relationship(), etf_instrument=OTHER_ETF))
    with pytest.raises(ValueError, match="profile benchmark"):
        ETFMasterBundle(master, replace(profile(), benchmark_index_identity=None), relationship())


@pytest.mark.parametrize(
    "value",
    [
        lambda: IndexReference(
            InstrumentIdentity(Market.CN_SSE, "000300", InstrumentType.INDEX),
            "CSI 300",
            None,
            None,
            None,
            ExposureMarket.CHINA,
            Currency.CNY,
            provenance(),
            AT,
        ),
        lambda: replace(profile(), trading_currency=Currency.USD),
        lambda: replace(profile(), management_fee=Decimal("-0.01")),
        lambda: replace(profile(), listing_date=None, delisting_date=date(2026, 1, 1)),
        lambda: replace(relationship(), effective_from=None, effective_to=date(2026, 1, 1)),
        lambda: replace(
            relationship(), effective_from=date(2026, 2, 1), effective_to=date(2026, 1, 1)
        ),
        lambda: replace(execution_profile(), board_lot=0),
        lambda: replace(execution_profile(), trading_currency=Currency.USD),
        lambda: replace(execution_profile(), instrument=INDEX),
    ],
)
def test_domain_rejects_unsupported_or_ambiguous_rules(value) -> None:
    with pytest.raises(ValueError):
        value()


def test_valuation_allows_missing_fields_but_rejects_invalid_values() -> None:
    value = ETFValuationSnapshot(
        "valuation-1",
        ETF,
        date(2026, 9, 4),
        None,
        None,
        None,
        None,
        provenance(),
        AT,
    )
    assert value.nav is None
    with pytest.raises(ValueError):
        replace(value, nav=Decimal("0"))
    with pytest.raises(ValueError):
        replace(value, share_size=Decimal("-1"))
    with pytest.raises(TypeError):
        replace(value, premium_discount_pct=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(value, available_at=datetime(2026, 9, 6))


def test_execution_profiles_make_t0_t1_and_unknown_auditable() -> None:
    assert execution_profile(SettlementCapability.T0).same_day_round_trip_allowed is True
    assert execution_profile(SettlementCapability.T1).same_day_round_trip_allowed is False
    assert execution_profile(SettlementCapability.UNKNOWN).same_day_round_trip_allowed is False
    assert execution_profile().price_limit_policy_reference == "exchange-product-rule/v1"


def test_asset_fee_policy_keeps_equity_tax_separate_from_etf_tax() -> None:
    policy = ConfiguredAssetFeePolicy(
        {
            InstrumentType.EQUITY: ConfigurableFeePolicy(
                Decimal("0"), Decimal("0"), Decimal("0.001"), "equity-fee/v1"
            ),
            InstrumentType.ETF: ConfigurableFeePolicy(
                Decimal("0"), Decimal("0"), Decimal("0"), "etf-fee/v1"
            ),
        }
    )
    equity = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)
    _, equity_tax = policy.calculate_for(
        equity, OrderSide.SELL, Quantity(Decimal("100")), Price(Decimal("10"))
    )
    _, etf_tax = policy.calculate_for(
        ETF, OrderSide.SELL, Quantity(Decimal("100")), Price(Decimal("10"))
    )
    assert equity_tax.amount == Decimal("1.000")
    assert etf_tax.amount == 0
    with pytest.raises(ValueError):
        ConfiguredAssetFeePolicy(
            {InstrumentType.ETF: ConfigurableFeePolicy()}, "incomplete/v1"
        )


def test_tracking_difference_uses_same_date_close_returns_deterministically() -> None:
    result = calculate_tracking_difference(
        Decimal("1"), Decimal("1.1"), Decimal("100"), Decimal("108")
    )
    assert result.etf_return == Decimal("0.1")
    assert result.benchmark_return == Decimal("0.08")
    assert result.difference == Decimal("0.02")
    assert result.sample_count == 2
    with pytest.raises(ValueError):
        calculate_tracking_difference(Decimal("0"), Decimal("1"), Decimal("1"), Decimal("1"))
    with pytest.raises(ValueError):
        calculate_tracking_difference(
            Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), policy_version=" "
        )
