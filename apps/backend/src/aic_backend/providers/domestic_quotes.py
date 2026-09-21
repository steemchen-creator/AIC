"""Disabled-by-default domestic public quote adapters for Checkpoint A."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

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

MARKET_QUOTE_REALTIME = ProviderCapability(
    "market.quote.realtime", "1.0.0", CapabilityMode.SNAPSHOT
)
MARKET_QUOTE_SNAPSHOT = ProviderCapability(
    "market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT
)

EASTMONEY_IMPLEMENTATION = "providers.eastmoney_quote"
SINA_IMPLEMENTATION = "providers.sina_quote"
TENCENT_IMPLEMENTATION = "providers.tencent_quote"


class QuoteUpstream(StrEnum):
    EASTMONEY = "eastmoney"
    SINA = "sina"
    TENCENT = "tencent"


class HttpGetClient(Protocol):
    async def get(self, url: str, *, timeout: float) -> httpx.Response: ...


class DomesticQuoteProvider:
    _ENDPOINTS = {
        QuoteUpstream.EASTMONEY: "https://push2.eastmoney.com/api/qt/stock/get?secid={secid}",
        QuoteUpstream.SINA: "https://hq.sinajs.cn/list={exchange}{symbol}",
        QuoteUpstream.TENCENT: "https://qt.gtimg.cn/q={exchange}{symbol}",
    }

    def __init__(
        self,
        definition: ProviderDefinition,
        upstream: QuoteUpstream,
        *,
        access_authorized: bool,
        client: HttpGetClient | None = None,
    ) -> None:
        self._definition = definition
        self._upstream = upstream
        self._access_authorized = access_authorized
        self._client = client or httpx.AsyncClient()
        self._initialized = False

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            self._definition.provider_id,
            f"{self._upstream.value.title()} Domestic Quote",
            ProviderType.MARKET_DATA,
            "1.0.0",
            vendor=self._upstream.value,
            priority=self._definition.priority,
            enabled=self._definition.enabled,
            tags=frozenset({"production-rights-required", "public-market-feed"}),
        )

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return self._definition.capabilities

    async def initialize(self) -> None:
        if self._definition.enabled and not self._access_authorized:
            raise UserPermissionError(
                "Quote source is disabled until machine-access and "
                "commercial-use rights are approved.",
                provider_id=self._definition.provider_id,
            )
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await close()

    async def health_check(self) -> HealthCheckResult:
        status = HealthStatus.HEALTHY if self._initialized else HealthStatus.UNKNOWN
        return HealthCheckResult(
            status, datetime.now(UTC), message="configured" if self._initialized else "disabled"
        )

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResponse:
        if request.capability not in {MARKET_QUOTE_REALTIME, MARKET_QUOTE_SNAPSHOT}:
            raise InvalidRequestError("Domestic quote capability is unsupported.")
        if not self._initialized or not self._access_authorized:
            raise UserPermissionError("Domestic quote upstream access is not authorized.")
        market = str(request.payload.get("market", ""))
        canonical_symbol = str(request.payload.get("symbol", "")).strip().upper()
        instrument_type = str(request.payload.get("instrument_type", ""))
        if market == "REFERENCE.INDEX" and instrument_type == "INDEX":
            parts = canonical_symbol.rsplit("-", 1)
            if len(parts) != 2 or parts[1] not in {"SH", "SZ"}:
                raise InvalidRequestError(
                    "Index reference identity must preserve its upstream exchange suffix."
                )
            symbol, source_market = parts
        else:
            symbol, source_market = canonical_symbol, market
        if (
            source_market not in {"CN.SSE", "CN.SZSE", "SH", "SZ"}
            or not symbol.isdigit()
            or len(symbol) != 6
        ):
            raise InvalidRequestError("Domestic quote requires a canonical A-share identity.")
        if instrument_type not in {"EQUITY", "ETF", "INDEX"}:
            raise InvalidRequestError("Domestic quote instrument type is unsupported.")
        exchange = "sh" if source_market in {"CN.SSE", "SH"} else "sz"
        secid = f"1.{symbol}" if exchange == "sh" else f"0.{symbol}"
        url = self._ENDPOINTS[self._upstream].format(exchange=exchange, symbol=symbol, secid=secid)
        try:
            response = await self._client.get(url, timeout=request.timeout_ms / 1000)
            if response.status_code == 429:
                raise ProviderRateLimitedError("Domestic quote rate limit was reached.")
            response.raise_for_status()
        except ProviderRateLimitedError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("Domestic quote request timed out.") from error
        except httpx.HTTPError as error:
            raise ProviderUnavailableError("Domestic quote service is unavailable.") from error
        if len(response.content) > 1_000_000:
            raise ProviderInvalidResponseError("Domestic quote response exceeds the payload limit.")
        try:
            if self._upstream is QuoteUpstream.EASTMONEY:
                payload = self._parse_eastmoney(response, market, symbol, instrument_type)
            elif self._upstream is QuoteUpstream.SINA:
                payload = self._parse_sina(response.text, market, symbol, instrument_type)
            else:
                payload = self._parse_tencent(response.text, market, symbol, instrument_type)
        except (KeyError, IndexError, InvalidOperation, TypeError, ValueError) as error:
            raise ProviderInvalidResponseError("Domestic quote response is malformed.") from error
        payload["market"] = market
        payload["symbol"] = canonical_symbol
        return ProviderInvocationResponse(
            payload, datetime.fromisoformat(str(payload["event_time"]))
        )

    @staticmethod
    def _common(
        market: str,
        symbol: str,
        instrument_type: str,
        event_time: datetime,
        last: Decimal,
        bid: Decimal | None,
        ask: Decimal | None,
        previous_close: Decimal | None,
        volume: int | None,
        turnover: Decimal | None,
        session_status: str,
    ) -> dict[str, object]:
        if event_time.tzinfo is None or last <= 0:
            raise ValueError("invalid quote")
        return {
            "market": market,
            "symbol": symbol,
            "instrument_type": instrument_type,
            "event_time": event_time.astimezone(UTC).isoformat(),
            "last": str(last),
            "bid": None if bid is None else str(bid),
            "ask": None if ask is None else str(ask),
            "previous_close": None if previous_close is None else str(previous_close),
            "volume": volume,
            "turnover": None if turnover is None else str(turnover),
            "session_status": session_status,
        }

    @classmethod
    def _parse_eastmoney(
        cls, response: httpx.Response, market: str, symbol: str, instrument_type: str
    ) -> dict[str, object]:
        body = response.json()
        if not isinstance(body, Mapping) or not isinstance(body.get("data"), Mapping):
            raise ValueError("missing data")
        data = body["data"]
        if str(data["f57"]) != symbol:
            raise ValueError("identity mismatch")
        scale = Decimal("100")
        event_time = datetime.fromtimestamp(int(data["f86"]), tz=UTC)

        def optional(key: str) -> Decimal | None:
            value = data.get(key)
            return None if value in (None, "-") else Decimal(str(value)) / scale

        return cls._common(
            market,
            symbol,
            instrument_type,
            event_time,
            Decimal(str(data["f43"])) / scale,
            optional("f19"),
            optional("f20"),
            optional("f60"),
            None if data.get("f47") is None else int(data["f47"]),
            None if data.get("f48") is None else Decimal(str(data["f48"])),
            "OPEN",
        )

    @classmethod
    def _parse_sina(
        cls, text: str, market: str, symbol: str, instrument_type: str
    ) -> dict[str, object]:
        prefix = f'var hq_str_{"sh" if market == "CN.SSE" else "sz"}{symbol}="'
        if not text.startswith(prefix) or not text.rstrip().endswith('";'):
            raise ValueError("identity mismatch")
        fields = text[len(prefix) :].rstrip()[:-2].split(",")
        if len(fields) < 32 or not fields[0]:
            raise ValueError("truncated quote")
        local = datetime.fromisoformat(f"{fields[30]}T{fields[31]}").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
        return cls._common(
            market,
            symbol,
            instrument_type,
            local,
            Decimal(fields[3]),
            Decimal(fields[11]),
            Decimal(fields[21]),
            Decimal(fields[2]),
            int(fields[8]),
            Decimal(fields[9]),
            "OPEN",
        )

    @classmethod
    def _parse_tencent(
        cls, text: str, market: str, symbol: str, instrument_type: str
    ) -> dict[str, object]:
        prefix = f'v_{"sh" if market == "CN.SSE" else "sz"}{symbol}="'
        if not text.startswith(prefix) or not text.rstrip().endswith('";'):
            raise ValueError("identity mismatch")
        fields = text[len(prefix) :].rstrip()[:-2].split("~")
        if len(fields) < 39 or fields[2] != symbol:
            raise ValueError("truncated quote")
        local = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
        return cls._common(
            market,
            symbol,
            instrument_type,
            local,
            Decimal(fields[3]),
            Decimal(fields[9]),
            Decimal(fields[19]),
            Decimal(fields[4]),
            int(fields[6]),
            Decimal(fields[37]),
            "OPEN",
        )


def _build(definition: ProviderDefinition, upstream: QuoteUpstream) -> DomesticQuoteProvider:
    authorized = definition.config.get("upstream_access_authorized") is True
    if definition.enabled and not authorized:
        raise ValueError("enabled quote adapter requires upstream_access_authorized=true")
    expected = {MARKET_QUOTE_REALTIME, MARKET_QUOTE_SNAPSHOT}
    if not definition.capabilities or not definition.capabilities <= expected:
        raise ValueError("quote adapter capabilities are invalid")
    return DomesticQuoteProvider(definition, upstream, access_authorized=authorized)


def build_eastmoney_quote_provider(definition: ProviderDefinition) -> DomesticQuoteProvider:
    return _build(definition, QuoteUpstream.EASTMONEY)


def build_sina_quote_provider(definition: ProviderDefinition) -> DomesticQuoteProvider:
    return _build(definition, QuoteUpstream.SINA)


def build_tencent_quote_provider(definition: ProviderDefinition) -> DomesticQuoteProvider:
    return _build(definition, QuoteUpstream.TENCENT)
