"""Immutable value models for the provider runtime."""

from __future__ import annotations

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
_IMPLEMENTATION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
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
    STATUS_CHANGED = "provider_status_changed"


class ProviderSelectionReason(StrEnum):
    PREFERRED_PROVIDER = "preferred_provider"
    READY_STATE = "ready_state"
    DEGRADED_STATE = "degraded_state"
    HIGHER_QUALITY_SCORE = "higher_quality_score"
    HIGHER_PRIORITY = "higher_priority"
    STABLE_PROVIDER_ID_TIE_BREAK = "stable_provider_id_tie_break"


class ProviderExclusionReason(StrEnum):
    PROVIDER_DISABLED = "provider_disabled"
    CAPABILITY_NOT_SUPPORTED = "capability_not_supported"
    EXPLICITLY_EXCLUDED = "explicitly_excluded"
    LIFECYCLE_NOT_SELECTABLE = "lifecycle_not_selectable"
    DEGRADED_NOT_ALLOWED = "degraded_not_allowed"
    HEALTH_UNHEALTHY = "health_unhealthy"
    HEALTH_UNKNOWN = "health_unknown"
    PROVIDER_IN_COOLDOWN = "provider_in_cooldown"
    CONCURRENCY_CAPACITY_EXHAUSTED = "concurrency_capacity_exhausted"


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
class ProviderDefinition:
    provider_id: str
    implementation: str
    enabled: bool
    priority: int
    capabilities: frozenset[ProviderCapability]
    config: Mapping[str, Any]
    required: bool = False
    max_concurrency: int = 1
    queue_timeout_ms: int = 500

    def __post_init__(self) -> None:
        if _PROVIDER_ID_PATTERN.fullmatch(self.provider_id) is None:
            raise ValueError("provider_id must match ^[a-z][a-z0-9_]{2,63}$")
        if _IMPLEMENTATION_PATTERN.fullmatch(self.implementation) is None:
            raise ValueError("implementation must use a controlled dotted name")
        if not 0 <= self.priority <= 1000:
            raise ValueError("priority must be between 0 and 1000")
        if not self.capabilities:
            raise ValueError("capabilities must not be empty")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if self.queue_timeout_ms <= 0:
            raise ValueError("queue_timeout_ms must be positive")
        object.__setattr__(self, "config", _freeze_mapping(self.config))


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
class HealthCheckPolicy:
    ready_interval_seconds: float = 60
    degraded_interval_seconds: float = 30
    unavailable_interval_seconds: float = 60
    timeout_ms: int = 2000
    failure_threshold: int = 3
    recovery_threshold: int = 2

    def __post_init__(self) -> None:
        intervals = (
            self.ready_interval_seconds,
            self.degraded_interval_seconds,
            self.unavailable_interval_seconds,
        )
        if any(interval <= 0 for interval in intervals):
            raise ValueError("health check intervals must be positive")
        if self.timeout_ms <= 0:
            raise ValueError("health check timeout_ms must be positive")
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.recovery_threshold <= 0:
            raise ValueError("recovery_threshold must be positive")


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
class ProviderRegistration:
    provider_id: str
    lifecycle_status: ProviderStatus
    registered_at: datetime

    def __post_init__(self) -> None:
        if _PROVIDER_ID_PATTERN.fullmatch(self.provider_id) is None:
            raise ValueError("provider_id must match ^[a-z][a-z0-9_]{2,63}$")
        if self.lifecycle_status not in {ProviderStatus.REGISTERED, ProviderStatus.DISABLED}:
            raise ValueError("registration status must be registered or disabled")
        _require_aware(self.registered_at, "registered_at")


@dataclass(frozen=True, slots=True)
class ProviderRegistrySnapshot:
    providers: tuple[ProviderSnapshot, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.captured_at, "captured_at")
        provider_ids = tuple(item.metadata.provider_id for item in self.providers)
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("registry snapshot must not contain duplicate provider IDs")


