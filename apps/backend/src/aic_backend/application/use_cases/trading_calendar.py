"""Trading-calendar queries and explicit Provider Runtime backfill."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from aic_backend.application.ports.calendar import (
    CalendarCoverageAttempt,
    CalendarCoverageRepository,
    CalendarNormalizer,
    TradingCalendarRepository,
)
from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.persistence import (
    PersistenceError,
    PersistenceErrorCode,
    SaveStatus,
)
from aic_backend.application.use_cases.backfill_daily_bars import chunk_intervals
from aic_backend.application.use_cases.historical_daily_bars import missing_intervals
from aic_backend.domain.market_data import Market, TradingSessionDay
from aic_backend.provider_runtime import (
    Clock,
    IdGenerator,
    ProviderCapability,
    ProviderRequestContext,
    ProviderRuntimePort,
)
from aic_backend.provider_runtime.errors import ProviderRuntimeError


class TradingCalendarService:
    def __init__(
        self, repository: TradingCalendarRepository, coverage: CalendarCoverageRepository
    ) -> None:
        self._repository, self._coverage = repository, coverage

    async def get_day(self, market: Market, value: date) -> TradingSessionDay | None:
        return await self._repository.get_day(market, value)

    async def is_trading_day(self, market: Market, value: date) -> bool | None:
        day = await self.get_day(market, value)
        return None if day is None else day.is_open

    async def list_trading_days(
        self, market: Market, start: date, end: date
    ) -> tuple[TradingSessionDay, ...]:
        return tuple(
            item for item in await self._repository.list_days(market, start, end) if item.is_open
        )

    async def previous_trading_day(self, market: Market, value: date) -> date | None:
        days = await self.list_trading_days(
            market, date.min, value.fromordinal(value.toordinal() - 1)
        )
        return days[-1].trading_date if days else None

    async def next_trading_day(self, market: Market, value: date) -> date | None:
        days = await self.list_trading_days(
            market, value.fromordinal(value.toordinal() + 1), date.max
        )
        return days[0].trading_date if days else None

    async def confirmed_intervals(
        self, market: Market, start: date, end: date
    ) -> tuple[DateInterval, ...]:
        attempts = await self._coverage.get_attempts(market, start, end)
        return tuple(
            item.interval for item in attempts if item.status is BackfillAttemptStatus.COMPLETED
        )


@dataclass(frozen=True, slots=True)
class CalendarBackfillResult:
    received: int
    persisted: int
    already_exists: int
    failed: int
    status: BackfillAttemptStatus
    error_code: str | None = None


class BackfillTradingCalendar:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        capability: ProviderCapability,
        repository: TradingCalendarRepository,
        coverage: CalendarCoverageRepository,
        normalizer: CalendarNormalizer,
        clock: Clock,
        ids: IdGenerator,
        *,
        chunk_days: int = 365,
    ) -> None:
        self._runtime, self._capability, self._repository = runtime, capability, repository
        self._coverage, self._normalizer, self._clock, self._ids = coverage, normalizer, clock, ids
        if chunk_days <= 0:
            raise ValueError("chunk_days must be positive")
        self._chunk_days = chunk_days

    async def execute(
        self, market: Market, start: date, end: date, *, timeout_ms: int = 5000
    ) -> CalendarBackfillResult:
        requested = DateInterval(start, end)
        attempts = await self._coverage.get_attempts(market, start, end)
        confirmed = tuple(
            item.interval for item in attempts if item.status is BackfillAttemptStatus.COMPLETED
        )
        chunks = chunk_intervals(missing_intervals(requested, confirmed), self._chunk_days)
        totals = [0, 0, 0, 0]
        status = BackfillAttemptStatus.COMPLETED
        error_code: str | None = None
        for interval in chunks:
            result = await self._execute_chunk(market, interval, timeout_ms)
            totals[0] += result.received
            totals[1] += result.persisted
            totals[2] += result.already_exists
            totals[3] += result.failed
            status, error_code = result.status, result.error_code
            if status is not BackfillAttemptStatus.COMPLETED:
                break
        return CalendarBackfillResult(
            totals[0], totals[1], totals[2], totals[3], status, error_code
        )

    async def _execute_chunk(
        self, market: Market, interval: DateInterval, timeout_ms: int
    ) -> CalendarBackfillResult:
        requested_at = self._clock.now()
        received = persisted = existing = failed = 0
        provider_id = "unselected"
        error_code: str | None = None
        try:
            result = await self._runtime.execute(
                ProviderRequestContext(
                    self._ids.new_id("request"), self._capability, timeout_ms, market=market.value
                ),
                {
                    "exchange": "SSE" if market is Market.CN_SSE else "SZSE",
                    "start_date": interval.start.isoformat(),
                    "end_date": interval.end.isoformat(),
                },
            )
            provider_id = result.provider_id
            rows = self._rows(result.data)
            received = len(rows)
            for row in rows:
                try:
                    day = self._normalizer.normalize(
                        row, provider_id=provider_id, retrieved_at=self._clock.now()
                    )
                    saved = await self._repository.save(day)
                    persisted += saved.status is SaveStatus.INSERTED
                    existing += saved.status is SaveStatus.ALREADY_EXISTS
                except (ValueError, PersistenceError) as error:
                    failed += 1
                    if (
                        isinstance(error, PersistenceError)
                        and error.code is not PersistenceErrorCode.IDENTITY_CONFLICT
                    ):
                        raise
            status = (
                BackfillAttemptStatus.COMPLETED if failed == 0 else BackfillAttemptStatus.PARTIAL
            )
        except (ProviderRuntimeError, PersistenceError, ValueError) as error:
            status = BackfillAttemptStatus.FAILED
            error_code = getattr(error, "code", type(error).__name__)
        await self._coverage.record(
            CalendarCoverageAttempt(
                self._ids.new_id("calendar_attempt"),
                provider_id,
                market,
                interval,
                requested_at,
                self._clock.now(),
                status,
                received,
                persisted,
                existing,
                failed,
                str(error_code) if error_code else None,
            )
        )
        return CalendarBackfillResult(
            received, persisted, existing, failed, status, str(error_code) if error_code else None
        )

    @staticmethod
    def _rows(data: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
        rows = None if data is None else data.get("rows")
        if not isinstance(rows, (list, tuple)) or any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("provider calendar response must contain rows")
        return tuple(rows)
