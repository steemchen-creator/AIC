"""Provider runtime contracts and immutable models."""

from aic_backend.provider_runtime.factory import ProviderFactory
from aic_backend.provider_runtime.health import ProviderHealthManager
from aic_backend.provider_runtime.interfaces import (
    Clock,
    IdGenerator,
    MetricsCollector,
    Provider,
    ProviderBuilder,
    ProviderInvocationHandler,
    ProviderRuntimePort,
)
from aic_backend.provider_runtime.lifecycle import ProviderLifecycleManager
from aic_backend.provider_runtime.models import (
    CapabilityMode,
    HealthCheckPolicy,
    HealthCheckResult,
    HealthStatus,
    InvocationRecord,
    ProviderAttribution,
    ProviderCapability,
    ProviderDefinition,
    ProviderEventType,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderMetadata,
    ProviderRegistration,
    ProviderRegistrySnapshot,
    ProviderRequestContext,
    ProviderRuntimeEvent,
    ProviderSnapshot,
    ProviderStatus,
    ProviderType,
    SelectionDecision,
)
from aic_backend.provider_runtime.registry import ProviderRegistry
from aic_backend.provider_runtime.system import UtcClock, UuidIdGenerator

__all__ = [
    "CapabilityMode",
    "Clock",
    "HealthCheckResult",
    "HealthCheckPolicy",
    "HealthStatus",
    "IdGenerator",
    "InvocationRecord",
    "MetricsCollector",
    "Provider",
    "ProviderBuilder",
    "ProviderAttribution",
    "ProviderCapability",
    "ProviderDefinition",
    "ProviderEventType",
    "ProviderInvocationHandler",
    "ProviderInvocationRequest",
    "ProviderInvocationResult",
    "ProviderMetadata",
    "ProviderFactory",
    "ProviderHealthManager",
    "ProviderLifecycleManager",
    "ProviderRegistration",
    "ProviderRegistry",
    "ProviderRegistrySnapshot",
    "ProviderRequestContext",
    "ProviderRuntimeEvent",
    "ProviderRuntimePort",
    "ProviderSnapshot",
    "ProviderStatus",
    "ProviderType",
    "SelectionDecision",
    "UtcClock",
    "UuidIdGenerator",
]
