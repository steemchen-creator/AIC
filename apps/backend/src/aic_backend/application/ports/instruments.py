"""Application-owned instrument master and trading-status contracts."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.persistence import SaveResult
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentTradingStatus,
    Market,
)


@dataclass(frozen=True, slots=True)
class InstrumentCoverageAttempt:
    attempt_id: str
    provider_id: str
    capability: str
    market: Market
    instrument: InstrumentIdentity | None
    interval: DateInterval | None
    requested_at: datetime
    completed_at: datetime
    status: BackfillAttemptStatus
    received_count: int
    persisted_count: int
    already_exists_count: int
    failed_count: int
    error_code: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.attempt_id.strip()
            or not self.provider_id.strip()
            or not self.capability.strip()
        ):
            raise ValueError("attempt identifiers must not be empty")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must include timezone information")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("completed_at must include timezone information")
        if self.completed_at < self.requested_at:
            raise ValueError("completed_at must not precede requested_at")
        if min(
            self.received_count,
            self.persisted_count,
            self.already_exists_count,
            self.failed_count,
        ) < 0:
            raise ValueError("attempt counts must not be negative")


class InstrumentMasterRepository(Protocol):
    async def save(self, value: InstrumentMaster) -> SaveResult: ...
    async def get_instrument(self, identity: InstrumentIdentity) -> InstrumentMaster | None: ...
    async def find_instrument(self, market: Market, symbol: str) -> InstrumentMaster | None: ...
    async def list_instruments(
        self, market: Market | None = None
    ) -> tuple[InstrumentMaster, ...]: ...


class InstrumentTradingStatusRepository(Protocol):
    async def save(self, value: InstrumentTradingStatus) -> SaveResult: ...
    async def get_trading_status(
        self, instrument: InstrumentIdentity, trading_date: date
    ) -> InstrumentTradingStatus | None: ...
    async def list_trading_status(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[InstrumentTradingStatus, ...]: ...


class InstrumentCoverageRepository(Protocol):
    async def record(self, attempt: InstrumentCoverageAttempt) -> None: ...
    async def get_attempts(
        self,
        capability: str,
        market: Market,
        instrument: InstrumentIdentity | None,
        start: date | None,
        end: date | None,
    ) -> tuple[InstrumentCoverageAttempt, ...]: ...


class InstrumentMasterNormalizer(Protocol):
    def normalize(
        self, row: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> InstrumentMaster: ...


class InstrumentTradingStatusNormalizer(Protocol):
    def normalize(
        self, row: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> InstrumentTradingStatus: ...