@dataclass(frozen=True, slots=True)
class ProviderRequestContext:
    request_id: str
    capability: ProviderCapability
    timeout_ms: int
    preferred_provider_ids: tuple[str, ...] = ()
    excluded_provider_ids: frozenset[str] = frozenset()
    allow_degraded: bool = False
    symbol: str | None = None
    market: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        preferred = tuple(self.preferred_provider_ids)
        excluded = frozenset(self.excluded_provider_ids)
        if any(not provider_id.strip() for provider_id in preferred):
            raise ValueError("preferred_provider_ids must not contain empty values")
        if any(not provider_id.strip() for provider_id in excluded):
            raise ValueError("excluded_provider_ids must not contain empty values")
        object.__setattr__(self, "preferred_provider_ids", preferred)
        object.__setattr__(self, "excluded_provider_ids", excluded)


@dataclass(frozen=True, slots=True)
class ProviderMetricsSnapshot:
    provider_id: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    timeout_calls: int = 0
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    data_freshness_seconds: float | None = None
    in_flight_requests: int = 0
    max_concurrency: int = 1
    cooldown_until: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id")
        counts = (
            self.total_calls,
            self.successful_calls,
            self.failed_calls,
            self.timeout_calls,
            self.in_flight_requests,
        )
        if any(value < 0 for value in counts):
            raise ValueError("metrics counts must not be negative")
        if self.successful_calls + self.failed_calls > self.total_calls:
            raise ValueError("successful_calls and failed_calls must not exceed total_calls")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        for value, name in (
            (self.p50_latency_ms, "p50_latency_ms"),
            (self.p95_latency_ms, "p95_latency_ms"),
            (self.data_freshness_seconds, "data_freshness_seconds"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.last_success_at is not None:
            _require_aware(self.last_success_at, "last_success_at")
        if self.last_failure_at is not None:
            _require_aware(self.last_failure_at, "last_failure_at")
        if self.cooldown_until is not None:
            _require_aware(self.cooldown_until, "cooldown_until")


@dataclass(frozen=True, slots=True)
class ProviderCapacitySnapshot:
    in_flight_requests: int
    max_concurrency: int

    def __post_init__(self) -> None:
        if self.in_flight_requests < 0:
            raise ValueError("in_flight_requests must not be negative")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")


@dataclass(frozen=True, slots=True)
class ProviderCooldownSnapshot:
    cooldown_until: datetime | None

    def __post_init__(self) -> None:
        if self.cooldown_until is not None:
            _require_aware(self.cooldown_until, "cooldown_until")


@dataclass(frozen=True, slots=True)
class QualityScoreBreakdown:
    total_score: float
    availability_score: float
    success_rate_score: float
    latency_score: float
    freshness_score: float
    priority_score: float
    used_default_success_rate: bool
    used_default_latency: bool
    used_p50_latency: bool
    freshness_unknown: bool

    def __post_init__(self) -> None:
        scores = (
            self.total_score,
            self.availability_score,
            self.success_rate_score,
            self.latency_score,
            self.freshness_score,
            self.priority_score,
        )
        if any(not 0 <= score <= 100 for score in scores):
            raise ValueError("quality scores must be between 0 and 100")
        weighted = (
            self.availability_score * 0.35
            + self.success_rate_score * 0.30
            + self.latency_score * 0.20
            + self.freshness_score * 0.10
            + self.priority_score * 0.05
        )
        if abs(self.total_score - weighted) > 1e-9:
            raise ValueError("total_score must equal the weighted component scores")


@dataclass(frozen=True, slots=True)
class ProviderCandidate:
    provider_id: str
    lifecycle_status: ProviderStatus
    health_status: HealthStatus
    priority: int
    quality_score: float
    score_breakdown: QualityScoreBreakdown
    preferred_rank: int | None


@dataclass(frozen=True, slots=True)
class ProviderInvocationRequest:
    request_id: str
    provider_id: str
    capability: ProviderCapability
    payload: Mapping[str, Any]
    timeout_ms: int
    created_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.provider_id, "provider_id")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        _require_aware(self.created_at, "created_at")
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
class ProviderInvocationResponse:
    payload: Mapping[str, Any]
    source_timestamp: datetime | None = None
    attribution: ProviderAttribution | None = None

    def __post_init__(self) -> None:
        if self.source_timestamp is not None:
            _require_aware(self.source_timestamp, "source_timestamp")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))


@dataclass(frozen=True, slots=True)
class InvocationErrorDetail:
    error_code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        _require_text(self.error_code, "error_code")
        _require_text(self.message, "message")


