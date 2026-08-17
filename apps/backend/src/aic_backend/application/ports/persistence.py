"""Application-owned canonical persistence contract."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from aic_backend.data_foundation.quality import DataQualityAssessment
from aic_backend.domain.market_data import DailyBar, InstrumentIdentity


class SaveStatus(StrEnum):
    INSERTED = "INSERTED"
    ALREADY_EXISTS = "ALREADY_EXISTS"


@dataclass(frozen=True, slots=True)
class SaveResult:
    status: SaveStatus
    record_id: str


@dataclass(frozen=True, slots=True)
class PersistedDailyBar:
    observation_id: str
    record: DailyBar
    quality: DataQualityAssessment


class PersistenceErrorCode(StrEnum):
    UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    CONSTRAINT_VIOLATION = "PERSISTENCE_CONSTRAINT_VIOLATION"
    IDENTITY_CONFLICT = "PERSISTENCE_IDENTITY_CONFLICT"
    SERIALIZATION_ERROR = "PERSISTENCE_SERIALIZATION_ERROR"
    TRANSACTION_ERROR = "PERSISTENCE_TRANSACTION_ERROR"


class PersistenceError(RuntimeError):
    def __init__(self, code: PersistenceErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class CanonicalDailyBarRepository(Protocol):
    async def save(self, value: PersistedDailyBar) -> SaveResult: ...

    async def get_by_record_id(self, record_id: str) -> PersistedDailyBar | None: ...

    async def get_daily_bars(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
    ) -> tuple[PersistedDailyBar, ...]: ...
