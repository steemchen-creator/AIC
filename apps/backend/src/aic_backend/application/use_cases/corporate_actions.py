"""Explicit, resumable adjustment-factor and corporate-action backfills."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast

from aic_backend.application.ports.corporate_actions import (
    AdjustmentFactorNormalizer,
    AdjustmentFactorRepository,
    CorporateActionNormalizer,
    CorporateActionRepository,
)
from aic_backend.application.ports.historical import (
    BackfillAttempt,
    BackfillAttemptStatus,
    BackfillMetadataRepository,
    DateInterval,
)
from aic_backend.application.ports.persistence import PersistenceError, SaveStatus
from aic_backend.application.use_cases.historical_daily_bars import missing_intervals
from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.domain.market_data import DataCapability, InstrumentIdentity, RawObservation
from aic_backend.provider_runtime import (
    Clock,
    IdGenerator,
    ProviderCapability,
    ProviderRequestContext,
    ProviderRuntimePort,
)
from aic_backend.provider_runtime.errors import ProviderRuntimeError


@dataclass(frozen=True, slots=True)
class CorporateDataBackfillResult:
    received: int
    persisted: int
    already_exists: int
    failed: int
    status: BackfillAttemptStatus
    error_code: str | None = None


def _rows(data: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    rows = None if data is None else data.get("rows")
    if not isinstance(rows, (list, tuple)) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("provider response must contain rows")
    return tuple(rows)


def _observation(
    row: Mapping[str, Any],
    provider_id: str,
    capability: DataCapability,
    now: datetime,
    ids: IdGenerator,
) -> RawObservation:
    return RawObservation(
        ids.new_id("observation"),
        provider_id,
        capability,
        now,
        row,
        raw_payload_hash(row),
        {"provider_id": provider_id},
    )


class BackfillAdjustmentFactors:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        capability: ProviderCapability,
        repository: AdjustmentFactorRepository,
        coverage: BackfillMetadataRepository,
        normalizer: AdjustmentFactorNormalizer,
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
    ) -> CorporateDataBackfillResult:
        requested = DateInterval(start, end)
        attempts = await self._coverage.get_attempts(instrument, start, end)
        confirmed = tuple(
            item.interval
            for item in attempts
            if item.capability == self._capability.name
            and item.status is BackfillAttemptStatus.COMPLETED
        )
        total = [0, 0, 0, 0]
        for gap in missing_intervals(requested, confirmed):
            cursor = gap.start
            while cursor <= gap.end:
                chunk = DateInterval(
                    cursor, min(gap.end, cursor + timedelta(days=self._chunk_days - 1))
                )
                result = await self._chunk(instrument, chunk, timeout_ms)
                for index, value in enumerate(
                    (result.received, result.persisted, result.already_exists, result.failed)
                ):
                    total[index] += value
                if result.status is not BackfillAttemptStatus.COMPLETED:
                    return CorporateDataBackfillResult(
                        total[0], total[1], total[2], total[3], result.status, result.error_code
                    )
                cursor = chunk.end + timedelta(days=1)
        return CorporateDataBackfillResult(
            total[0], total[1], total[2], total[3], BackfillAttemptStatus.COMPLETED
        )

    async def _chunk(
        self, instrument: InstrumentIdentity, interval: DateInterval, timeout_ms: int
    ) -> CorporateDataBackfillResult:
        requested_at = self._clock.now()
        provider_id = "unselected"
        received = persisted = existing = failed = 0
        error_code = None
        try:
            response = await self._runtime.execute(
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
            provider_id = response.provider_id
            rows = _rows(response.data)
            received = len(rows)
            for row in rows:
                try:
                    observation = _observation(
                        row,
                        provider_id,
                        DataCapability.ADJUSTMENT_FACTOR,
                        self._clock.now(),
                        self._ids,
                    )
                    value = self._normalizer.normalize(
                        cast(Mapping[str, object], observation.payload),
                        provider_id=provider_id,
                        retrieved_at=self._clock.now(),
                    )
                    if (
                        value.instrument != instrument
                        or not interval.start <= value.trading_date <= interval.end
                    ):
                        raise ValueError("factor row is outside the request")
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
            BackfillAttempt(
                self._ids.new_id("factor_attempt"),
                provider_id,
                self._capability.name,
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
        return CorporateDataBackfillResult(
            received, persisted, existing, failed, status, error_code
        )


class BackfillCorporateActions:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        capability: ProviderCapability,
        repository: CorporateActionRepository,
        coverage: BackfillMetadataRepository,
        normalizer: CorporateActionNormalizer,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._runtime, self._capability, self._repository = runtime, capability, repository
        self._coverage, self._normalizer, self._clock, self._ids = coverage, normalizer, clock, ids

    async def execute(
        self, instrument: InstrumentIdentity, start: date, end: date, *, timeout_ms: int = 5000
    ) -> CorporateDataBackfillResult:
        interval = DateInterval(start, end)
        requested_at = self._clock.now()
        provider_id = "unselected"
        received = persisted = existing = failed = 0
        error_code = None
        try:
            response = await self._runtime.execute(
                ProviderRequestContext(
                    self._ids.new_id("request"),
                    self._capability,
                    timeout_ms,
                    market=instrument.market.value,
                ),
                {
                    "symbol": instrument.symbol,
                    "market": instrument.market.value,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
            )
            provider_id = response.provider_id
            rows = _rows(response.data)
            received = len(rows)
            for row in rows:
                try:
                    observation = _observation(
                        row,
                        provider_id,
                        DataCapability.CORPORATE_ACTION,
                        self._clock.now(),
                        self._ids,
                    )
                    values = self._normalizer.normalize_many(
                        cast(Mapping[str, object], observation.payload),
                        provider_id=provider_id,
                        retrieved_at=self._clock.now(),
                    )
                    for value in values:
                        if (
                            value.instrument != instrument
                            or value.effective_date is None
                            or not start <= value.effective_date <= end
                        ):
                            continue
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
            BackfillAttempt(
                self._ids.new_id("action_attempt"),
                provider_id,
                self._capability.name,
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
        return CorporateDataBackfillResult(
            received, persisted, existing, failed, status, error_code
        )
