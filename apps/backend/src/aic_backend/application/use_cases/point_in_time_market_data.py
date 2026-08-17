"""Application-owned point-in-time market-data façade."""

from collections.abc import Callable, Sequence
from datetime import date
from typing import TypeVar

from aic_backend.application.point_in_time import (
    AvailabilityClassification,
    AvailabilityDecision,
    DataAvailabilityPolicy,
    PointInTimeContext,
    PointInTimeDataResult,
)
from aic_backend.application.ports.calendar import TradingCalendarRepository
from aic_backend.application.ports.corporate_actions import (
    AdjustmentFactorRepository,
    CorporateActionRepository,
)
from aic_backend.application.ports.instruments import (
    InstrumentMasterRepository,
    InstrumentTradingStatusRepository,
)
from aic_backend.application.ports.persistence import (
    CanonicalDailyBarRepository,
    PersistedDailyBar,
)
from aic_backend.domain.market_data import (
    AdjustmentFactor,
    AdjustmentMode,
    CorporateAction,
    InstrumentIdentity,
    InstrumentTradingStatus,
    Market,
    TradingSessionDay,
)

T = TypeVar("T")


class PointInTimeAdjustmentUnsupported(ValueError):
    pass


class PointInTimeMarketDataService:
    def __init__(
        self,
        daily_bars: CanonicalDailyBarRepository,
        factors: AdjustmentFactorRepository,
        actions: CorporateActionRepository,
        instruments: InstrumentMasterRepository,
        trading_statuses: InstrumentTradingStatusRepository,
        calendar: TradingCalendarRepository,
        policy: DataAvailabilityPolicy,
    ) -> None:
        self._daily_bars = daily_bars
        self._factors = factors
        self._actions = actions
        self._instruments = instruments
        self._trading_statuses = trading_statuses
        self._calendar = calendar
        self._policy = policy

    async def get_daily_bars_as_of(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
        context: PointInTimeContext,
    ) -> PointInTimeDataResult[PersistedDailyBar]:
        if context.adjustment_mode is not AdjustmentMode.RAW:
            raise PointInTimeAdjustmentUnsupported(
                "point-in-time adjusted DailyBars are unsupported in V1; use RAW"
            )
        values = await self._daily_bars.get_daily_bars(instrument, start, end)
        return self._filter(values, lambda value: self._policy.daily_bar(value, context))

    async def list_corporate_actions_as_of(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
        context: PointInTimeContext,
    ) -> PointInTimeDataResult[CorporateAction]:
        values = await self._actions.list_corporate_actions(instrument, start, end)
        return self._filter(values, lambda value: self._policy.corporate_action(value, context))

    async def list_adjustment_factors_as_of(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
        context: PointInTimeContext,
    ) -> PointInTimeDataResult[AdjustmentFactor]:
        values = await self._factors.list_adjustment_factors(instrument, start, end)
        return self._filter(values, lambda value: self._policy.adjustment_factor(value, context))

    async def list_trading_status_as_of(
        self,
        instrument: InstrumentIdentity,
        start: date,
        end: date,
        context: PointInTimeContext,
    ) -> PointInTimeDataResult[InstrumentTradingStatus]:
        values = await self._trading_statuses.list_trading_status(instrument, start, end)
        return self._filter(values, lambda value: self._policy.trading_status(value, context))

    async def list_calendar_as_of(
        self,
        market: Market,
        start: date,
        end: date,
        context: PointInTimeContext,
    ) -> PointInTimeDataResult[TradingSessionDay]:
        values = await self._calendar.list_days(market, start, end)
        return self._filter(values, lambda value: self._policy.calendar(value, context))

    async def list_instruments_as_of(
        self,
        lifecycle_date: date,
        context: PointInTimeContext,
        market: Market | None = None,
    ) -> PointInTimeDataResult[InstrumentIdentity]:
        masters = await self._instruments.list_instruments(market)
        records: list[InstrumentIdentity] = []
        decisions: list[AvailabilityDecision] = []
        warnings: list[str] = []
        for value in masters:
            record_id = value.instrument.canonical_key
            if value.listing_date is None:
                decisions.append(
                    AvailabilityDecision(
                        record_id,
                        AvailabilityClassification.UNKNOWN_AVAILABILITY,
                        None,
                        "missing_listing_date",
                        self._policy.VERSION,
                    )
                )
                continue
            if lifecycle_date < value.listing_date:
                decisions.append(
                    AvailabilityDecision(
                        record_id,
                        AvailabilityClassification.NOT_YET_AVAILABLE,
                        None,
                        "listing_date",
                        self._policy.VERSION,
                    )
                )
                continue
            master_decision = self._policy.instrument_master(value, context)
            known_delisted = (
                value.delisting_date is not None
                and lifecycle_date > value.delisting_date
                and master_decision.classification is AvailabilityClassification.AVAILABLE
            )
            if known_delisted:
                decisions.append(
                    AvailabilityDecision(
                        record_id,
                        AvailabilityClassification.NOT_YET_AVAILABLE,
                        master_decision.available_at,
                        "known_delisting_date",
                        self._policy.VERSION,
                    )
                )
                continue
            records.append(value.instrument)
            decisions.append(
                AvailabilityDecision(
                    record_id,
                    AvailabilityClassification.AVAILABLE,
                    master_decision.available_at,
                    "listing_lifecycle",
                    self._policy.VERSION,
                )
            )
            if value.delisting_date is not None and lifecycle_date > value.delisting_date:
                warnings.append(f"{record_id}: delisting knowledge unavailable as_of")
        return PointInTimeDataResult(
            tuple(records), tuple(decisions), tuple(warnings), self._policy.VERSION
        )

    def _filter(
        self, values: Sequence[T], decide: Callable[[T], AvailabilityDecision]
    ) -> PointInTimeDataResult[T]:
        decisions = tuple(decide(value) for value in values)
        records = tuple(
            value
            for value, decision in zip(values, decisions, strict=True)
            if decision.classification is AvailabilityClassification.AVAILABLE
        )
        unknown = sum(
            decision.classification is AvailabilityClassification.UNKNOWN_AVAILABILITY
            for decision in decisions
        )
        warnings = () if not unknown else (f"{unknown} record(s) have unknown availability",)
        return PointInTimeDataResult(records, decisions, warnings, self._policy.VERSION)
