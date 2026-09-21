"""Source-neutral macro, calendar, and acquisition evidence models."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from aic_backend.domain.market_data import SourceLineage


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone information")
    return value.astimezone(UTC)


class MacroFrequency(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"
    IRREGULAR = "IRREGULAR"


class SeasonalAdjustment(StrEnum):
    NOT_SEASONALLY_ADJUSTED = "NOT_SEASONALLY_ADJUSTED"
    SEASONALLY_ADJUSTED = "SEASONALLY_ADJUSTED"
    SEASONALLY_ADJUSTED_ANNUAL_RATE = "SEASONALLY_ADJUSTED_ANNUAL_RATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MacroQueryMode(StrEnum):
    KNOWN_AT = "KNOWN_AT"
    AS_PUBLISHED = "AS_PUBLISHED"
    LATEST_REVISED = "LATEST_REVISED"


@dataclass(frozen=True, slots=True)
class MacroSeriesIdentity:
    series_id: str
    title: str
    geography: str
    source_agency_id: str
    unit: str
    frequency: MacroFrequency
    seasonal_adjustment: SeasonalAdjustment

    def __post_init__(self) -> None:
        for field in ("series_id", "title", "geography", "source_agency_id", "unit"):
            object.__setattr__(self, field, _text(getattr(self, field), field))

    @property
    def authority_key(self) -> tuple[str, str]:
        """Identify the factual producer/series independently of its transport adapter."""
        return (self.source_agency_id, self.series_id)


@dataclass(frozen=True, slots=True)
class MacroObservation:
    observation_id: str
    series: MacroSeriesIdentity
    period_start: date
    period_end: date
    value: Decimal
    release_at: datetime
    realtime_start: date
    realtime_end: date
    vintage_date: date
    observed_at: datetime
    ingested_at: datetime
    lineage: SourceLineage
    predecessor_observation_id: str | None = None

    RECORD_TYPE = "MACRO_OBSERVATION"

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _text(self.observation_id, "observation_id"))
        if not isinstance(self.value, Decimal):
            raise TypeError("value must be Decimal")
        if self.period_end < self.period_start:
            raise ValueError("period_end must not precede period_start")
        if self.realtime_end < self.realtime_start:
            raise ValueError("realtime_end must not precede realtime_start")
        if not self.realtime_start <= self.vintage_date <= self.realtime_end:
            raise ValueError("vintage_date must be within the realtime interval")
        for field in ("release_at", "observed_at", "ingested_at"):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        if self.release_at > self.observed_at or self.observed_at > self.ingested_at:
            raise ValueError("macro publication, observation and ingestion order is invalid")
        if (self.observed_at, self.ingested_at) != (
            self.lineage.observed_at,
            self.lineage.ingested_at,
        ):
            raise ValueError("macro timestamps must match source lineage")
        if self.lineage.published_at != self.release_at:
            raise ValueError("release_at must match source lineage published_at")
        if self.predecessor_observation_id is not None:
            object.__setattr__(
                self,
                "predecessor_observation_id",
                _text(self.predecessor_observation_id, "predecessor_observation_id"),
            )
            if self.predecessor_observation_id == self.observation_id:
                raise ValueError("an observation cannot supersede itself")

    @property
    def source_known_at(self) -> datetime:
        return max(
            self.release_at,
            datetime.combine(self.vintage_date, datetime.min.time(), tzinfo=UTC),
        )


class ScheduledEventType(StrEnum):
    CENTRAL_BANK_MEETING = "CENTRAL_BANK_MEETING"
    MACRO_RELEASE = "MACRO_RELEASE"
    EARNINGS = "EARNINGS"
    OTHER = "OTHER"


class ScheduledEventStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    event_version_id: str
    event_id: str
    event_type: ScheduledEventType
    subject_id: str
    scheduled_start: datetime
    scheduled_end: datetime | None
    timezone: str
    status: ScheduledEventStatus
    version: int
    predecessor_version_id: str | None
    published_at: datetime
    observed_at: datetime
    ingested_at: datetime
    actual_evidence_ids: tuple[str, ...]
    lineage: SourceLineage

    RECORD_TYPE = "SCHEDULED_EVENT"

    def __post_init__(self) -> None:
        for field in ("event_version_id", "event_id", "subject_id", "timezone"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in ("scheduled_start", "published_at", "observed_at", "ingested_at"):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        if self.scheduled_end is not None:
            object.__setattr__(self, "scheduled_end", _utc(self.scheduled_end, "scheduled_end"))
            if self.scheduled_end < self.scheduled_start:
                raise ValueError("scheduled_end must not precede scheduled_start")
        if self.version <= 0:
            raise ValueError("version must be positive")
        if (self.version == 1) != (self.predecessor_version_id is None):
            raise ValueError("only the first schedule version omits a predecessor")
        if self.predecessor_version_id is not None:
            object.__setattr__(
                self,
                "predecessor_version_id",
                _text(self.predecessor_version_id, "predecessor_version_id"),
            )
        if self.published_at > self.observed_at or self.observed_at > self.ingested_at:
            raise ValueError("schedule publication, observation and ingestion order is invalid")
        if self.lineage.published_at != self.published_at:
            raise ValueError("scheduled event published_at must match source lineage")
        evidence = tuple(
            sorted({_text(value, "actual_evidence_id") for value in self.actual_evidence_ids})
        )
        object.__setattr__(self, "actual_evidence_ids", evidence)
        if self.status is ScheduledEventStatus.COMPLETED and not evidence:
            raise ValueError("completed scheduled event requires actual evidence")
        if self.status is not ScheduledEventStatus.COMPLETED and evidence:
            raise ValueError("only completed scheduled events may link actual evidence")


class AcquisitionCadenceKind(StrEnum):
    FIXED_INTERVAL = "FIXED_INTERVAL"
    RELEASE_WINDOW = "RELEASE_WINDOW"


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    plan_id: str
    version: int
    capability: str
    scope_id: str
    preferred_provider_ids: tuple[str, ...]
    cadence_kind: AcquisitionCadenceKind
    interval: timedelta
    overlap: timedelta
    release_window_interval: timedelta = timedelta(minutes=5)
    release_window_before: timedelta = timedelta(0)
    release_window_after: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        for field in ("plan_id", "capability", "scope_id"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if (
            self.version <= 0
            or self.interval <= timedelta(0)
            or self.release_window_interval <= timedelta(0)
            or self.overlap < timedelta(0)
        ):
            raise ValueError("acquisition plan version/interval/overlap is invalid")
        providers = tuple(
            sorted({_text(value, "provider_id") for value in self.preferred_provider_ids})
        )
        if not providers:
            raise ValueError("acquisition plan requires a preferred provider")
        object.__setattr__(self, "preferred_provider_ids", providers)
        if self.release_window_before < timedelta(0) or self.release_window_after < timedelta(0):
            raise ValueError("release windows must not be negative")


@dataclass(frozen=True, slots=True)
class AcquisitionCheckpoint:
    plan_id: str
    plan_version: int
    next_due_at: datetime
    cursor: str | None = None
    watermark: datetime | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_persisted_id: str | None = None
    consecutive_failures: int = 0
    retry_not_before: datetime | None = None
    rate_limit_reset_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    fencing_token: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _text(self.plan_id, "plan_id"))
        if self.plan_version <= 0 or self.fencing_token < 0 or self.consecutive_failures < 0:
            raise ValueError("checkpoint counters are invalid")
        object.__setattr__(self, "next_due_at", _utc(self.next_due_at, "next_due_at"))
        for field in (
            "watermark",
            "last_attempt_at",
            "last_success_at",
            "retry_not_before",
            "rate_limit_reset_at",
            "lease_expires_at",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _utc(value, field))
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError("lease owner and expiry must be set together")


@dataclass(frozen=True, slots=True)
class AcquisitionClaim:
    plan_id: str
    plan_version: int
    worker_id: str
    fencing_token: int
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        for field in ("plan_id", "worker_id"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if self.plan_version <= 0 or self.fencing_token <= 0:
            raise ValueError("claim version and fencing token must be positive")
        object.__setattr__(
            self, "lease_expires_at", _utc(self.lease_expires_at, "lease_expires_at")
        )
