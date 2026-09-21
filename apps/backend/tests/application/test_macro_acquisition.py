from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aic_backend.application.acquisition import MacroAcquisitionService, MacroAcquisitionTarget
from aic_backend.data_foundation.macro import MacroNormalizer
from aic_backend.domain.evidence import AcquisitionCadenceKind, AcquisitionPlan
from aic_backend.infrastructure.evidence_persistence import InMemoryEvidenceRepository
from aic_backend.infrastructure.market_intelligence_persistence import (
    InMemoryMarketIntelligenceRepository,
)
from aic_backend.provider_runtime import (
    ProviderCapability,
    ProviderInvocationResult,
    ProviderRequestContext,
)
from aic_backend.provider_runtime.errors import ProviderRateLimitedError
from aic_backend.providers.fred import MACRO_VINTAGE_READ

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value


class Runtime:
    async def execute(
        self, context: ProviderRequestContext, payload: Mapping[str, Any]
    ) -> ProviderInvocationResult:
        del payload
        data = {
            "series": {
                "series_id": "PAYEMS",
                "title": "Payrolls",
                "geography": "US",
                "source_agency_id": "BLS",
                "unit": "Thousands",
                "frequency": "M",
                "seasonal_adjustment": "SA",
            },
            "observations": [
                {
                    "date": "2026-08-01",
                    "value": "160000",
                    "realtime_start": "2026-09-04",
                    "realtime_end": "9999-12-31",
                    "release_at": "2026-09-04",
                }
            ],
            "next_cursor": "1000",
        }
        return ProviderInvocationResult(
            context.request_id,
            "fred_official",
            True,
            data,
            None,
            1.0,
            NOW,
            NOW,
        )


class RateLimitedRuntime:
    async def execute(
        self, context: ProviderRequestContext, payload: Mapping[str, Any]
    ) -> ProviderInvocationResult:
        del context, payload
        raise ProviderRateLimitedError("rate limited")


class FailingEvidenceRepository(InMemoryEvidenceRepository):
    async def save_macro(self, raw_observation_id: str, value: object):
        del raw_observation_id, value
        raise RuntimeError("persistence failed")


def plan(plan_id: str = "payroll-release") -> AcquisitionPlan:
    return AcquisitionPlan(
        plan_id,
        1,
        "macro.vintage.read",
        "PAYEMS",
        ("fred_official",),
        AcquisitionCadenceKind.RELEASE_WINDOW,
        timedelta(hours=1),
        timedelta(days=2),
        timedelta(minutes=2),
        timedelta(minutes=10),
        timedelta(hours=2),
    )


def service(
    evidence: InMemoryEvidenceRepository,
    raw: InMemoryMarketIntelligenceRepository,
    clock: Clock,
    capability: ProviderCapability = MACRO_VINTAGE_READ,
) -> MacroAcquisitionService:
    return MacroAcquisitionService(
        Runtime(), raw, evidence, evidence, capability, MacroNormalizer(), clock
    )


@pytest.mark.asyncio
async def test_release_window_persists_before_cursor_and_restart_is_idempotent() -> None:
    evidence = InMemoryEvidenceRepository()
    raw = InMemoryMarketIntelligenceRepository()
    clock = Clock()
    acquisition_plan = plan()
    await evidence.register_plan(acquisition_plan, first_due_at=NOW)
    target = MacroAcquisitionTarget(acquisition_plan, "PAYEMS", "BLS", "US")

    result = await service(evidence, raw, clock).run_once(target, "worker-a")
    checkpoint = await evidence.get_checkpoint(acquisition_plan.plan_id)
    assert result is not None and len(result.observations) == 1
    assert checkpoint is not None and checkpoint.cursor == "1000"
    assert checkpoint.last_persisted_id == result.observations[0].observation_id
    assert len(raw.raw) == 1

    clock.value = NOW + timedelta(hours=1)
    restarted = await service(evidence, raw, clock).run_once(target, "worker-b")
    assert restarted is not None
    assert len(raw.raw) == 1
    assert len(evidence.macro) == 1


@pytest.mark.asyncio
async def test_failed_persistence_never_advances_cursor_and_is_retryable() -> None:
    evidence = FailingEvidenceRepository()
    raw = InMemoryMarketIntelligenceRepository()
    clock = Clock()
    acquisition_plan = plan("failure-plan")
    await evidence.register_plan(acquisition_plan, first_due_at=NOW)

    with pytest.raises(RuntimeError, match="persistence failed"):
        await service(evidence, raw, clock).run_once(
            MacroAcquisitionTarget(acquisition_plan, "PAYEMS", "BLS", "US"), "worker-a"
        )
    checkpoint = await evidence.get_checkpoint(acquisition_plan.plan_id)
    assert checkpoint is not None
    assert checkpoint.cursor is None
    assert checkpoint.last_success_at is None
    assert checkpoint.consecutive_failures == 1


@pytest.mark.asyncio
async def test_multi_worker_claim_has_single_fenced_owner() -> None:
    evidence = InMemoryEvidenceRepository()
    acquisition_plan = plan("fenced-plan")
    await evidence.register_plan(acquisition_plan, first_due_at=NOW)
    first = await evidence.claim_due("fenced-plan", "worker-a", NOW, timedelta(minutes=2))
    second = await evidence.claim_due("fenced-plan", "worker-b", NOW, timedelta(minutes=2))
    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_rate_limit_sets_durable_retry_boundary() -> None:
    evidence = InMemoryEvidenceRepository()
    raw = InMemoryMarketIntelligenceRepository()
    clock = Clock()
    acquisition_plan = plan("rate-limit-plan")
    await evidence.register_plan(acquisition_plan, first_due_at=NOW)
    coordinator = MacroAcquisitionService(
        RateLimitedRuntime(),
        raw,
        evidence,
        evidence,
        MACRO_VINTAGE_READ,
        MacroNormalizer(),
        clock,
    )
    with pytest.raises(ProviderRateLimitedError):
        await coordinator.run_once(
            MacroAcquisitionTarget(acquisition_plan, "PAYEMS", "BLS", "US"), "worker-a"
        )
    checkpoint = await evidence.get_checkpoint(acquisition_plan.plan_id)
    assert checkpoint is not None
    assert checkpoint.rate_limit_reset_at == NOW + timedelta(minutes=5)
    assert checkpoint.retry_not_before == checkpoint.rate_limit_reset_at


def test_release_window_switches_from_normal_to_accelerated_cadence() -> None:
    acquisition_plan = plan("cadence-plan")
    release_at = NOW + timedelta(hours=3)
    target = MacroAcquisitionTarget(acquisition_plan, "PAYEMS", "BLS", "US", release_at)
    assert MacroAcquisitionService._next_due_at(target, NOW) == NOW + timedelta(hours=1)
    inside_window = release_at - timedelta(minutes=5)
    assert MacroAcquisitionService._next_due_at(target, inside_window) == inside_window + timedelta(
        minutes=2
    )
