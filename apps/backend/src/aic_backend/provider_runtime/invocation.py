"""Bounded Provider invocation with timeout and resource cleanup."""

import asyncio
from collections.abc import Mapping
from typing import cast

from aic_backend.provider_runtime.errors import (
    CapabilityNotSupportedError,
    ProviderExecutionError,
    ProviderInvalidResponseError,
    ProviderInvocationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from aic_backend.provider_runtime.interfaces import Clock, ProviderInvocationHandler
from aic_backend.provider_runtime.models import (
    ProviderInvocationRequest,
    ProviderInvocationResponse,
    ProviderInvocationResult,
    ProviderStatus,
)
from aic_backend.provider_runtime.registry import ProviderRegistry


class ProviderInvocationManager:
    """Execute one selected Provider without retry or failover."""

    def __init__(
        self,
        registry: ProviderRegistry,
        clock: Clock,
        max_concurrency: Mapping[str, int],
    ) -> None:
        if any(limit <= 0 for limit in max_concurrency.values()):
            raise ValueError("max_concurrency values must be positive")
        self._registry = registry
        self._clock = clock
        self._semaphores = {
            provider_id: asyncio.Semaphore(limit)
            for provider_id, limit in max_concurrency.items()
        }

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResult:
        snapshot = await self._registry.get_snapshot(request.provider_id)
        if snapshot.lifecycle_status not in {ProviderStatus.READY, ProviderStatus.DEGRADED}:
            raise ProviderUnavailableError(
                f"Provider {request.provider_id} is not available for invocation.",
                request_id=request.request_id,
                provider_id=request.provider_id,
                capability=request.capability.name,
            )
        if request.capability not in snapshot.capabilities:
            raise CapabilityNotSupportedError(
                f"Provider {request.provider_id} does not support the requested capability.",
                request_id=request.request_id,
                provider_id=request.provider_id,
                capability=request.capability.name,
            )
        provider = await self._registry.get(request.provider_id)
        invoke = getattr(provider, "invoke", None)
        if not callable(invoke):
            raise ProviderUnavailableError(
                f"Provider {request.provider_id} has no invocation handler.",
                request_id=request.request_id,
                provider_id=request.provider_id,
                capability=request.capability.name,
            )
        handler = cast(ProviderInvocationHandler, provider)
        semaphore = self._semaphores.setdefault(request.provider_id, asyncio.Semaphore(1))
        started_at = self._clock.now()
        try:
            async with asyncio.timeout(request.timeout_ms / 1000):
                async with semaphore:
                    response = await handler.invoke(request)
        except TimeoutError as error:
            raise ProviderTimeoutError(
                f"Provider {request.provider_id} invocation timed out.",
                request_id=request.request_id,
                provider_id=request.provider_id,
                capability=request.capability.name,
            ) from error
        except asyncio.CancelledError:
            raise
        except ProviderInvocationError:
            raise
        except Exception as error:
            raise ProviderExecutionError(
                f"Provider {request.provider_id} invocation failed.",
                request_id=request.request_id,
                provider_id=request.provider_id,
                capability=request.capability.name,
            ) from error
        if not isinstance(response, ProviderInvocationResponse):
            raise ProviderInvalidResponseError(
                f"Provider {request.provider_id} returned an invalid response.",
                request_id=request.request_id,
                provider_id=request.provider_id,
                capability=request.capability.name,
            )
        finished_at = self._clock.now()
        latency_ms = max(0.0, (finished_at - started_at).total_seconds() * 1000)
        return ProviderInvocationResult(
            request_id=request.request_id,
            provider_id=request.provider_id,
            success=True,
            data=response.payload,
            error=None,
            latency_ms=latency_ms,
            started_at=started_at,
            finished_at=finished_at,
        )
