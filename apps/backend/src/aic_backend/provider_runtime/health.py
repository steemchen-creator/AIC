"""Provider health checks and threshold-based lifecycle requests."""

import asyncio
from dataclasses import dataclass

from aic_backend.provider_runtime.errors import ProviderLifecycleError
from aic_backend.provider_runtime.interfaces import Clock
from aic_backend.provider_runtime.lifecycle import ProviderLifecycleManager
from aic_backend.provider_runtime.models import (
    HealthCheckPolicy,
    HealthCheckResult,
    HealthStatus,
    ProviderStatus,
)
from aic_backend.provider_runtime.registry import ProviderRegistry

_CHECKABLE_STATUSES = frozenset(
    {ProviderStatus.READY, ProviderStatus.DEGRADED, ProviderStatus.UNAVAILABLE}
)


@dataclass(slots=True)
class _HealthCounters:
    failures: int = 0
    successes: int = 0


class ProviderHealthManager:
    """Check Provider health and request state changes from Lifecycle Manager."""

    def __init__(
        self,
        registry: ProviderRegistry,
        lifecycle: ProviderLifecycleManager,
        clock: Clock,
        policy: HealthCheckPolicy,
    ) -> None:
        self._registry = registry
        self._lifecycle = lifecycle
        self._clock = clock
        self._policy = policy
        self._counters: dict[str, _HealthCounters] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def check_once(self, provider_id: str) -> HealthCheckResult:
        snapshot = await self._registry.get_snapshot(provider_id)
        if snapshot.lifecycle_status not in _CHECKABLE_STATUSES:
            raise ProviderLifecycleError(
                f"Provider {provider_id} cannot be health checked while "
                f"{snapshot.lifecycle_status.value}.",
                provider_id=provider_id,
            )
        provider = await self._registry.get(provider_id)
        try:
            async with asyncio.timeout(self._policy.timeout_ms / 1000):
                result = await provider.health_check()
        except TimeoutError:
            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                checked_at=self._clock.now(),
                message="Health check timed out.",
            )
        except Exception:
            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                checked_at=self._clock.now(),
                message="Health check failed.",
            )
        await self._apply_result(provider_id, snapshot.lifecycle_status, result)
        return result

    def start(self, provider_id: str) -> None:
        existing = self._tasks.get(provider_id)
        if existing is not None and not existing.done():
            return
        self._tasks[provider_id] = asyncio.create_task(
            self._run(provider_id), name=f"provider-health:{provider_id}"
        )

    async def stop(self, provider_id: str) -> None:
        task = self._tasks.pop(provider_id, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def shutdown(self) -> None:
        for provider_id in tuple(self._tasks):
            await self.stop(provider_id)

    async def _run(self, provider_id: str) -> None:
        while True:
            snapshot = await self._registry.get_snapshot(provider_id)
            if snapshot.lifecycle_status not in _CHECKABLE_STATUSES:
                return
            await self.check_once(provider_id)
            current = await self._registry.get_snapshot(provider_id)
            await asyncio.sleep(self._interval_for(current.lifecycle_status))

    async def _apply_result(
        self,
        provider_id: str,
        current_status: ProviderStatus,
        result: HealthCheckResult,
    ) -> None:
        counters = self._counters.setdefault(provider_id, _HealthCounters())
        target: ProviderStatus | None = None
        if result.status is HealthStatus.HEALTHY:
            counters.failures = 0
            counters.successes += 1
            if (
                current_status is ProviderStatus.UNAVAILABLE
                and counters.successes >= self._policy.recovery_threshold
            ):
                target = ProviderStatus.DEGRADED
                counters.successes = 0
            elif (
                current_status is ProviderStatus.DEGRADED
                and counters.successes >= self._policy.recovery_threshold
            ):
                target = ProviderStatus.READY
                counters.successes = 0
        else:
            counters.successes = 0
            counters.failures += 1
            if current_status is ProviderStatus.READY:
                target = ProviderStatus.DEGRADED
            if counters.failures >= self._policy.failure_threshold:
                target = ProviderStatus.UNAVAILABLE
        await self._lifecycle.record_health(provider_id, result, target)

    def _interval_for(self, status: ProviderStatus) -> float:
        if status is ProviderStatus.DEGRADED:
            return self._policy.degraded_interval_seconds
        if status is ProviderStatus.UNAVAILABLE:
            return self._policy.unavailable_interval_seconds
        return self._policy.ready_interval_seconds
