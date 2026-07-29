"""Concurrency-safe in-process Provider Registry."""

import asyncio
from dataclasses import dataclass

from aic_backend.provider_runtime.errors import DuplicateProviderError, ProviderNotFoundError
from aic_backend.provider_runtime.interfaces import Clock, Provider
from aic_backend.provider_runtime.models import (
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

    def snapshot(self) -> ProviderSnapshot:
        return ProviderSnapshot(
            metadata=self.metadata,
            capabilities=self.capabilities,
            lifecycle_status=self.registration.lifecycle_status,
            health=None,
            quality_score=None,
            in_flight_requests=0,
            registered_at=self.registration.registered_at,
            last_state_change_at=self.registration.registered_at,
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
        entry = _RegistryEntry(provider, metadata, capabilities, registration)

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
