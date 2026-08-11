"""Protocols owned by the provider runtime boundary."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from aic_backend.provider_runtime.models import (
    HealthCheckResult,
    InvocationRecord,
    ProviderCapability,
    ProviderDefinition,
    ProviderInvocationRequest,
    ProviderInvocationResponse,
    ProviderInvocationResult,
    ProviderMetadata,
    ProviderRequestContext,
)


class Provider(Protocol):
    """Lifecycle and identity contract shared by every provider."""

    @property
    def metadata(self) -> ProviderMetadata: ...

    @property
    def capabilities(self) -> frozenset[ProviderCapability]: ...

    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def health_check(self) -> HealthCheckResult: ...


ProviderBuilder = Callable[[ProviderDefinition], Provider]


class ProviderInvocationHandler(Protocol):
    """Explicit capability invocation contract composed with a Provider."""

    async def invoke(
        self, request: ProviderInvocationRequest
    ) -> ProviderInvocationResponse: ...


class ProviderRuntimePort(Protocol):
    """Application-facing provider runtime contract."""

    async def execute(
        self,
        request: ProviderInvocationRequest,
        context: ProviderRequestContext,
    ) -> ProviderInvocationResult: ...


class MetricsCollector(Protocol):
    """Replaceable sink and snapshot source for runtime metrics."""

    async def record(self, invocation: InvocationRecord) -> None: ...

    async def snapshot(self) -> Mapping[str, Any]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...
