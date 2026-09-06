"""Infrastructure-owned Tushare Pro market-data Provider."""

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
TUSHARE_CALENDAR = ProviderCapability("market.calendar.read", "1.0.0", CapabilityMode.BATCH)
TUSHARE_INSTRUMENT_MASTER = ProviderCapability(
    "instrument.master.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_TRADING_STATUS = ProviderCapability(
    "instrument.trading_status.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_ADJUSTMENT_FACTOR = ProviderCapability(
    "market.adjustment_factor.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_CORPORATE_ACTION = ProviderCapability(
    "market.corporate_action.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_ETF_MASTER = ProviderCapability(
    "instrument.etf_master.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_ETF_BENCHMARK = ProviderCapability(
    "instrument.etf_benchmark.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_ETF_DAILY = ProviderCapability(
    "market.etf_daily.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_ETF_ADJUSTMENT_FACTOR = ProviderCapability(
    "market.etf_adjustment_factor.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_ETF_VALUATION = ProviderCapability(
    "market.etf_valuation.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_INDEX_REFERENCE = ProviderCapability(
    "market.index_reference.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_INDEX_DAILY = ProviderCapability(
    "market.index_daily.read", "1.0.0", CapabilityMode.BATCH
)
TUSHARE_IMPLEMENTATION = "providers.tushare_daily"


class JsonHttpClient(Protocol):
    async def post(
        self, url: str, *, json: Mapping[str, Any], timeout: float
    ) -> httpx.Response: ...


