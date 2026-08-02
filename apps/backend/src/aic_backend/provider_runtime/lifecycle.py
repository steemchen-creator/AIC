"""Validated and serialized Provider lifecycle management."""

import asyncio

from aic_backend.application.ports import EventBus
from aic_backend.provider_runtime.errors import (
    InvalidStateTransitionError,
    ProviderLifecycleError,
)
from aic_backend.provider_runtime.interfaces import Clock, IdGenerator, Provider
from aic_backend.provider_runtime.models import (
    HealthCheckResult,
    ProviderEventType,
    ProviderRegistration,
    ProviderRuntimeEvent,
    ProviderSnapshot,
    ProviderStatus,
)
from aic_backend.provider_runtime.registry import ProviderRegistry

_ALLOWED_TRANSITIONS: dict[ProviderStatus, frozenset[ProviderStatus]] = {
    ProviderStatus.REGISTERED: frozenset(
        {ProviderStatus.INITIALIZING, ProviderStatus.DISABLED}
    ),
    ProviderStatus.INITIALIZING: frozenset({ProviderStatus.READY, ProviderStatus.FAILED}),
    ProviderStatus.READY: frozenset(
        {
            ProviderStatus.DEGRADED,
            ProviderStatus.UNAVAILABLE,
            ProviderStatus.STOPPING,
            ProviderStatus.DISABLED,
        }
    ),
    ProviderStatus.DEGRADED: frozenset(
        {
            ProviderStatus.READY,
            ProviderStatus.UNAVAILABLE,
            ProviderStatus.STOPPING,
            ProviderStatus.DISABLED,
        }
    ),
    ProviderStatus.UNAVAILABLE: frozenset(
        {
            ProviderStatus.DEGRADED,
            ProviderStatus.READY,
            ProviderStatus.STOPPING,
            ProviderStatus.DISABLED,
        }
    ),
    ProviderStatus.STOPPING: frozenset({ProviderStatus.STOPPED, ProviderStatus.FAILED}),
    ProviderStatus.STOPPED: frozenset(),
    ProviderStatus.DISABLED: frozenset({ProviderStatus.INITIALIZING}),
    ProviderStatus.FAILED: frozenset({ProviderStatus.INITIALIZING}),
}


class ProviderLifecycleManager:
    """The sole owner of validated Provider status changes."""

    def __init__(
        self,
        registry: ProviderRegistry,
        event_bus: EventBus,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus
        self._clock = clock
        self._id_generator = id_generator
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, provider_id: str) -> asyncio.Lock:
        return self._locks.setdefault(provider_id, asyncio.Lock())

    async def register(self, provider: Provider) -> ProviderRegistration:
        registration = await self._registry.register(provider)
        await self._publish(
            ProviderEventType.REGISTERED,
            provider.metadata.provider_id,
            {"status": registration.lifecycle_status.value},
        )
        return registration

    async def transition(
        self, provider_id: str, target: ProviderStatus
    ) -> ProviderSnapshot:
        async with self._lock_for(provider_id):
            return await self._transition_locked(provider_id, target)

    async def initialize(self, provider_id: str) -> ProviderSnapshot:
        async with self._lock_for(provider_id):
            await self._transition_locked(provider_id, ProviderStatus.INITIALIZING)
            provider = await self._registry.get(provider_id)
            try:
                await provider.initialize()
            except Exception as error:
                await self._transition_locked(provider_id, ProviderStatus.FAILED)
                raise ProviderLifecycleError(
                    f"Provider {provider_id} initialization failed.", provider_id=provider_id
                ) from error
            snapshot = await self._transition_locked(provider_id, ProviderStatus.READY)
            await self._publish(
                ProviderEventType.READY, provider_id, {"status": ProviderStatus.READY.value}
            )
            return snapshot

    async def shutdown(self, provider_id: str) -> ProviderSnapshot:
        async with self._lock_for(provider_id):
            await self._transition_locked(provider_id, ProviderStatus.STOPPING)
            provider = await self._registry.get(provider_id)
            try:
                await provider.shutdown()
            except Exception as error:
                await self._transition_locked(provider_id, ProviderStatus.FAILED)
                raise ProviderLifecycleError(
                    f"Provider {provider_id} shutdown failed.", provider_id=provider_id
                ) from error
            return await self._transition_locked(provider_id, ProviderStatus.STOPPED)

    async def disable(self, provider_id: str, reason: str) -> ProviderSnapshot:
        async with self._lock_for(provider_id):
            snapshot = await self._transition_locked(provider_id, ProviderStatus.DISABLED)
            await self._publish(
                ProviderEventType.DISABLED,
                provider_id,
                {"status": ProviderStatus.DISABLED.value, "reason": reason},
            )
            return snapshot

    async def record_health(
        self,
        provider_id: str,
        result: HealthCheckResult,
        target_status: ProviderStatus | None = None,
    ) -> ProviderSnapshot:
        async with self._lock_for(provider_id):
            current = await self._registry.get_snapshot(provider_id)
            target = target_status or current.lifecycle_status
            if target is not current.lifecycle_status:
                self._validate_transition(provider_id, current.lifecycle_status, target)
            snapshot = await self._registry._replace_runtime_state(
                provider_id,
                expected_status=current.lifecycle_status,
                lifecycle_status=target,
                changed_at=self._clock.now(),
                health=result,
            )
            await self._publish(
                ProviderEventType.HEALTH_CHANGED,
                provider_id,
                {
                    "from_status": current.lifecycle_status.value,
                    "to_status": target.value,
                    "health": result.status.value,
                },
            )
            return snapshot

    async def _transition_locked(
        self, provider_id: str, target: ProviderStatus
    ) -> ProviderSnapshot:
        current = await self._registry.get_snapshot(provider_id)
        self._validate_transition(provider_id, current.lifecycle_status, target)
        snapshot = await self._registry._replace_runtime_state(
            provider_id,
            expected_status=current.lifecycle_status,
            lifecycle_status=target,
            changed_at=self._clock.now(),
            health=current.health,
        )
        await self._publish(
            ProviderEventType.STATUS_CHANGED,
            provider_id,
            {"from_status": current.lifecycle_status.value, "to_status": target.value},
        )
        return snapshot

    @staticmethod
    def _validate_transition(
        provider_id: str, current: ProviderStatus, target: ProviderStatus
    ) -> None:
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransitionError(
                f"Provider {provider_id} cannot transition from {current.value} "
                f"to {target.value}.",
                provider_id=provider_id,
            )

    async def _publish(
        self, event_type: ProviderEventType, provider_id: str, payload: dict[str, str]
    ) -> None:
        await self._event_bus.publish(
            ProviderRuntimeEvent(
                event_id=self._id_generator.new_id("evt"),
                event_type=event_type,
                occurred_at=self._clock.now(),
                payload={"provider_id": provider_id, **payload},
            )
        )
