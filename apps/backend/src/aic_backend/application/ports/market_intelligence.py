"""Application-owned persistence contracts for SPEC-011 Checkpoint A."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aic_backend.application.ports.persistence import SaveResult
from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    MarketPulseObservation,
    MarketQuote,
    QuoteReconciliation,
    RawObservation,
)


@dataclass(frozen=True, slots=True)
class PersistedMarketQuote:
    observation_id: str
    quote: MarketQuote
    quality: DataQualityAssessment


class RawObservationRepository(Protocol):
    async def save_raw(self, value: RawObservation) -> SaveResult: ...
    async def get_raw(self, observation_id: str) -> RawObservation | None: ...


class MarketQuoteRepository(Protocol):
    async def save_quote(self, value: PersistedMarketQuote) -> SaveResult: ...
    async def get_quote(self, quote_id: str) -> PersistedMarketQuote | None: ...
    async def list_quotes(
        self, instrument: InstrumentIdentity, start: datetime, end: datetime
    ) -> tuple[PersistedMarketQuote, ...]: ...
    async def save_reconciliation(self, value: QuoteReconciliation) -> SaveResult: ...
    async def get_reconciliation(self, reconciliation_id: str) -> QuoteReconciliation | None: ...


class MarketPulseRepository(Protocol):
    async def save_pulse(self, value: MarketPulseObservation) -> SaveResult: ...
    async def list_pulse(
        self, series_id: str, start: datetime, end: datetime
    ) -> tuple[MarketPulseObservation, ...]: ...