class TushareDailyProvider:
    endpoint = "https://api.tushare.pro"

    def __init__(
        self,
        definition: ProviderDefinition,
        token: str | None,
        client: JsonHttpClient | None = None,
    ) -> None:
        self._definition = definition
        self._token = token.strip() if token else None
        self._client = client or httpx.AsyncClient()
        self._initialized = False

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            self._definition.provider_id,
            "Tushare Pro Market Data",
            ProviderType.MARKET_DATA,
            "1.0.0",
            vendor="Tushare",
            priority=self._definition.priority,
            enabled=self._definition.enabled,
        )

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return self._definition.capabilities

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
        calendar = request.capability == TUSHARE_CALENDAR
        master = request.capability == TUSHARE_INSTRUMENT_MASTER
        trading_status = request.capability == TUSHARE_TRADING_STATUS
        adjustment_factor = request.capability == TUSHARE_ADJUSTMENT_FACTOR
        corporate_action = request.capability == TUSHARE_CORPORATE_ACTION
        etf_master = request.capability == TUSHARE_ETF_MASTER
        etf_benchmark = request.capability == TUSHARE_ETF_BENCHMARK
        etf_daily = request.capability == TUSHARE_ETF_DAILY
        etf_adjustment = request.capability == TUSHARE_ETF_ADJUSTMENT_FACTOR
        etf_valuation = request.capability == TUSHARE_ETF_VALUATION
        index_reference = request.capability == TUSHARE_INDEX_REFERENCE
        index_daily = request.capability == TUSHARE_INDEX_DAILY
        if (
            not calendar
            and not master
            and not trading_status
            and not adjustment_factor
            and not corporate_action
            and not etf_master
            and not etf_benchmark
            and not etf_daily
            and not etf_adjustment
            and not etf_valuation
            and not index_reference
            and not index_daily
            and request.capability != TUSHARE_DAILY
        ):
            raise InvalidRequestError("Tushare capability is unsupported.")
        if calendar:
            api_name, params = "trade_cal", self._calendar_parameters(request.payload)
            fields = "exchange,cal_date,is_open,pretrade_date"
        elif master:
            api_name, params = "stock_basic", self._instrument_parameters(request.payload)
            fields = "ts_code,symbol,name,exchange,list_status,list_date,delist_date"
        elif trading_status:
            api_name, params = "suspend_d", self._status_parameters(request.payload)
            fields = "ts_code,trade_date,suspend_timing,suspend_type"
        elif adjustment_factor:
            api_name, params = "adj_factor", self._dated_instrument_parameters(request.payload)
            fields = "ts_code,trade_date,adj_factor"
        elif corporate_action:
            api_name, params = "dividend", self._corporate_action_parameters(request.payload)
            fields = (
                "ts_code,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,"
                "cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date"
            )
        elif etf_master:
            api_name, params = "etf_basic", self._etf_master_parameters(request.payload)
            fields = (
                "ts_code,csname,extname,cname,index_code,index_name,setup_date,list_date,"
                "list_status,exchange,mgr_name,custod_name,mgt_fee,etf_type"
            )
        elif etf_benchmark or index_reference:
            api_name, params = "etf_index", self._index_reference_parameters(request.payload)
            fields = (
                "ts_code,indx_name,indx_csname,pub_party_name,pub_date,base_date,bp,adj_circle"
            )
        elif etf_daily:
            api_name, params = "fund_daily", self._parameters(request.payload)
            fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        elif etf_adjustment:
            api_name, params = "fund_adj", self._dated_instrument_parameters(request.payload)
            fields = "ts_code,trade_date,adj_factor"
        elif etf_valuation:
            api_name, params = "etf_share_size", self._parameters(request.payload)
            fields = "trade_date,ts_code,etf_name,total_share,total_size,nav,close,exchange"
        elif index_daily:
            api_name, params = "index_daily", self._parameters(request.payload)
            fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        else:
            api_name, params = "daily", self._parameters(request.payload)
            fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        body = {
            "api_name": api_name,
            "token": self._token,
            "params": params,
            "fields": fields,
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
        response_fields, items = payload.get("fields"), payload.get("items")
        if not isinstance(response_fields, list) or not isinstance(items, list):
            raise ProviderInvalidResponseError("Tushare rows are malformed.")
        try:
            rows = [
                {
                    str(key): str(value) if isinstance(value, float) else value
                    for key, value in zip(response_fields, item, strict=True)
                }
                for item in items
            ]
        except (TypeError, ValueError) as error:
            raise ProviderInvalidResponseError("Tushare rows are malformed.") from error
        return ProviderInvocationResponse({"rows": rows})

    @staticmethod
    def _parameters(payload: Mapping[str, Any]) -> dict[str, str]:
        allowed = ("ts_code", "trade_date", "start_date", "end_date")
        result = {key: str(payload[key]) for key in allowed if payload.get(key)}
        if "ts_code" not in result and payload.get("symbol") and payload.get("market"):
            suffixes = {"CN.SSE": "SH", "CN.SZSE": "SZ"}
            suffix = suffixes.get(str(payload["market"]))
            if suffix is None:
                raise InvalidRequestError("Tushare daily instrument market is unsupported.")
            result["ts_code"] = f"{payload['symbol']}.{suffix}"
        for field in ("trade_date", "start_date", "end_date"):
            if field in result:
                result[field] = result[field].replace("-", "")
        if "ts_code" not in result and "trade_date" not in result:
            raise InvalidRequestError("Tushare daily requires ts_code or trade_date.")
        return result

    @staticmethod
    def _calendar_parameters(payload: Mapping[str, Any]) -> dict[str, str]:
        exchange = str(payload.get("exchange", ""))
        if exchange not in {"SSE", "SZSE"}:
            raise InvalidRequestError("Tushare calendar exchange is unsupported.")
        result = {"exchange": exchange}
        for field in ("start_date", "end_date"):
            if payload.get(field):
                result[field] = str(payload[field]).replace("-", "")
        if "start_date" not in result or "end_date" not in result:
            raise InvalidRequestError("Tushare calendar requires a date range.")
        return result

    @staticmethod
    def _instrument_parameters(payload: Mapping[str, Any]) -> dict[str, str]:
        exchange = str(payload.get("exchange", ""))
        if exchange not in {"SSE", "SZSE"}:
            raise InvalidRequestError("Tushare instrument exchange is unsupported.")
        status = str(payload.get("list_status", "L"))
        if status not in {"L", "D", "P", "G"}:
            raise InvalidRequestError("Tushare listing status is unsupported.")
        return {"exchange": exchange, "list_status": status}

    @staticmethod
    def _etf_master_parameters(payload: Mapping[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        market = str(payload.get("market", ""))
        exchange = {"CN.SSE": "SH", "CN.SZSE": "SZ", "SH": "SH", "SZ": "SZ"}.get(
            market
        )
        if market and exchange is None:
            raise InvalidRequestError("Tushare ETF exchange is unsupported.")
        if exchange is not None:
            result["exchange"] = exchange
        status = str(payload.get("list_status", "L"))
        if status not in {"L", "D", "P"}:
            raise InvalidRequestError("Tushare ETF listing status is unsupported.")
        result["list_status"] = status
        for field in ("ts_code", "index_code", "list_date", "mgr"):
            if payload.get(field):
                result[field] = str(payload[field]).replace("-", "")
        return result

    @staticmethod
    def _index_reference_parameters(payload: Mapping[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for field in ("ts_code", "pub_date", "base_date"):
            if payload.get(field):
                result[field] = str(payload[field]).replace("-", "")
        return result

    @staticmethod
    def _status_parameters(payload: Mapping[str, Any]) -> dict[str, str]:
        market = str(payload.get("market", ""))
        suffix = {"CN.SSE": "SH", "CN.SZSE": "SZ"}.get(market)
        symbol = str(payload.get("symbol", "")).strip()
        if suffix is None or not symbol:
            raise InvalidRequestError("Tushare trading status instrument is unsupported.")
        result = {"ts_code": f"{symbol}.{suffix}"}
        for field in ("start_date", "end_date"):
            value = payload.get(field)
            if not value:
                raise InvalidRequestError("Tushare trading status requires a date range.")
            result[field] = str(value).replace("-", "")
        return result

    @staticmethod
    def _instrument_code(payload: Mapping[str, Any]) -> str:
        market = str(payload.get("market", ""))
        suffix = {"CN.SSE": "SH", "CN.SZSE": "SZ"}.get(market)
        symbol = str(payload.get("symbol", "")).strip()
        if suffix is None or not symbol:
            raise InvalidRequestError("Tushare instrument is unsupported.")
        return f"{symbol}.{suffix}"

    @classmethod
    def _dated_instrument_parameters(cls, payload: Mapping[str, Any]) -> dict[str, str]:
        result = {"ts_code": cls._instrument_code(payload)}
        for field in ("start_date", "end_date"):
            value = payload.get(field)
            if not value:
                raise InvalidRequestError("Tushare adjustment factor requires a date range.")
            result[field] = str(value).replace("-", "")
        return result

    @classmethod
    def _corporate_action_parameters(cls, payload: Mapping[str, Any]) -> dict[str, str]:
        return {"ts_code": cls._instrument_code(payload)}


def build_tushare_daily_provider(definition: ProviderDefinition) -> TushareDailyProvider:
    """Controlled Factory builder; credentials remain environment-owned."""

    return TushareDailyProvider(definition, get_settings().tushare_token)
