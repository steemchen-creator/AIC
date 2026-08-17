"""Application-owned historical market-data persistence contracts."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from aic_backend.domain.market_data import InstrumentIdentity


@dataclass(frozen=True, slots=True, order=True)
class DateInterval:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("interval end must not precede start")


class BackfillAttemptStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class BackfillAttempt:
    attempt_id: str
    provider_id: str
    capability: str
    instrument: InstrumentIdentity
    interval: DateInterval
    requested_at: datetime
    completed_at: datetime
    status: BackfillAttemptStatus
    received_count: int
    persisted_count: int
    already_exists_count: int
    failed_count: int
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id.strip() or not self.provider_id.strip():
            raise ValueError("attempt and provider identities must not be empty")
        if not self.capability.strip():
            raise ValueError("capability must not be empty")
        if self.requested_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("backfill timestamps must include timezone information")
        if self.completed_at < self.requested_at:
            raise ValueError("completed_at must not precede requested_at")
        if min(
            self.received_count,
            self.persisted_count,
            self.already_exists_count,
            self.failed_count,
        ) < 0:
            raise ValueError("backfill counts must not be negative")


class BackfillMetadataRepository(Protocol):
    async def record(self, attempt: BackfillAttempt) -> None: ...

    async def get_attempts(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
    ) -> tuple[BackfillAttempt, ...]: ...
