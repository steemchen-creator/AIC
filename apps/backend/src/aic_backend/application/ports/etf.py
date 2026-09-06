"""Application-owned ETF and index persistence contracts."""

from datetime import date
from typing import Protocol

from aic_backend.application.ports.persistence import SaveResult
from aic_backend.domain.market_data import (
    ETFInstrumentProfile,
    ETFTracksIndex,
    ETFValuationSnapshot,
    IndexReference,
    InstrumentExecutionProfile,
    InstrumentIdentity,
)


class ETFDataRepository(Protocol):
    async def save_etf_profile(self, value: ETFInstrumentProfile) -> SaveResult: ...

    async def get_etf_profile(
        self, instrument: InstrumentIdentity
    ) -> ETFInstrumentProfile | None: ...

    async def save_index_reference(self, value: IndexReference) -> SaveResult: ...

    async def get_index_reference(
        self, identity: InstrumentIdentity
    ) -> IndexReference | None: ...

    async def save_relationship(self, value: ETFTracksIndex) -> SaveResult: ...

    async def list_relationships(
        self, instrument: InstrumentIdentity
    ) -> tuple[ETFTracksIndex, ...]: ...

    async def save_valuation(self, value: ETFValuationSnapshot) -> SaveResult: ...

    async def list_valuations(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[ETFValuationSnapshot, ...]: ...

    async def save_execution_profile(self, value: InstrumentExecutionProfile) -> SaveResult: ...

    async def list_execution_profiles(
        self, instrument: InstrumentIdentity
    ) -> tuple[InstrumentExecutionProfile, ...]: ...
