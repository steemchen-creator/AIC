"""Provider adapters."""

from aic_backend.providers.mock import MockDataProvider
from aic_backend.providers.tushare import (
    TUSHARE_ADJUSTMENT_FACTOR,
    TUSHARE_CALENDAR,
    TUSHARE_CORPORATE_ACTION,
    TUSHARE_DAILY,
    TUSHARE_INSTRUMENT_MASTER,
    TUSHARE_TRADING_STATUS,
)

__all__ = [
    "TUSHARE_ADJUSTMENT_FACTOR",
    "TUSHARE_CORPORATE_ACTION",
    "MockDataProvider",
    "TUSHARE_CALENDAR",
    "TUSHARE_DAILY",
    "TUSHARE_INSTRUMENT_MASTER",
    "TUSHARE_TRADING_STATUS",
]
