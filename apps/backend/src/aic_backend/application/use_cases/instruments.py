"""Instrument master queries, sync, and conservative trading-status backfill."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from aic_backend.application.ports.historical import BackfillAttemptStatus, DateInterval
from aic_backend.application.ports.instruments import (
    InstrumentCoverageAttempt,
    InstrumentCoverageRepository,
    InstrumentMasterNormalizer,
    InstrumentMasterRepository,
    InstrumentTradingStatusNormalizer,
    InstrumentTradingStatusRepository,
)
from aic_backend.application.ports.persistence import PersistenceError, SaveStatus
from aic_backend.application.use_cases.historical_daily_bars import missing_intervals
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentTradingStatus,
    Market,
)
from aic_backend.provider_runtime import (
    Clock,
    IdGenerator,
    ProviderCapability,
    ProviderRequestContext,
    ProviderRuntimePort,
)
from aic_backend.provider_runtime.errors import ProviderRuntimeError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InstrumentSyncResult:
    received: int
    persisted: int
    already_exists: int
    failed: int
    status: BackfillAttemptStatus
    error_code: str | None = None


class InstrumentService:
    def __init__(
        self,
        masters: InstrumentMasterRepository,
        statuses: InstrumentTradingStatusRepository,
        coverage: InstrumentCoverageRepository,
        status_capability: ProviderCapability,
    ) -> None:
        self._masters = masters
        self._statuses = statuses
        self._coverage = coverage
        self._status_capability = status_capability

    async def get_instrument(self, identity: InstrumentIdentity) -> InstrumentMaster | None:
        return await self._masters.get_instrument(identity)

    async def status_on(
        self, identity: InstrumentIdentity, value: date
    ) -> InstrumentTradingStatus | None:
        return await self._statuses.get_trading_status(identity, value)

    async def status_coverage_complete(
        self, identity: InstrumentIdentity, start: date, end: date
    ) -> bool:
        requested = DateInterval(start, end)
        attempts = await self._coverage.get_attempts(
            self._status_capability.name, identity.market, identity, start, end
        )
        confirmed = tuple(
            item.interval
            for item in attempts
            if item.status is BackfillAttemptStatus.COMPLETED and item.interval is not None
        )
        return not missing_intervals(requested, confirmed)


class SyncInstrumentMaster:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        capability: ProviderCapability,
        repository: InstrumentMasterRepository,
        coverage: InstrumentCoverageRepository,
        normalizer: InstrumentMasterNormalizer,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._runtime, self._capability, self._repository = runtime, capability, repository
        self._coverage, self._normalizer, self._clock, self._ids = coverage, normalizer, clock, ids

    async def execute(
        self, market: Market, *, listing_status: str = "L", timeout_ms: int = 5000
    ) -> InstrumentSyncResult:
        requested_at = self._clock.now()
        provider_id = "unselected"
        received = persisted = existing = failed = 0
        error_code: str | None = None
        try:
            result = await self._runtime.execute(
                ProviderRequestContext(
                    self._ids.new_id("request"), self._capability, timeout_ms, market=market.value
                ),
                {
                    "exchange": "SSE" if market is Market.CN_SSE else "SZSE",
                    "list_status": listing_status,
                },
            )
            provider_id = result.provider_id
            rows = _rows(result.data, "instrument master")
            received = len(rows)
            for row in rows:
                try:
                    value = self._normalizer.normalize(
                        row, provider_id=provider_id, retrieved_at=self._clock.now()
                    )
                    if value.instrument.market is not market:
                        raise ValueError("instrument row market does not match request")
                    saved = await self._repository.save(value)
                    persisted += saved.status is SaveStatus.INSERTED
                    existing += saved.status is SaveStatus.ALREADY_EXISTS
                except (ValueError, PersistenceError) as error:
                    failed += 1
                    error_code = error_code or str(getattr(error, "code", type(error).__name__))
            status = (
                BackfillAttemptStatus.COMPLETED if failed == 0 else BackfillAttemptStatus.PARTIAL
            )
        except (ProviderRuntimeError, PersistenceError, ValueError) as error:
            status = BackfillAttemptStatus.FAILED
            error_code = str(getattr(error, "code", type(error).__name__))
        await self._coverage.record(
            InstrumentCoverageAttempt(
                self._ids.new_id("instrument_attempt"),
                provider_id,
                self._capability.name,
                market,
                None,
                None,
                requested_at,
                self._clock.now(),
                status,
                received,
                persisted,
                existing,
                failed,
                error_code,
            )
        )
        logger.info(
            "instrument master sync completed",
            extra={
                "provider_id": provider_id,
                "market": market.value,
                "status": status.value,
                "received_count": received,
                "persisted_count": persisted,
                "failed_count": failed,
            },
        )
        return InstrumentSyncResult(received, persisted, existing, failed, status, error_code)


class BackfillInstrumentTradingStatus:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        capability: ProviderCapability,
        repository: InstrumentTradingStatusRepository,
        coverage: InstrumentCoverageRepository,
        normalizer: InstrumentTradingStatusNormalizer,
        clock: Clock,
        ids: IdGenerator,
        *,
        chunk_days: int = 365,
    ) -> None:
        if chunk_days <= 0:
            raise ValueError("chunk_days must be positive")
        self._runtime, self._capability, self._repository = runtime, capability, repository
        self._coverage, self._normalizer, self._clock, self._ids = coverage, normalizer, clock, ids
        self._chunk_days = chunk_days

    async def execute(
        self, instrument: InstrumentIdentity, start: date, end: date, *, timeout_ms: int = 5000
    ) -> InstrumentSyncResult:
        requested = DateInterval(start, end)
        attempts = await self._coverage.get_attempts(
            self._capability.name, instrument.market, instrument, start, end
        )
        confirmed = tuple(
            item.interval
            for item in attempts
            if item.status is BackfillAttemptStatus.COMPLETED and item.interval is not None
        )
        totals = [0, 0, 0, 0]
        status = BackfillAttemptStatus.COMPLETED
        error_code: str | None = None
        for gap in missing_intervals(requested, confirmed):
            cursor = gap.start
            while cursor <= gap.end:
                chunk_end = min(
                    gap.end, cursor.fromordinal(cursor.toordinal() + self._chunk_days - 1)
                )
                result = await self._chunk(instrument, DateInterval(cursor, chunk_end), timeout_ms)
                for index, value in enumerate(
                    (result.received, result.persisted, result.already_exists, result.failed)
                ):
                    totals[index] += value
                status, error_code = result.status, result.error_code
                if status is not BackfillAttemptStatus.COMPLETED:
                    return InstrumentSyncResult(
                        totals[0], totals[1], totals[2], totals[3], status, error_code
                    )
                cursor = chunk_end.fromordinal(chunk_end.toordinal() + 1)
        return InstrumentSyncResult(totals[0], totals[1], totals[2], totals[3], status, error_code)

    async def _chunk(
        self, instrument: InstrumentIdentity, interval: DateInterval, timeout_ms: int
    ) -> InstrumentSyncResult:
        requested_at = self._clock.now()
        provider_id = "unselected"
        received = persisted = existing = failed = 0
        error_code: str | None = None
        try:
            result = await self._runtime.execute(
                ProviderRequestContext(
                    self._ids.new_id("request"),
                    self._capability,
                    timeout_ms,
                    market=instrument.market.value,
                ),
                {
                    "symbol": instrument.symbol,
                    "market": instrument.market.value,
                    "start_date": interval.start.isoformat(),
                    "end_date": interval.end.isoformat(),
                },
            )
            provider_id = result.provider_id
            rows = _rows(result.data, "instrument trading status")
            received = len(rows)
            for row in rows:
                try:
                    value = self._normalizer.normalize(
                        row, provider_id=provider_id, retrieved_at=self._clock.now()
                    )
                    if (
                        value.instrument != instrument
                        or not interval.start <= value.trading_date <= interval.end
                    ):
                        raise ValueError("trading-status row is outside the request")
                    saved = await self._repository.save(value)
                    persisted += saved.status is SaveStatus.INSERTED
                    existing += saved.status is SaveStatus.ALREADY_EXISTS
                except (ValueError, PersistenceError) as error:
                    failed += 1
                    error_code = error_code or str(getattr(error, "code", type(error).__name__))
            status = (
                BackfillAttemptStatus.COMPLETED if failed == 0 else BackfillAttemptStatus.PARTIAL
            )
        except (ProviderRuntimeError, PersistenceError, ValueError) as error:
            status = BackfillAttemptStatus.FAILED
            error_code = str(getattr(error, "code", type(error).__name__))
        await self._coverage.record(
            InstrumentCoverageAttempt(
                self._ids.new_id("status_attempt"),
                provider_id,
                self._capability.name,
                instrument.market,
                instrument,
                interval,
                requested_at,
                self._clock.now(),
                status,
                received,
                persisted,
                existing,
                failed,
                error_code,
            )
        )
        logger.info(
            "instrument trading-status backfill chunk completed",
            extra={
                "provider_id": provider_id,
                "market": instrument.market.value,
                "symbol": instrument.symbol,
                "requested_start": interval.start.isoformat(),
                "requested_end": interval.end.isoformat(),
                "status": status.value,
                "received_count": received,
                "persisted_count": persisted,
                "failed_count": failed,
            },
        )
        return InstrumentSyncResult(received, persisted, existing, failed, status, error_code)


def _rows(data: Mapping[str, Any] | None, label: str) -> tuple[Mapping[str, Any], ...]:
    rows = None if data is None else data.get("rows")
    if not isinstance(rows, (list, tuple)) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"provider {label} response must contain rows")
    return tuple(rows)
