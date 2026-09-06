"""ETF ingestion persistence and point-in-time read orchestration."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    DataAvailabilityPolicy,
    PointInTimeContext,
)
from aic_backend.application.ports.corporate_actions import AdjustmentFactorRepository
from aic_backend.application.ports.etf import ETFDataRepository
from aic_backend.application.ports.instruments import InstrumentMasterRepository
from aic_backend.application.ports.persistence import (
    CanonicalDailyBarRepository,
    PersistedDailyBar,
    SaveResult,
)
from aic_backend.domain.market_data import (
    AdjustmentFactor,
    ETFInstrumentProfile,
    ETFMasterBundle,
    ETFTracksIndex,
    ETFValuationSnapshot,
    IndexReference,
    InstrumentExecutionProfile,
    InstrumentIdentity,
)


@dataclass(frozen=True, slots=True)
class ETFMasterSaveResult:
    master: SaveResult
    profile: SaveResult
    relationship: SaveResult | None


@dataclass(frozen=True, slots=True)
class TrackingDifference:
    etf_return: Decimal
    benchmark_return: Decimal
    difference: Decimal
    sample_count: int
    policy_version: str


def calculate_tracking_difference(
    etf_start: Decimal,
    etf_end: Decimal,
    benchmark_start: Decimal,
    benchmark_end: Decimal,
    *,
    policy_version: str = "same-date-close-return/v1",
) -> TrackingDifference:
    if min(etf_start, etf_end, benchmark_start, benchmark_end) <= 0:
        raise ValueError("tracking-difference inputs must be positive")
    if not policy_version.strip():
        raise ValueError("policy_version must not be empty")
    etf_return = etf_end / etf_start - 1
    benchmark_return = benchmark_end / benchmark_start - 1
    return TrackingDifference(
        etf_return,
        benchmark_return,
        etf_return - benchmark_return,
        2,
        policy_version,
    )


class ETFDataIngestionService:
    def __init__(
        self,
        etf_data: ETFDataRepository,
        instruments: InstrumentMasterRepository,
        daily_bars: CanonicalDailyBarRepository,
        factors: AdjustmentFactorRepository,
    ) -> None:
        self._etf_data = etf_data
        self._instruments = instruments
        self._daily_bars = daily_bars
        self._factors = factors

    async def save_master(self, value: ETFMasterBundle) -> ETFMasterSaveResult:
        master = await self._instruments.save(value.master)
        profile = await self._etf_data.save_etf_profile(value.profile)
        relationship = (
            None
            if value.relationship is None
            else await self._etf_data.save_relationship(value.relationship)
        )
        return ETFMasterSaveResult(master, profile, relationship)

    async def save_index_reference(self, value: IndexReference) -> SaveResult:
        return await self._etf_data.save_index_reference(value)

    async def save_daily_bar(self, value: PersistedDailyBar) -> SaveResult:
        return await self._daily_bars.save(value)

    async def save_adjustment_factor(self, value: AdjustmentFactor) -> SaveResult:
        return await self._factors.save(value)

    async def save_valuation(self, value: ETFValuationSnapshot) -> SaveResult:
        return await self._etf_data.save_valuation(value)

    async def save_execution_profile(self, value: InstrumentExecutionProfile) -> SaveResult:
        return await self._etf_data.save_execution_profile(value)


class ETFPointInTimeService:
    def __init__(self, repository: ETFDataRepository, policy: DataAvailabilityPolicy) -> None:
        self._repository = repository
        self._policy = policy

    async def profile_as_of(
        self, instrument: InstrumentIdentity, context: PointInTimeContext
    ) -> ETFInstrumentProfile | None:
        value = await self._repository.get_etf_profile(instrument)
        if value is None:
            return None
        decision = self._policy.etf_profile(value, context)
        return value if decision.classification is AvailabilityClassification.AVAILABLE else None

    async def execution_profile_as_of(
        self,
        instrument: InstrumentIdentity,
        trading_date: date,
        context: PointInTimeContext,
    ) -> InstrumentExecutionProfile | None:
        profiles = await self._repository.list_execution_profiles(instrument)
        eligible = (
            value
            for value in profiles
            if value.effective_from <= trading_date
            and self._policy.execution_profile(value, context).classification
            is AvailabilityClassification.AVAILABLE
        )
        return max(
            eligible,
            key=lambda value: (value.effective_from, value.available_at),
            default=None,
        )

    async def relationship_as_of(
        self, instrument: InstrumentIdentity, trading_date: date, context: PointInTimeContext
    ) -> ETFTracksIndex | None:
        values = await self._repository.list_relationships(instrument)
        eligible = (
            value
            for value in values
            if (value.effective_from is None or value.effective_from <= trading_date)
            and (value.effective_to is None or trading_date <= value.effective_to)
            and self._policy.etf_relationship(value, context).classification
            is AvailabilityClassification.AVAILABLE
        )
        return max(eligible, key=lambda value: value.available_at, default=None)

    async def valuation_as_of(
        self, instrument: InstrumentIdentity, trading_date: date, context: PointInTimeContext
    ) -> ETFValuationSnapshot | None:
        values = await self._repository.list_valuations(
            instrument, trading_date, trading_date
        )
        eligible = (
            value
            for value in values
            if self._policy.etf_valuation(value, context).classification
            is AvailabilityClassification.AVAILABLE
        )
        return max(eligible, key=lambda value: value.available_at, default=None)

    async def index_reference_as_of(
        self, identity: InstrumentIdentity, context: PointInTimeContext
    ) -> IndexReference | None:
        value = await self._repository.get_index_reference(identity)
        if value is None:
            return None
        decision = self._policy.index_reference(value, context)
        return value if decision.classification is AvailabilityClassification.AVAILABLE else None
