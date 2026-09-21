"""Application orchestration for auditable, independently reconciled quotes."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from aic_backend.application.ports.etf import ETFDataRepository
from aic_backend.application.ports.instruments import InstrumentMasterRepository
from aic_backend.application.ports.market_intelligence import (
    MarketQuoteRepository,
    PersistedMarketQuote,
    RawObservationRepository,
)
from aic_backend.data_foundation.canonical import create_raw_observation
from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.data_foundation.market_quotes import (
    MarketQuoteNormalizer,
    MarketQuoteQualityAssessor,
    MarketQuoteReconciler,
    MarketQuoteValidator,
)
from aic_backend.data_foundation.quality import QualityContext
from aic_backend.domain.market_data import (
    AuthorityLevel,
    DataCapability,
    InstrumentIdentity,
    InstrumentType,
    MarketQuote,
    QuoteReconciliation,
    SourceLineage,
    SourceType,
)
from aic_backend.provider_runtime import (
    ProviderCapability,
    ProviderRequestContext,
    ProviderRuntimePort,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class QuoteSourceConfig:
    adapter_id: str
    upstream_source_id: str
    authority_level: AuthorityLevel
    source_type: SourceType
    source_uri: str
    license_id: str | None = None

    def __post_init__(self) -> None:
        if not self.adapter_id.strip() or not self.upstream_source_id.strip():
            raise ValueError("source identities must not be empty")


@dataclass(frozen=True, slots=True)
class RealtimeQuoteResult:
    quotes: tuple[MarketQuote, ...]
    reconciliation: QuoteReconciliation
    failed_adapter_ids: tuple[str, ...]


class QuoteInstrumentResolver:
    def __init__(
        self, instruments: InstrumentMasterRepository, etf_data: ETFDataRepository
    ) -> None:
        self._instruments = instruments
        self._etf_data = etf_data

    async def require_known(self, identity: InstrumentIdentity) -> None:
        if identity.instrument_type is InstrumentType.INDEX:
            known = await self._etf_data.get_index_reference(identity) is not None
        elif identity.instrument_type is InstrumentType.ETF:
            known = await self._etf_data.get_etf_profile(identity) is not None
        else:
            known = await self._instruments.get_instrument(identity) is not None
        if not known:
            raise ValueError("quote instrument is absent from the authoritative instrument master")


class RealtimeMarketQuoteService:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        raw_repository: RawObservationRepository,
        quote_repository: MarketQuoteRepository,
        resolver: QuoteInstrumentResolver,
        capability: ProviderCapability,
        sources: tuple[QuoteSourceConfig, ...],
        reconciler: MarketQuoteReconciler,
        clock: Clock,
        *,
        timeout_ms: int = 2000,
    ) -> None:
        self._runtime = runtime
        self._raw_repository = raw_repository
        self._quote_repository = quote_repository
        self._resolver = resolver
        self._capability = capability
        self._sources = sources
        self._source_by_adapter = {source.adapter_id: source for source in sources}
        if len(self._source_by_adapter) != len(sources):
            raise ValueError("adapter identities must be unique")
        self._reconciler = reconciler
        self._clock = clock
        self._timeout_ms = timeout_ms
        self._normalizer = MarketQuoteNormalizer()
        self._validator = MarketQuoteValidator()
        self._quality = MarketQuoteQualityAssessor()

    async def get(self, instrument: InstrumentIdentity) -> RealtimeQuoteResult:
        await self._resolver.require_known(instrument)
        quotes: dict[str, MarketQuote] = {}
        failed: set[str] = set()
        for sequence, requested_source in enumerate(self._sources, start=1):
            now = self._clock.now().astimezone(UTC)
            request_seed = f"{instrument.canonical_key}:{now.isoformat()}:{sequence}"
            request_id = f"quote_{hashlib.sha256(request_seed.encode()).hexdigest()}"
            context = ProviderRequestContext(
                request_id,
                self._capability,
                self._timeout_ms,
                preferred_provider_ids=(requested_source.adapter_id,),
                symbol=instrument.symbol,
                market=instrument.market.value,
            )
            result = await self._runtime.execute(
                context,
                {
                    "market": instrument.market.value,
                    "symbol": instrument.symbol,
                    "instrument_type": instrument.instrument_type.value,
                },
            )
            if not result.success or result.data is None:
                failed.add(requested_source.adapter_id)
                continue
            actual_source = self._source_by_adapter.get(result.provider_id)
            if actual_source is None:
                raise ValueError("provider runtime returned an unconfigured quote adapter")
            raw_hash = raw_payload_hash(result.data)
            event_value = result.data.get("event_time")
            if not isinstance(event_value, str):
                raise ValueError("quote provider omitted event_time")
            event_time = datetime.fromisoformat(event_value)
            if event_time.tzinfo is None or event_time.utcoffset() is None:
                raise ValueError("quote provider event_time requires timezone")
            observed_at = result.finished_at.astimezone(UTC)
            ingested_at = max(observed_at, self._clock.now().astimezone(UTC))
            lineage = SourceLineage(
                result.provider_id,
                actual_source.upstream_source_id,
                actual_source.authority_level,
                actual_source.source_type,
                event_time,
                observed_at,
                ingested_at,
                raw_hash,
                self._normalizer.transformation_version,
                published_at=event_time,
                source_uri=actual_source.source_uri,
                source_record_id=f"{instrument.canonical_key}:{event_time.isoformat()}",
                license_id=actual_source.license_id,
            )
            observation_seed = (
                f"{result.provider_id}:{actual_source.upstream_source_id}:{raw_hash}"
            )
            observation_id = f"obs_{hashlib.sha256(observation_seed.encode()).hexdigest()}"
            observation = create_raw_observation(
                observation_id=observation_id,
                provider_id=result.provider_id,
                capability=DataCapability.MARKET_QUOTE,
                received_at=ingested_at,
                payload=result.data,
                source_metadata={
                    "request_id": result.request_id,
                    "failover_count": result.failover_count,
                },
                lineage=lineage,
            )
            await self._raw_repository.save_raw(observation)
            quote = self._normalizer.normalize(observation)
            validation = self._validator.validate(quote)
            if not validation.valid:
                raise ValueError("normalized quote failed validation")
            assessment = self._quality.assess(
                quote,
                reference_time=ingested_at,
                context=QualityContext(),
                validation_result=validation,
            )
            await self._quote_repository.save_quote(
                PersistedMarketQuote(observation_id, quote, assessment)
            )
            quotes[quote.quote_id] = quote
        as_of = self._clock.now().astimezone(UTC)
        reconciliation = self._reconciler.reconcile(instrument, tuple(quotes.values()), as_of)
        await self._quote_repository.save_reconciliation(reconciliation)
        return RealtimeQuoteResult(
            tuple(sorted(quotes.values(), key=lambda item: item.quote_id)),
            reconciliation,
            tuple(sorted(failed)),
        )
