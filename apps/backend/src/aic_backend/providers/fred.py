"""Official FRED/ALFRED adapter using the existing Provider Runtime contract."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time
from typing import Protocol

import httpx

from aic_backend.shared.config import get_settings
from aic_backend.provider_runtime.errors import (
    InvalidRequestError,
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UserPermissionError,
)
from aic_backend.provider_runtime.models import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderDefinition,
    ProviderInvocationRequest,
    ProviderInvocationResponse,
    ProviderMetadata,
    ProviderType,
)

MACRO_SERIES_READ = ProviderCapability("macro.series.read", "1.0.0", CapabilityMode.SNAPSHOT)
MACRO_RELEASE_READ = ProviderCapability("macro.release.read", "1.0.0", CapabilityMode.SNAPSHOT)
MACRO_VINTAGE_READ = ProviderCapability("macro.vintage.read", "1.0.0", CapabilityMode.BATCH)
FRED_IMPLEMENTATION = "providers.fred_official"
_BASE_URL = "https://api.stlouisfed.org/fred"


class HttpGetClient(Protocol):
    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float | bool | None],
        timeout: float,
    ) -> httpx.Response: ...


class FredProvider:
    def __init__(
        self,
        definition: ProviderDefinition,
        api_key: str | None,
        *,
        client: HttpGetClient | None = None,
    ) -> None:
        self._definition, self._api_key = definition, api_key
        self._client = client or httpx.AsyncClient()
        self._initialized = False

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            self._definition.provider_id,
            "FRED/ALFRED Official API",
            ProviderType.MACRO,
            "1.0.0",
            vendor="Federal Reserve Bank of St. Louis",
            priority=self._definition.priority,
            enabled=self._definition.enabled,
            tags=frozenset({"official", "vintage", "pit"}),
        )

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return self._definition.capabilities

    async def initialize(self) -> None:
        if self._definition.enabled and not self._api_key:
            raise UserPermissionError("FRED API key is required for an enabled provider.")
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await close()

    async def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            HealthStatus.HEALTHY if self._initialized and self._api_key else HealthStatus.UNKNOWN,
            datetime.now(UTC),
            message="configured" if self._api_key else "api-key-required",
        )

    async def _json(
        self,
        path: str,
        params: Mapping[str, str | int | float | bool | None],
        timeout_ms: int,
    ) -> Mapping[str, object]:
        if not self._api_key:
            raise UserPermissionError("FRED API key is not configured.")
        owned = {**params, "api_key": self._api_key, "file_type": "json"}
        try:
            response = await self._client.get(
                f"{_BASE_URL}/{path}", params=owned, timeout=timeout_ms / 1000
            )
            if response.status_code == 429:
                raise ProviderRateLimitedError("FRED rate limit was reached.")
            response.raise_for_status()
        except ProviderRateLimitedError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("FRED request timed out.") from error
        except httpx.HTTPError as error:
            raise ProviderUnavailableError("FRED API is unavailable.") from error
        if len(response.content) > 2_000_000:
            raise ProviderInvalidResponseError("FRED response exceeds the payload limit.")
        try:
            value = response.json()
        except ValueError as error:
            raise ProviderInvalidResponseError("FRED returned malformed JSON.") from error
        if not isinstance(value, Mapping):
            raise ProviderInvalidResponseError("FRED response must be an object.")
        return value

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResponse:
        if not self._initialized:
            raise ProviderUnavailableError("FRED provider is not initialized.")
        if request.capability not in {MACRO_SERIES_READ, MACRO_RELEASE_READ, MACRO_VINTAGE_READ}:
            raise InvalidRequestError("FRED capability is unsupported.")
        series_id = str(request.payload.get("series_id", "")).strip().upper()
        if (
            not series_id
            or len(series_id) > 64
            or not all(c.isalnum() or c in "-_." for c in series_id)
        ):
            raise InvalidRequestError("FRED series_id is invalid.")
        common = {"series_id": series_id}
        if request.capability is MACRO_SERIES_READ:
            return ProviderInvocationResponse(
                await self._json("series", common, request.timeout_ms)
            )
        if request.capability is MACRO_RELEASE_READ:
            return ProviderInvocationResponse(
                await self._json("series/release", common, request.timeout_ms)
            )
        offset = int(str(request.payload.get("cursor") or "0"))
        if offset < 0:
            raise InvalidRequestError("FRED cursor must be non-negative.")
        params: dict[str, str | int | float | bool | None] = {
            **common,
            "output_type": 4,
            "offset": offset,
            "limit": 1000,
            "sort_order": "asc",
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
        }
        watermark = request.payload.get("watermark")
        if isinstance(watermark, str) and watermark:
            params["realtime_start"] = watermark[:10]
        series_json = await self._json("series", common, request.timeout_ms)
        observations_json = await self._json("series/observations", params, request.timeout_ms)
        vintages_json = await self._json("series/vintagedates", common, request.timeout_ms)
        series_rows, observation_rows = (
            series_json.get("seriess"),
            observations_json.get("observations"),
        )
        if (
            not isinstance(series_rows, list)
            or len(series_rows) != 1
            or not isinstance(series_rows[0], Mapping)
            or not isinstance(observation_rows, list)
        ):
            raise ProviderInvalidResponseError("FRED response schema is invalid.")
        row = series_rows[0]
        frequency = str(row.get("frequency_short", ""))
        adjustment = str(row.get("seasonal_adjustment_short", "NA")) or "NA"
        owned_rows: list[dict[str, object]] = []
        latest_source: datetime | None = None
        for value in observation_rows:
            if not isinstance(value, Mapping):
                raise ProviderInvalidResponseError("FRED observation schema is invalid.")
            realtime_start = str(value.get("realtime_start", ""))
            try:
                source_time = datetime.combine(
                    datetime.fromisoformat(realtime_start).date(), time.min, tzinfo=UTC
                )
            except ValueError as error:
                raise ProviderInvalidResponseError("FRED realtime_start is invalid.") from error
            latest_source = max(latest_source, source_time) if latest_source else source_time
            owned_rows.append(
                {
                    "date": str(value.get("date", "")),
                    "value": str(value.get("value", "")),
                    "realtime_start": realtime_start,
                    "realtime_end": str(value.get("realtime_end", "")),
                    "release_at": realtime_start,
                }
            )
        count = int(str(observations_json.get("count", len(owned_rows))))
        limit = int(str(observations_json.get("limit", 1000)))
        next_cursor = str(offset + limit) if offset + limit < count else None
        vintage_value = vintages_json.get("vintage_dates", ())
        if not isinstance(vintage_value, Sequence) or isinstance(vintage_value, str):
            raise ProviderInvalidResponseError("FRED vintage response schema is invalid.")
        payload: dict[str, object] = {
            "series": {
                "series_id": series_id,
                "title": str(row.get("title", series_id)),
                "geography": str(request.payload.get("geography", "GLOBAL")),
                "source_agency_id": str(request.payload.get("source_agency_id", "UNKNOWN")),
                "unit": str(row.get("units", "UNKNOWN")),
                "frequency": frequency,
                "seasonal_adjustment": adjustment,
            },
            "observations": owned_rows,
            "vintage_dates": tuple(str(item) for item in vintage_value),
            "next_cursor": next_cursor,
        }
        return ProviderInvocationResponse(payload, latest_source)


def build_fred_provider(definition: ProviderDefinition) -> FredProvider:
    configured = get_settings().fred_api_key
    api_key = configured.strip() if configured and configured.strip() else None
    if definition.enabled and api_key is None:
        raise ValueError("enabled FRED provider requires api_key")
    return FredProvider(definition, api_key)
