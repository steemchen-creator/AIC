"""Durable macro acquisition orchestration over the existing Provider Runtime."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from aic_backend.application.ports.evidence import (
    AcquisitionPlanRepository,
    MacroObservationRepository,
)
from aic_backend.application.ports.market_intelligence import RawObservationRepository
from aic_backend.data_foundation.canonical import create_raw_observation
from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.data_foundation.macro import MacroNormalizer
from aic_backend.domain.evidence import (
    AcquisitionCadenceKind,
    AcquisitionClaim,
    AcquisitionPlan,
    MacroObservation,
)
from aic_backend.domain.market_data import AuthorityLevel, DataCapability, SourceLineage, SourceType
from aic_backend.provider_runtime import (
    ProviderCapability,
    ProviderRequestContext,
    ProviderRuntimePort,
)
from aic_backend.provider_runtime.errors import FailoverError, ProviderRuntimeError


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class MacroAcquisitionTarget:
    plan: AcquisitionPlan
    series_id: str
    source_agency_id: str
    geography: str
    next_release_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MacroAcquisitionResult:
    claim: AcquisitionClaim
    observations: tuple[MacroObservation, ...]
    cursor: str | None


class MacroAcquisitionService:
    def __init__(
        self,
        runtime: ProviderRuntimePort,
        raw_repository: RawObservationRepository,
        macro_repository: MacroObservationRepository,
        acquisition_repository: AcquisitionPlanRepository,
        capability: ProviderCapability,
        normalizer: MacroNormalizer,
        clock: Clock,
        *,
        lease_for: timedelta = timedelta(minutes=2),
        timeout_ms: int = 5000,
    ) -> None:
        self._runtime, self._raw, self._macro = runtime, raw_repository, macro_repository
        self._acquisition, self._capability, self._normalizer = (
            acquisition_repository,
            capability,
            normalizer,
        )
        self._clock, self._lease_for, self._timeout_ms = clock, lease_for, timeout_ms

    async def run_once(
        self, target: MacroAcquisitionTarget, worker_id: str
    ) -> MacroAcquisitionResult | None:
        now = self._clock.now().astimezone(UTC)
        claim = await self._acquisition.claim_due(
            target.plan.plan_id, worker_id, now, self._lease_for
        )
        if claim is None:
            return None
        checkpoint = await self._acquisition.get_checkpoint(target.plan.plan_id)
        if checkpoint is None:
            raise RuntimeError("claimed acquisition checkpoint disappeared")
        request_id = (
            "macro_"
            + hashlib.sha256(f"{target.plan.plan_id}:{claim.fencing_token}".encode()).hexdigest()
        )
        request_watermark = (
            None if checkpoint.watermark is None else checkpoint.watermark - target.plan.overlap
        )
        try:
            result = await self._runtime.execute(
                ProviderRequestContext(
                    request_id,
                    self._capability,
                    self._timeout_ms,
                    preferred_provider_ids=target.plan.preferred_provider_ids,
                ),
                {
                    "series_id": target.series_id,
                    "source_agency_id": target.source_agency_id,
                    "geography": target.geography,
                    "cursor": checkpoint.cursor,
                    "watermark": (
                        None if request_watermark is None else request_watermark.isoformat()
                    ),
                    "overlap_seconds": int(target.plan.overlap.total_seconds()),
                },
            )
            if not result.success or result.data is None:
                raise RuntimeError("macro provider invocation failed")
            observed_at = result.finished_at.astimezone(UTC)
            ingested_at = max(observed_at, self._clock.now().astimezone(UTC))
            completed_at = ingested_at
            raw_hash = raw_payload_hash(result.data)
            raw_id = (
                "obs_"
                + hashlib.sha256(
                    f"{result.provider_id}:{target.series_id}:{raw_hash}".encode()
                ).hexdigest()
            )
            existing_raw = await self._raw.get_raw(raw_id)
            if existing_raw is None:
                published = observed_at
                lineage = SourceLineage(
                    result.provider_id,
                    "FRED_ALFRED",
                    AuthorityLevel.PRIMARY,
                    SourceType.OFFICIAL_API,
                    published,
                    observed_at,
                    ingested_at,
                    raw_hash,
                    self._normalizer.transformation_version,
                    published_at=published,
                    source_uri="https://api.stlouisfed.org/fred/series/observations",
                    source_record_id=target.series_id,
                )
                raw = create_raw_observation(
                    observation_id=raw_id,
                    provider_id=result.provider_id,
                    capability=DataCapability.MACRO_OBSERVATION,
                    received_at=ingested_at,
                    payload=result.data,
                    source_metadata={
                        "request_id": result.request_id,
                        "failover_count": result.failover_count,
                    },
                    lineage=lineage,
                )
                await self._raw.save_raw(raw)
            else:
                if existing_raw.lineage is None:
                    raise RuntimeError("stored macro raw evidence has no lineage")
                observed_at = existing_raw.lineage.observed_at
                ingested_at = existing_raw.lineage.ingested_at
            series, observations = self._normalizer.normalize_fred(
                result.data,
                adapter_id=result.provider_id,
                observed_at=observed_at,
                ingested_at=ingested_at,
                raw_hash=raw_hash,
            )
            await self._macro.save_series(series)
            for observation in observations:
                await self._macro.save_macro(raw_id, observation)
            persisted_id = observations[-1].observation_id if observations else raw_id
            cursor_value = result.data.get("next_cursor")
            cursor = None if cursor_value is None else str(cursor_value)
            candidate_watermark = max(
                (item.release_at for item in observations), default=checkpoint.watermark
            )
            watermark = checkpoint.watermark if cursor is not None else candidate_watermark
            await self._acquisition.complete_claim(
                claim,
                completed_at=completed_at,
                persisted_id=persisted_id,
                cursor=cursor,
                watermark=watermark,
                next_due_at=self._next_due_at(target, completed_at),
            )
            return MacroAcquisitionResult(claim, observations, cursor)
        except Exception as error:
            failed_at = self._clock.now().astimezone(UTC)
            root_error = error.last_error if isinstance(error, FailoverError) else error
            rate_limited = (
                isinstance(root_error, ProviderRuntimeError)
                and root_error.error_code == "PROVIDER_RATE_LIMITED"
            )
            delay_seconds = min(30 * (2**checkpoint.consecutive_failures), 1800)
            rate_limit_reset_at = failed_at + timedelta(minutes=5) if rate_limited else None
            await self._acquisition.fail_claim(
                claim,
                failed_at=failed_at,
                retry_not_before=rate_limit_reset_at
                or failed_at + timedelta(seconds=delay_seconds),
                rate_limit_reset_at=rate_limit_reset_at,
            )
            raise

    @staticmethod
    def _next_due_at(target: MacroAcquisitionTarget, completed_at: datetime) -> datetime:
        plan = target.plan
        release_at = target.next_release_at
        if plan.cadence_kind is not AcquisitionCadenceKind.RELEASE_WINDOW or release_at is None:
            return completed_at + plan.interval
        release_at = release_at.astimezone(UTC)
        window_start = release_at - plan.release_window_before
        window_end = release_at + plan.release_window_after
        if completed_at < window_start:
            return min(completed_at + plan.interval, window_start)
        if completed_at <= window_end:
            return min(completed_at + plan.release_window_interval, window_end + plan.interval)
        return completed_at + plan.interval
