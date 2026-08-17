"""Application-owned trading-calendar persistence contracts."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.persistence import SaveResult
from aic_backend.domain.market_data import Market, TradingSessionDay


@dataclass(frozen=True, slots=True)
class CalendarCoverageAttempt:
    attempt_id: str
    provider_id: str
    market: Market
    interval: DateInterval
    requested_at: datetime
    completed_at: datetime
    status: BackfillAttemptStatus
    received_count: int
    persisted_count: int
    already_exists_count: int
    failed_count: int
    error_code: str | None = None


class TradingCalendarRepository(Protocol):
    async def save(self, day: TradingSessionDay) -> SaveResult: ...
    async def get_day(self, market: Market, trading_date: date) -> TradingSessionDay | None: ...
    async def list_days(
        self, market: Market, start: date, end: date
    ) -> tuple[TradingSessionDay, ...]: ...


class CalendarCoverageRepository(Protocol):
    async def record(self, attempt: CalendarCoverageAttempt) -> None: ...
    async def get_attempts(
        self, market: Market, start: date, end: date
    ) -> tuple[CalendarCoverageAttempt, ...]: ...


class CalendarNormalizer(Protocol):
    def normalize(
        self,
        row: Mapping[str, object],
        *,
        provider_id: str,
        retrieved_at: datetime,
    ) -> TradingSessionDay: ...
