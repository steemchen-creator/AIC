"""Immutable point-in-time query vocabulary and availability policy."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeVar

from aic_backend.application.ports.persistence import PersistedDailyBar
from aic_backend.domain.market_data import (
    AdjustmentFactor,
    AdjustmentMode,
    CorporateAction,
    InstrumentMaster,
    InstrumentTradingStatus,
    TradingSessionDay,
)

T = TypeVar("T")
PITRecord = (
    PersistedDailyBar
    | AdjustmentFactor
    | CorporateAction
    | InstrumentMaster
    | InstrumentTradingStatus
    | TradingSessionDay
)


class AvailabilityMode(StrEnum):
    HISTORICAL_RESEARCH = "HISTORICAL_RESEARCH"
    OPERATIONAL_REPLAY = "OPERATIONAL_REPLAY"


class AvailabilityClassification(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"
    UNKNOWN_AVAILABILITY = "UNKNOWN_AVAILABILITY"


@dataclass(frozen=True, slots=True)
class PointInTimeContext:
    as_of: datetime
    availability_mode: AvailabilityMode
    adjustment_mode: AdjustmentMode = AdjustmentMode.RAW
    policy_version: str = "point-in-time-availability/v1"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")
        if self.policy_version != "point-in-time-availability/v1":
            raise ValueError("unsupported point-in-time policy version")


@dataclass(frozen=True, slots=True)
class AvailabilityDecision:
    record_id: str
    classification: AvailabilityClassification
    available_at: datetime | None
    availability_source: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class PointInTimeDataResult[T]:
    records: tuple[T, ...]
    decisions: tuple[AvailabilityDecision, ...]
    warnings: tuple[str, ...]
    policy_version: str

    @property
    def requested_count(self) -> int:
        return len(self.decisions)

    @property
    def available_count(self) -> int:
        return sum(
            item.classification is AvailabilityClassification.AVAILABLE for item in self.decisions
        )

    @property
    def excluded_future_count(self) -> int:
        return sum(
            item.classification is AvailabilityClassification.NOT_YET_AVAILABLE
            for item in self.decisions
        )

    @property
    def unknown_count(self) -> int:
        return sum(
            item.classification is AvailabilityClassification.UNKNOWN_AVAILABILITY
            for item in self.decisions
        )


class DataAvailabilityPolicy:
    VERSION = "point-in-time-availability/v1"

    def daily_bar(
        self, value: PersistedDailyBar, context: PointInTimeContext
    ) -> AvailabilityDecision:
        record = value.record
        if context.availability_mode is AvailabilityMode.OPERATIONAL_REPLAY:
            return self._at(record.record_id, record.ingested_at, "ingested_at", context)
        return self._at(
            record.record_id,
            record.provenance.provider_timestamp,
            "provider_timestamp",
            context,
        )

    def corporate_action(
        self, value: CorporateAction, context: PointInTimeContext
    ) -> AvailabilityDecision:
        return self._retrieved(
            value.action_id, value.retrieved_at, value.provenance.provider_timestamp, context
        )

    def adjustment_factor(
        self, value: AdjustmentFactor, context: PointInTimeContext
    ) -> AvailabilityDecision:
        return self._retrieved(
            value.factor_id, value.retrieved_at, value.provenance.provider_timestamp, context
        )

    def instrument_master(
        self, value: InstrumentMaster, context: PointInTimeContext
    ) -> AvailabilityDecision:
        return self._retrieved(
            value.instrument.canonical_key,
            value.retrieved_at,
            value.provenance.provider_timestamp,
            context,
        )

    def trading_status(
        self, value: InstrumentTradingStatus, context: PointInTimeContext
    ) -> AvailabilityDecision:
        return self._retrieved(
            f"{value.instrument.canonical_key}:{value.trading_date}",
            value.retrieved_at,
            value.provenance.provider_timestamp,
            context,
        )

    def calendar(
        self, value: TradingSessionDay, context: PointInTimeContext
    ) -> AvailabilityDecision:
        if context.availability_mode is AvailabilityMode.HISTORICAL_RESEARCH:
            return AvailabilityDecision(
                value.identity,
                AvailabilityClassification.AVAILABLE,
                None,
                "ex_ante_calendar_policy",
                self.VERSION,
            )
        return self._at(value.identity, value.retrieved_at, "retrieved_at", context)

    def _retrieved(
        self,
        record_id: str,
        retrieved_at: datetime,
        provider_timestamp: datetime | None,
        context: PointInTimeContext,
    ) -> AvailabilityDecision:
        if context.availability_mode is AvailabilityMode.OPERATIONAL_REPLAY:
            return self._at(record_id, retrieved_at, "retrieved_at", context)
        return self._at(record_id, provider_timestamp, "provider_timestamp", context)

    def _at(
        self,
        record_id: str,
        available_at: datetime | None,
        source: str,
        context: PointInTimeContext,
    ) -> AvailabilityDecision:
        if available_at is None:
            return AvailabilityDecision(
                record_id,
                AvailabilityClassification.UNKNOWN_AVAILABILITY,
                None,
                source,
                self.VERSION,
            )
        classification = (
            AvailabilityClassification.AVAILABLE
            if available_at <= context.as_of
            else AvailabilityClassification.NOT_YET_AVAILABLE
        )
        return AvailabilityDecision(record_id, classification, available_at, source, self.VERSION)
