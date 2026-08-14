"""Application-facing facade over selection, invocation, and bounded failover."""

from collections.abc import Mapping
from typing import Any

from aic_backend.provider_runtime.failover import ProviderFailoverManager
from aic_backend.provider_runtime.interfaces import Clock
from aic_backend.provider_runtime.models import ProviderInvocationResult, ProviderRequestContext
from aic_backend.provider_runtime.registry import ProviderRegistry


class ProviderRuntime:
    """Supply current runtime snapshots without exposing them to Application."""

    def __init__(
        self,
        registry: ProviderRegistry,
        failover: ProviderFailoverManager,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._failover = failover
        self._clock = clock

    async def execute(
        self,
        context: ProviderRequestContext,
        payload: Mapping[str, Any],
    ) -> ProviderInvocationResult:
        now = self._clock.now()
        return await self._failover.execute(
            context,
            payload,
            await self._registry.snapshot(),
            {},
            now,
        )
