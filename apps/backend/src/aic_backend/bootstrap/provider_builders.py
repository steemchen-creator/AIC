"""Explicit production Provider builder allowlist."""

from aic_backend.provider_runtime import ProviderBuilder
from aic_backend.providers.domestic_quotes import (
    EASTMONEY_IMPLEMENTATION,
    SINA_IMPLEMENTATION,
    TENCENT_IMPLEMENTATION,
    build_eastmoney_quote_provider,
    build_sina_quote_provider,
    build_tencent_quote_provider,
)
from aic_backend.providers.fred import FRED_IMPLEMENTATION, build_fred_provider
from aic_backend.providers.tushare import (
    TUSHARE_IMPLEMENTATION,
    build_tushare_daily_provider,
)


def provider_builders() -> dict[str, ProviderBuilder]:
    return {
        TUSHARE_IMPLEMENTATION: build_tushare_daily_provider,
        EASTMONEY_IMPLEMENTATION: build_eastmoney_quote_provider,
        SINA_IMPLEMENTATION: build_sina_quote_provider,
        TENCENT_IMPLEMENTATION: build_tencent_quote_provider,
        FRED_IMPLEMENTATION: build_fred_provider,
    }
