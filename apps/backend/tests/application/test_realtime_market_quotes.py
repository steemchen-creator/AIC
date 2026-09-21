from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from aic_backend.application.use_cases.realtime_market_quotes import (
    QuoteInstrumentResolver,
    QuoteSourceConfig,
    RealtimeMarketQuoteService,
)
from aic_backend.data_foundation.market_quotes import MarketQuoteReconciler
from aic_backend.domain.market_data import (
    AuthorityLevel,
    InstrumentIdentity,
    InstrumentType,
    Market,
    ReconciliationStatus,
    SourceType,
)
from aic_backend.infrastructure.market_intelligence_persistence import (
    InMemoryMarketIntelligenceRepository,
)
from aic_backend.provider_runtime import (
    ProviderInvocationResult,
    ProviderRequestContext,
)
from aic_backend.providers.domestic_quotes import MARKET_QUOTE_REALTIME

NOW = datetime(2026, 9, 21, 7, 0, 10, tzinfo=UTC)
EVENT = NOW - timedelta(seconds=2)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class KnownInstruments:
    def __init__(self, known: bool = True) -> None:
        self.known = known

    async def get_instrument(self, identity: InstrumentIdentity) -> object | None:
        return object() if self.known and identity == INSTRUMENT else None


class EmptyETF:
    async def get_etf_profile(self, identity: InstrumentIdentity) -> None:
        return None

    async def get_index_reference(self, identity: InstrumentIdentity) -> None:
        return None


class FixtureRuntime:
    def __init__(self, providers: tuple[str, ...], prices: Mapping[str, str]) -> None:
        self.providers = providers
        self.prices = prices
        self.calls = 0

    async def execute(
        self, context: ProviderRequestContext, payload: Mapping[str, Any]
    ) -> ProviderInvocationResult:
        provider = self.providers[self.calls]
        self.calls += 1
        data = {
            "market": payload["market"],
            "symbol": payload["symbol"],
            "instrument_type": payload["instrument_type"],
            "event_time": EVENT.isoformat(),
            "last": self.prices[provider],
            "bid": "9.99",
            "ask": "10.01",
            "previous_close": "9.8",
            "volume": 100,
            "turnover": "1000",
            "session_status": "OPEN",
        }
        return ProviderInvocationResult(
            context.request_id,
            provider,
            True,
            data,
            None,
            1,
            NOW,
            NOW,
            failover_count=0,
        )


def source(adapter: str, upstream: str) -> QuoteSourceConfig:
    return QuoteSourceConfig(
        adapter,
        upstream,
        AuthorityLevel.HIGH_QUALITY_PUBLIC,
        SourceType.PUBLIC_MARKET_FEED,
        f"https://{upstream}.example/quote",
        "TEST-ONLY",
    )


def service(runtime: FixtureRuntime, sources: tuple[QuoteSourceConfig, ...], *, known: bool = True):
    repository = InMemoryMarketIntelligenceRepository()
    resolver = QuoteInstrumentResolver(KnownInstruments(known), EmptyETF())  # type: ignore[arg-type]
    return (
        RealtimeMarketQuoteService(
            runtime,
            repository,
            repository,
            resolver,
            MARKET_QUOTE_REALTIME,
            sources,
            MarketQuoteReconciler(max_age=timedelta(seconds=15), price_tolerance_bps=Decimal("20")),
            FixedClock(),
        ),
        repository,
    )


@pytest.mark.asyncio
async def test_service_persists_raw_quote_and_confirmed_reconciliation() -> None:
    runtime = FixtureRuntime(
        ("eastmoney_adapter", "sina_adapter"),
        {
            "eastmoney_adapter": "10.00",
            "sina_adapter": "10.01",
        },
    )
    use_case, repository = service(
        runtime, (source("eastmoney_adapter", "eastmoney"), source("sina_adapter", "sina"))
    )
    result = await use_case.get(INSTRUMENT)
    assert result.reconciliation.status is ReconciliationStatus.CONFIRMED
    assert len(repository.raw) == 2
    assert len(repository.quotes) == 2
    assert len(repository.reconciliations) == 1


@pytest.mark.asyncio
async def test_transport_fallback_and_library_alias_cannot_fabricate_consensus() -> None:
    runtime = FixtureRuntime(
        ("akshare_eastmoney", "efinance_eastmoney"),
        {
            "akshare_eastmoney": "10.00",
            "efinance_eastmoney": "10.00",
        },
    )
    use_case, _ = service(
        runtime,
        (
            source("akshare_eastmoney", "eastmoney"),
            source("efinance_eastmoney", "eastmoney"),
        ),
    )
    result = await use_case.get(INSTRUMENT)
    assert result.reconciliation.status is ReconciliationStatus.DEGRADED
    assert result.reconciliation.contributing_upstream_ids == ("eastmoney",)


@pytest.mark.asyncio
async def test_unknown_instrument_fails_before_provider_invocation() -> None:
    runtime = FixtureRuntime(("eastmoney_adapter",), {"eastmoney_adapter": "10.00"})
    use_case, repository = service(
        runtime, (source("eastmoney_adapter", "eastmoney"),), known=False
    )
    with pytest.raises(ValueError, match="instrument master"):
        await use_case.get(INSTRUMENT)
    assert runtime.calls == 0
    assert not repository.raw


@pytest.mark.asyncio
async def test_restart_retry_is_idempotent() -> None:
    sources = (source("eastmoney_adapter", "eastmoney"), source("sina_adapter", "sina"))
    repository = InMemoryMarketIntelligenceRepository()
    resolver = QuoteInstrumentResolver(KnownInstruments(), EmptyETF())  # type: ignore[arg-type]
    reconciler = MarketQuoteReconciler(
        max_age=timedelta(seconds=15), price_tolerance_bps=Decimal("20")
    )
    for _ in range(2):
        runtime = FixtureRuntime(
            ("eastmoney_adapter", "sina_adapter"),
            {
                "eastmoney_adapter": "10.00",
                "sina_adapter": "10.01",
            },
        )
        use_case = RealtimeMarketQuoteService(
            runtime,
            repository,
            repository,
            resolver,
            MARKET_QUOTE_REALTIME,
            sources,
            reconciler,
            FixedClock(),
        )
        result = await use_case.get(INSTRUMENT)
        assert result.reconciliation.status is ReconciliationStatus.CONFIRMED
    assert len(repository.raw) == 2
    assert len(repository.quotes) == 2
    assert len(repository.reconciliations) == 1