@dataclass(frozen=True, slots=True)
class FailoverAttempt:
    provider_id: str
    attempt_number: int
    success: bool
    error_code: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id")
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        if self.success and self.error_code is not None:
            raise ValueError("successful attempt must not contain error_code")
        if not self.success and self.error_code is None:
            raise ValueError("failed attempt must contain error_code")


@dataclass(frozen=True, slots=True)
class FailoverContext:
    request_id: str
    capability: ProviderCapability
    original_provider_id: str
    attempted_provider_ids: tuple[str, ...]
    max_failover_attempts: int
    started_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.original_provider_id, "original_provider_id")
        attempted = tuple(self.attempted_provider_ids)
        if len(attempted) != len(set(attempted)):
            raise ValueError("attempted_provider_ids must not contain duplicates")
        if self.max_failover_attempts < 0:
            raise ValueError("max_failover_attempts must not be negative")
        _require_aware(self.started_at, "started_at")
        object.__setattr__(self, "attempted_provider_ids", attempted)


@dataclass(frozen=True, slots=True)
class FailoverDecision:
    should_failover: bool
    reason: str
    excluded_provider_ids: frozenset[str]
    next_provider_candidates: tuple[str, ...]
    attempt_number: int

    def __post_init__(self) -> None:
        _require_text(self.reason, "reason")
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        object.__setattr__(self, "excluded_provider_ids", frozenset(self.excluded_provider_ids))
        object.__setattr__(self, "next_provider_candidates", tuple(self.next_provider_candidates))


@dataclass(frozen=True, slots=True)
class ProviderInvocationResult:
    request_id: str
    provider_id: str
    success: bool
    data: Mapping[str, Any] | None
    error: InvocationErrorDetail | None
    latency_ms: float
    started_at: datetime
    finished_at: datetime
    attempt_history: tuple[FailoverAttempt, ...] = ()
    failover_count: int = 0

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.provider_id, "provider_id")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        _require_aware(self.started_at, "started_at")
        _require_aware(self.finished_at, "finished_at")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.success and (self.data is None or self.error is not None):
            raise ValueError("successful result must contain data and no error")
        if not self.success and (self.data is not None or self.error is None):
            raise ValueError("failed result must contain error and no data")
        if self.data is not None:
            object.__setattr__(self, "data", _freeze_mapping(self.data))
        history = tuple(self.attempt_history)
        if self.failover_count < 0 or self.failover_count > max(0, len(history) - 1):
            raise ValueError("failover_count must match attempt history")
        object.__setattr__(self, "attempt_history", history)


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
    capability: ProviderCapability
    selected_provider_id: str
    ordered_candidate_provider_ids: tuple[str, ...]
    candidate_scores: Mapping[str, float]
    score_breakdowns: Mapping[str, QualityScoreBreakdown]
    selection_reasons: Mapping[str, tuple[ProviderSelectionReason, ...]]
    excluded_providers: Mapping[str, ProviderExclusionReason]
    decided_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.selected_provider_id, "selected_provider_id")
        _require_aware(self.decided_at, "decided_at")
        utc_offset = self.decided_at.utcoffset()
        if utc_offset is None or utc_offset.total_seconds() != 0:
            raise ValueError("decided_at must use UTC")
        candidates = tuple(self.ordered_candidate_provider_ids)
        if not candidates or self.selected_provider_id != candidates[0]:
            raise ValueError("selected_provider_id must be the first ordered candidate")
        candidate_ids = set(candidates)
        if (
            set(self.candidate_scores) != candidate_ids
            or set(self.score_breakdowns) != candidate_ids
        ):
            raise ValueError("candidate scores and breakdowns must match candidates")
        object.__setattr__(self, "ordered_candidate_provider_ids", candidates)
        object.__setattr__(self, "candidate_scores", _freeze_mapping(self.candidate_scores))
        object.__setattr__(self, "score_breakdowns", _freeze_mapping(self.score_breakdowns))
        object.__setattr__(self, "selection_reasons", _freeze_mapping(self.selection_reasons))
        object.__setattr__(self, "excluded_providers", _freeze_mapping(self.excluded_providers))


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
