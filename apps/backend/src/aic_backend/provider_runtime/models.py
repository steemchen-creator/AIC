"""Immutable value models for the provider runtime."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_CAPABILITY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
)
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _require_text(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone information")


def _require_semver(value: str, name: str) -> None:
    if _SEMVER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a semantic version")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


class ProviderType(StrEnum):
    MARKET_DATA = "market_data"
    FUNDAMENTAL_DATA = "fundamental_data"
    NEWS = "news"
    MACRO = "macro"
    RESEARCH = "research"
    TRADING = "trading"
    INTERNAL = "internal"
    MOCK = "mock"


class ProviderStatus(StrEnum):
    REGISTERED = "registered"
    INITIALIZING = "initializing"
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"
    STOPPED = "stopped"
    DISABLED = "disabled"
    FAILED = "failed"


class CapabilityMode(StrEnum):
    SNAPSHOT = "snapshot"
    BATCH = "batch"
    STREAM = "stream"
    COMMAND = "command"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ProviderEventType(StrEnum):
    REGISTERED = "provider_registered"
    READY = "provider_ready"
    HEALTH_CHANGED = "provider_health_changed"
    INVOCATION_FAILED = "provider_invocation_failed"
    FAILOVER_OCCURRED = "provider_failover_occurred"
    DISABLED = "provider_disabled"


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    provider_type: ProviderType
    version: str
    vendor: str | None = None
    description: str | None = None
    priority: int = 0
    enabled: bool = True
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if _PROVIDER_ID_PATTERN.fullmatch(self.provider_id) is None:
            raise ValueError("provider_id must match ^[a-z][a-z0-9_]{2,63}$")
        _require_text(self.display_name, "display_name")
        _require_semver(self.version, "version")
        if not 0 <= self.priority <= 1000:
            raise ValueError("priority must be between 0 and 1000")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("tags must not contain empty values")


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    name: str
    version: str
    mode: CapabilityMode

    def __post_init__(self) -> None:
        if _CAPABILITY_PATTERN.fullmatch(self.name) is None:
            raise ValueError("capability name must use <domain>.<resource>.<operation>")
        _require_semver(self.version, "capability version")


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    status: HealthStatus
    checked_at: datetime
    latency_ms: float | None = None
    message: str | None = None
    details: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        _require_aware(self.checked_at, "checked_at")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        object.__setattr__(self, "details", _freeze_mapping(self.details))


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    metadata: ProviderMetadata
    capabilities: frozenset[ProviderCapability]
    lifecycle_status: ProviderStatus
    health: HealthCheckResult | None
    quality_score: float | None
    in_flight_requests: int
    registered_at: datetime
    last_state_change_at: datetime

    def __post_init__(self) -> None:
        if self.quality_score is not None and not 0 <= self.quality_score <= 100:
            raise ValueError("quality_score must be between 0 and 100")
        if self.in_flight_requests < 0:
            raise ValueError("in_flight_requests must not be negative")
        _require_aware(self.registered_at, "registered_at")
        _require_aware(self.last_state_change_at, "last_state_change_at")


@dataclass(frozen=True, slots=True)
class ProviderRequestContext:
    capability: ProviderCapability
    request_id: str
    timeout_ms: int
    symbol: str | None = None
    market: str | None = None
    preferred_provider_ids: tuple[str, ...] = ()
    excluded_provider_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")


@dataclass(frozen=True, slots=True)
class ProviderInvocationRequest:
    capability: ProviderCapability
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class ProviderAttribution:
    provider_id: str
    capability: str
    invocation_id: str
    retrieved_at: datetime
    source_timestamp: datetime | None
    failover_count: int

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id")
        _require_text(self.capability, "capability")
        _require_text(self.invocation_id, "invocation_id")
        _require_aware(self.retrieved_at, "retrieved_at")
        if self.source_timestamp is not None:
            _require_aware(self.source_timestamp, "source_timestamp")
        if self.failover_count < 0:
            raise ValueError("failover_count must not be negative")


@dataclass(frozen=True, slots=True)
class ProviderInvocationResult:
    payload: Mapping[str, Any]
    source_timestamp: datetime | None = None
    attribution: ProviderAttribution | None = None

    def __post_init__(self) -> None:
        if self.source_timestamp is not None:
            _require_aware(self.source_timestamp, "source_timestamp")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class InvocationRecord:
    invocation_id: str
    request_id: str
    provider_id: str
    capability: str
    attempt: int
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    outcome: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.invocation_id, "invocation_id"),
            (self.request_id, "request_id"),
            (self.provider_id, "provider_id"),
            (self.capability, "capability"),
            (self.outcome, "outcome"),
        ):
            _require_text(value, name)
        if self.attempt < 1:
            raise ValueError("attempt must be positive")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")
        _require_aware(self.started_at, "started_at")
        _require_aware(self.finished_at, "finished_at")


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    request_id: str
    capability: str
    selected_provider_id: str
    candidate_provider_ids: tuple[str, ...]
    scores: Mapping[str, float]
    reasons: Mapping[str, tuple[str, ...]]
    decided_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.capability, "capability")
        _require_text(self.selected_provider_id, "selected_provider_id")
        _require_aware(self.decided_at, "decided_at")
        object.__setattr__(self, "scores", _freeze_mapping(self.scores))
        object.__setattr__(self, "reasons", _freeze_mapping(self.reasons))


@dataclass(frozen=True, slots=True)
class ProviderRuntimeEvent:
    event_id: str
    event_type: ProviderEventType
    occurred_at: datetime
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))
