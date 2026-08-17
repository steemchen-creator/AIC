"""Provider adapters."""

from aic_backend.providers.mock import MockDataProvider
from aic_backend.providers.tushare import TUSHARE_CALENDAR

__all__ = ["MockDataProvider", "TUSHARE_CALENDAR"]
