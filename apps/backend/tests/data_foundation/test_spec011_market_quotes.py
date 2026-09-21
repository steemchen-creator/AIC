from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityMode,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.data_foundation.canonical import create_raw_observation
from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.data_foundation.market_quotes import (
    MarketQuoteNormalizer,
    MarketQuoteReconciler,
    MarketQuoteValidator,
)
from aic_backend.domain.market_data import (
    AuthorityLevel,
    DataCapability,
    InstrumentIdentity,
    InstrumentType,
    Market,
    MarketPulseFamily,
    MarketPulseObservation,
    MarketSeriesIdentity,
    PublicationMode,
    QuoteSessionStatus,
    ReconciliationStatus,
    SourceLineage,
    SourceType,
)

NOW = datetime(2026, 9, 21, 7, 0, 10, tzinfo=UTC)
EVENT = NOW - timedelta(seconds=2)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


def lineage(
    upstream: str,
    *,
    event_time: datetime = EVENT,
    observed_at: datetime = NOW,
    ingested_at: datetime = NOW,
    raw_hash: str = "a" * 64,
) -> SourceLineage:
    return SourceLineage(
        f"{upstream}_adapter",
        upstream,
        AuthorityLevel.HIGH_QUALITY_PUBLIC,
        SourceType.PUBLIC_MARKET_FEED,
        event_time,
        observed_at,
        ingested_at,
        raw_hash,
        "quote/v1",
        published_at=event_time,
        source_uri=f"https://{upstream}.example/quote",
        license_id="TEST-ONLY",
    )


def quote(upstream: str, last: str = "10.00", event_time: datetime = EVENT):
    payload = {
        "market": "CN.SSE",
        "symbol": "600000",
        "instrument_type": "EQUITY",
        "event_time": event_time.isoformat(),
        "last": last,
        "bid": "9.99",
        "ask": "10.01",
        "previous_close": "9.80",
        "volume": 100,
        "turnover": "1000",
        "session_status": "OPEN",
    }
    source_lineage = lineage(
        upstream, event_time=event_time, raw_hash=raw_payload_hash(payload)
    )
    observation = create_raw_observation(
        observation_id=f"obs-{upstream}",
        provider_id=f"{upstream}_adapter",
        capability=DataCapability.MARKET_QUOTE,
        received_at=NOW,
        payload=payload,
        source_metadata={},
        lineage=source_lineage,
    )
    return MarketQuoteNormalizer().normalize(observation)


def test_source_lineage_rejects_secret_uri_and_time_reversal() -> None:
    with pytest.raises(ValueError, match="credentials"):
        SourceLineage(
            "adapter",
            "upstream",
            AuthorityLevel.PRIMARY,
            SourceType.OFFICIAL_API,
            EVENT,
            NOW,
            NOW,
            "a" * 64,
            "v1",
            source_uri="https://example.test/data?api_key=secret",
        )
    with pytest.raises(ValueError, match="observed_at"):
        lineage("source", observed_at=NOW + timedelta(seconds=1), ingested_at=NOW)
    with pytest.raises(ValueError, match="published_at"):
        SourceLineage(
            "adapter", "upstream", AuthorityLevel.PRIMARY, SourceType.OFFICIAL_API,
            EVENT, NOW, NOW, "a" * 64, "v1", published_at=NOW + timedelta(seconds=1),
        )


def test_quote_normalization_and_validation_fail_closed() -> None:
    value = quote("eastmoney")
    assert value.instrument == INSTRUMENT
    assert value.last == Decimal("10.00")
    assert MarketQuoteValidator().validate(value).valid
    with pytest.raises(ValueError, match="bid"):
        type(value)(
            value.quote_id,
            value.instrument,
            value.event_time,
            value.observed_at,
            value.ingested_at,
            value.last,
            Decimal("11"),
            Decimal("10"),
            value.previous_close,
            value.volume,
            value.turnover,
            QuoteSessionStatus.OPEN,
            value.lineage,
        )


def test_reconciliation_is_permutation_stable_and_requires_independent_upstreams() -> None:
    reconciler = MarketQuoteReconciler(
        max_age=timedelta(seconds=15), price_tolerance_bps=Decimal("20")
    )
    first = quote("eastmoney", "10.00")
    second = quote("sina", "10.01")
    forward = reconciler.reconcile(INSTRUMENT, (first, second), NOW)
    reverse = reconciler.reconcile(INSTRUMENT, (second, first), NOW)
    assert forward == reverse
    assert forward.status is ReconciliationStatus.CONFIRMED
    assert forward.confidence == Decimal("1")


def test_same_upstream_adapters_are_one_vote_and_stale_sources_are_excluded() -> None:
    reconciler = MarketQuoteReconciler(
        max_age=timedelta(seconds=15), price_tolerance_bps=Decimal("20")
    )
    first = quote("eastmoney", "10.00")
    duplicate = quote("eastmoney", "10.01")
    stale = quote("sina", "10.00", NOW - timedelta(minutes=1))
    result = reconciler.reconcile(INSTRUMENT, (first, duplicate, stale), NOW)
    assert result.status is ReconciliationStatus.DEGRADED
    assert result.contributing_upstream_ids == ("eastmoney",)
    assert "DUPLICATE_UPSTREAM_COLLAPSED" in result.reasons
    assert "STALE_SOURCE_EXCLUDED" in result.reasons


def test_conflicting_independent_prices_fail_closed() -> None:
    result = MarketQuoteReconciler(
        max_age=timedelta(seconds=15), price_tolerance_bps=Decimal("5")
    ).reconcile(INSTRUMENT, (quote("eastmoney", "10"), quote("sina", "11")), NOW)
    assert result.status is ReconciliationStatus.CONFLICTED
    assert result.chosen_quote_id is None


def test_quote_and_pulse_point_in_time_require_observation_availability() -> None:
    policy = DataAvailabilityPolicy()
    value = quote("eastmoney")
    before = PointInTimeContext(NOW - timedelta(seconds=1), AvailabilityMode.HISTORICAL_RESEARCH)
    after = PointInTimeContext(NOW, AvailabilityMode.HISTORICAL_RESEARCH)
    assert (
        policy.market_quote(value, before).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )
    assert policy.market_quote(value, after).classification is AvailabilityClassification.AVAILABLE

    pulse_lineage = lineage("official-index")
    pulse = MarketPulseObservation(
        "pulse-1",
        MarketSeriesIdentity(
            "sp500",
            MarketPulseFamily.EQUITY_INDEX,
            "S&P DJI",
            "S&P 500 index level",
            "US",
            "POINTS",
            PublicationMode.DAILY_REFERENCE,
            "USD",
        ),
        Decimal("6000"),
        EVENT,
        NOW,
        NOW,
        pulse_lineage,
    )
    assert (
        policy.market_pulse(pulse, before).classification
        is AvailabilityClassification.NOT_YET_AVAILABLE
    )
    assert policy.market_pulse(pulse, after).classification is AvailabilityClassification.AVAILABLE
    assert not hasattr(pulse.series, "tradable")
