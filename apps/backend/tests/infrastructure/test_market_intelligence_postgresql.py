import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.ports.market_intelligence import PersistedMarketQuote
from aic_backend.application.ports.persistence import SaveStatus
from aic_backend.data_foundation.canonical import create_raw_observation
from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.domain.market_data import (
    AuthorityLevel,
    DataCapability,
    InstrumentIdentity,
    InstrumentType,
    Market,
    MarketPulseFamily,
    MarketPulseObservation,
    MarketQuote,
    MarketSeriesIdentity,
    PublicationMode,
    QuoteReconciliation,
    QuoteSessionStatus,
    ReconciliationStatus,
    SourceLineage,
    SourceType,
)
from aic_backend.infrastructure.market_intelligence_persistence import (
    PostgreSQLMarketIntelligenceRepository,
    canonical_market_quotes,
    market_pulse_observations,
    quote_reconciliations,
    raw_observations,
)

NOW = datetime(2026, 9, 21, 7, 0, 10, tzinfo=UTC)
EVENT = NOW - timedelta(seconds=2)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


def migration_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    return environment


def source_lineage(upstream: str = "eastmoney", raw_hash: str = "a" * 64) -> SourceLineage:
    return SourceLineage(
        f"{upstream}_adapter",
        upstream,
        AuthorityLevel.HIGH_QUALITY_PUBLIC,
        SourceType.PUBLIC_MARKET_FEED,
        EVENT,
        NOW,
        NOW,
        raw_hash,
        "quote/v1",
        published_at=EVENT,
        source_uri=f"https://{upstream}.example/quote",
        source_record_id="600000:20260921T150008",
        license_id="TEST-ONLY",
    )


def evidence():
    payload = {"last": Decimal("10.00"), "event_time": EVENT}
    lineage = source_lineage(raw_hash=raw_payload_hash(payload))
    raw = create_raw_observation(
        observation_id="obs-1",
        provider_id="eastmoney_adapter",
        capability=DataCapability.MARKET_QUOTE,
        received_at=NOW,
        payload=payload,
        source_metadata={"request_id": "request-1"},
        lineage=lineage,
    )
    quote = MarketQuote(
        "quote-1",
        INSTRUMENT,
        EVENT,
        NOW,
        NOW,
        Decimal("10"),
        Decimal("9.99"),
        Decimal("10.01"),
        Decimal("9.8"),
        100,
        Decimal("1000"),
        QuoteSessionStatus.OPEN,
        lineage,
    )
    persisted = PersistedMarketQuote(
        raw.observation_id, quote, DataQualityAssessment(95, 100, 100, 100, 75)
    )
    reconciliation = QuoteReconciliation(
        "recon-1",
        INSTRUMENT,
        NOW,
        ReconciliationStatus.DEGRADED,
        (quote.quote_id,),
        (lineage.upstream_source_id,),
        quote.quote_id,
        Decimal("0.5"),
        ("INDEPENDENT_QUORUM_ABSENT",),
        "quote-reconciliation/v1",
    )
    pulse_lineage = source_lineage("official-index")
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
        Decimal("6000.123456789012"),
        EVENT,
        NOW,
        NOW,
        pulse_lineage,
    )
    return raw, persisted, reconciliation, pulse


@pytest.fixture
async def engine() -> AsyncEngine:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=migration_environment(),
    )
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        for table in (
            quote_reconciliations,
            canonical_market_quotes,
            raw_observations,
            market_pulse_observations,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


@pytest.mark.asyncio
async def test_postgresql_round_trip_restart_and_idempotency(engine: AsyncEngine) -> None:
    raw, quote, reconciliation, pulse = evidence()
    repository = PostgreSQLMarketIntelligenceRepository(engine)
    assert (await repository.save_raw(raw)).status is SaveStatus.INSERTED
    assert (await repository.save_quote(quote)).status is SaveStatus.INSERTED
    assert (await repository.save_reconciliation(reconciliation)).status is SaveStatus.INSERTED
    assert (await repository.save_pulse(pulse)).status is SaveStatus.INSERTED

    restarted = PostgreSQLMarketIntelligenceRepository(engine)
    assert (await restarted.save_raw(raw)).status is SaveStatus.ALREADY_EXISTS
    assert (await restarted.save_quote(quote)).status is SaveStatus.ALREADY_EXISTS
    assert (await restarted.save_reconciliation(reconciliation)).status is SaveStatus.ALREADY_EXISTS
    assert (await restarted.save_pulse(pulse)).status is SaveStatus.ALREADY_EXISTS
    assert await restarted.get_raw(raw.observation_id) == raw
    assert await restarted.get_quote(quote.quote.quote_id) == quote
    assert await restarted.get_reconciliation(reconciliation.reconciliation_id) == reconciliation
    assert await restarted.list_pulse("sp500", EVENT, NOW) == (pulse,)
    async with engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(raw_observations)) == 1
        quote_count = await connection.scalar(
            select(func.count()).select_from(canonical_market_quotes)
        )
        assert quote_count == 1


def test_spec011_checkpoint_a_migration_round_trip() -> None:
    environment = migration_environment()
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260910_0015"],
        check=True,
        env=environment,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )
