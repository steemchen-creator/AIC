"""Deterministic adjusted DailyBar projections over immutable canonical facts."""

from decimal import Decimal

from aic_backend.application.ports.corporate_actions import AdjustmentFactorRepository
from aic_backend.application.ports.persistence import PersistedDailyBar
from aic_backend.domain.market_data.corporate_actions import AdjustedDailyBar, AdjustmentMode


class AdjustmentCoverageIncomplete(RuntimeError):
    """Requested adjusted series lacks an authoritative factor for every raw bar."""


class AdjustmentService:
    version = "a-share-adjustment/v1"

    def __init__(self, factors: AdjustmentFactorRepository) -> None:
        self._factors = factors

    async def adjust(
        self, bars: tuple[PersistedDailyBar, ...], mode: AdjustmentMode
    ) -> tuple[AdjustedDailyBar, ...]:
        if not bars:
            return ()
        if mode is AdjustmentMode.RAW:
            return tuple(self._project(item, mode, Decimal("1")) for item in bars)
        instrument = bars[0].record.instrument
        start, end = bars[0].record.trading_date, bars[-1].record.trading_date
        factors = await self._factors.list_adjustment_factors(instrument, start, end)
        by_date = {item.trading_date: item.factor for item in factors}
        if any(item.record.trading_date not in by_date for item in bars):
            raise AdjustmentCoverageIncomplete("ADJUSTMENT_COVERAGE_INCOMPLETE")
        anchor = by_date[end]
        return tuple(
            self._project(
                item,
                mode,
                by_date[item.record.trading_date] / anchor
                if mode is AdjustmentMode.FORWARD_ADJUSTED
                else by_date[item.record.trading_date],
            )
            for item in bars
        )

    def _project(
        self, item: PersistedDailyBar, mode: AdjustmentMode, multiplier: Decimal
    ) -> AdjustedDailyBar:
        record = item.record
        return AdjustedDailyBar(
            f"{record.record_id}:{mode.value}:{self.version}",
            record.record_id,
            record.instrument,
            record.trading_date,
            mode,
            record.open * multiplier,
            record.high * multiplier,
            record.low * multiplier,
            record.close * multiplier,
            record.volume,
            record.turnover,
            multiplier,
            self.version,
        )
