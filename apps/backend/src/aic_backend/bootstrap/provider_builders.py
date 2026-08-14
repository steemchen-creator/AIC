"""Explicit production Provider builder allowlist."""

from aic_backend.provider_runtime import ProviderBuilder
from aic_backend.providers.tushare import (
    TUSHARE_IMPLEMENTATION,
    build_tushare_daily_provider,
)


def provider_builders() -> dict[str, ProviderBuilder]:
    return {TUSHARE_IMPLEMENTATION: build_tushare_daily_provider}
