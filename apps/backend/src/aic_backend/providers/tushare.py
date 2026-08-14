"""Infrastructure-owned Tushare Pro A-share daily Provider."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from aic_backend.provider_runtime.errors import (
    AuthenticationConfigurationError,
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
from aic_backend.shared.config import get_settings

TUSHARE_DAILY = ProviderCapability("market.daily.read", "1.0.0", CapabilityMode.BATCH)
TUSHARE_IMPLEMENTATION = "providers.tushare_daily"


class JsonHttpClient(Protocol):
    async def post(
        self, url: str, *, json: Mapping[str, Any], timeout: float
    ) -> httpx.Response: ...


class TushareDailyProvider:
    endpoint = "https://api.tushare.pro"

    def __init__(
        self, definition: ProviderDefinition, token: str | None,
        client: JsonHttpClient | None = None,
    ) -> None:
        self._definition = definition
        self._token = token.strip() if token else None
        self._client = client or httpx.AsyncClient()
        self._initialized = False

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            self._definition.provider_id, "Tushare Pro Daily", ProviderType.MARKET_DATA,
            "1.0.0", vendor="Tushare", priority=self._definition.priority,
            enabled=self._definition.enabled,
        )

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset({TUSHARE_DAILY})

    async def initialize(self) -> None:
        if self._token is None:
            raise AuthenticationConfigurationError(
                "Tushare credential is not configured.", provider_id=self.metadata.provider_id
            )
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await close()

    async def health_check(self) -> HealthCheckResult:
        status = HealthStatus.HEALTHY if self._initialized else HealthStatus.UNHEALTHY
        message = "configuration ready" if self._initialized else "not initialized"
        return HealthCheckResult(status, datetime.now(UTC), message=message)

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResponse:
        if not self._initialized or self._token is None:
            raise AuthenticationConfigurationError("Tushare credential is unavailable.")
        body = {
            "api_name": "daily", "token": self._token,
            "params": self._parameters(request.payload),
            "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        }
        try:
            response = await self._client.post(
                self.endpoint, json=body, timeout=request.timeout_ms / 1000
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("Tushare request timed out.") from error
        except httpx.HTTPError as error:
            raise ProviderUnavailableError("Tushare service is unavailable.") from error
        try:
            data = response.json()
        except ValueError as error:
            raise ProviderInvalidResponseError("Tushare response is malformed.") from error
        if not isinstance(data, Mapping):
            raise ProviderInvalidResponseError("Tushare response is malformed.")
        if data.get("code") != 0:
            message = str(data.get("msg", ""))
            if "频率" in message or "rate" in message.casefold():
                raise ProviderRateLimitedError("Tushare rate limit was reached.")
            if "权限" in message or "permission" in message.casefold():
                raise UserPermissionError("Tushare permission was denied.")
            raise AuthenticationConfigurationError("Tushare authentication failed.")
        payload = data.get("data")
        if not isinstance(payload, Mapping):
            raise ProviderInvalidResponseError("Tushare data envelope is malformed.")
        fields, items = payload.get("fields"), payload.get("items")
        if not isinstance(fields, list) or not isinstance(items, list):
            raise ProviderInvalidResponseError("Tushare rows are malformed.")
        try:
            rows = [
                {str(key): str(value) if isinstance(value, float) else value
                 for key, value in zip(fields, item, strict=True)}
                for item in items
            ]
        except (TypeError, ValueError) as error:
            raise ProviderInvalidResponseError("Tushare rows are malformed.") from error
        return ProviderInvocationResponse({"rows": rows})

    @staticmethod
    def _parameters(payload: Mapping[str, Any]) -> dict[str, str]:
        allowed = ("ts_code", "trade_date", "start_date", "end_date")
        result = {key: str(payload[key]) for key in allowed if payload.get(key)}
        if "ts_code" not in result and "trade_date" not in result:
            raise InvalidRequestError("Tushare daily requires ts_code or trade_date.")
        return result


def build_tushare_daily_provider(definition: ProviderDefinition) -> TushareDailyProvider:
    """Controlled Factory builder; credentials remain environment-owned."""

    return TushareDailyProvider(definition, get_settings().tushare_token)
