"""Concurrency-safe in-process Provider Registry."""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime

from aic_backend.provider_runtime.errors import DuplicateProviderError, ProviderNotFoundError
from aic_backend.provider_runtime.interfaces import Clock, Provider
from aic_backend.provider_runtime.models import (
    HealthCheckResult,
    ProviderCapability,
    ProviderMetadata,
    ProviderRegistration,
    ProviderRegistrySnapshot,
    ProviderSnapshot,
    ProviderStatus,
)


@dataclass(frozen=True, slots=True)
class _RegistryEntry:
    provider: Provider
    metadata: ProviderMetadata
    capabilities: frozenset[ProviderCapability]
    registration: ProviderRegistration
    lifecycle_status: ProviderStatus
    health: HealthCheckResult | None
    last_state_change_at: datetime

    def snapshot(self) -> ProviderSnapshot:
        return ProviderSnapshot(
            metadata=self.metadata,
            capabilities=self.capabilities,
            lifecycle_status=self.lifecycle_status,
            health=self.health,
            quality_score=None,
            in_flight_requests=0,
            registered_at=self.registration.registered_at,
            last_state_change_at=self.last_state_change_at,
        )


class ProviderRegistry:
    """Own registered Provider identities without executing Provider methods."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._entries: dict[str, _RegistryEntry] = {}
        self._lock = asyncio.Lock()

    async def register(self, provider: Provider) -> ProviderRegistration:
        metadata = provider.metadata
        capabilities = frozenset(provider.capabilities)
        status = ProviderStatus.REGISTERED if metadata.enabled else ProviderStatus.DISABLED
        registration = ProviderRegistration(
            provider_id=metadata.provider_id,
            lifecycle_status=status,
            registered_at=self._clock.now(),
        )
        entry = _RegistryEntry(
            provider,
            metadata,
            capabilities,
            registration,
            registration.lifecycle_status,
            None,
            registration.registered_at,
        )

        async with self._lock:
            if metadata.provider_id in self._entries:
                raise DuplicateProviderError(
                    f"Provider {metadata.provider_id} is already registered.",
                    provider_id=metadata.provider_id,
                )
            self._entries[metadata.provider_id] = entry
        return registration

    async def unregister(self, provider_id: str) -> None:
        async with self._lock:
            if provider_id not in self._entries:
                raise ProviderNotFoundError(
                    f"Provider {provider_id} is not registered.", provider_id=provider_id
                )
            del self._entries[provider_id]

    async def get(self, provider_id: str) -> Provider:
        async with self._lock:
            entry = self._entries.get(provider_id)
        if entry is None:
            raise ProviderNotFoundError(
                f"Provider {provider_id} is not registered.", provider_id=provider_id
            )
        return entry.provider

    async def get_snapshot(self, provider_id: str) -> ProviderSnapshot:
        async with self._lock:
            entry = self._entries.get(provider_id)
        if entry is None:
            raise ProviderNotFoundError(
                f"Provider {provider_id} is not registered.", provider_id=provider_id
            )
        return entry.snapshot()

    async def _replace_runtime_state(
        self,
        provider_id: str,
        *,
        expected_status: ProviderStatus,
        lifecycle_status: ProviderStatus,
        changed_at: datetime,
        health: HealthCheckResult | None,
    ) -> ProviderSnapshot:
        """Atomically store state chosen by the Lifecycle Manager."""

        async with self._lock:
            entry = self._entries.get(provider_id)
            if entry is None:
                raise ProviderNotFoundError(
                    f"Provider {provider_id} is not registered.", provider_id=provider_id
                )
            if entry.lifecycle_status is not expected_status:
                raise RuntimeError(
                    f"Provider {provider_id} changed concurrently from {expected_status.value} "
                    f"to {entry.lifecycle_status.value}."
                )
            updated = replace(
                entry,
                lifecycle_status=lifecycle_status,
                health=health,
                last_state_change_at=changed_at,
            )
            self._entries[provider_id] = updated
        return updated.snapshot()

    async def list(self) -> tuple[ProviderSnapshot, ...]:
        async with self._lock:
            entries = tuple(self._entries.values())
        return tuple(entry.snapshot() for entry in sorted(
            entries, key=lambda item: item.metadata.provider_id
        ))

    async def find_by_capability(
        self, capability: ProviderCapability
    ) -> tuple[ProviderSnapshot, ...]:
        snapshots = await self.list()
        return tuple(item for item in snapshots if capability in item.capabilities)

    async def snapshot(self) -> ProviderRegistrySnapshot:
        return ProviderRegistrySnapshot(providers=await self.list(), captured_at=self._clock.now())
