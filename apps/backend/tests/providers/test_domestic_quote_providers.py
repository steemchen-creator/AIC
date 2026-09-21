from datetime import UTC, datetime

import httpx
import pytest

from aic_backend.provider_runtime import (
    ProviderDefinition,
    ProviderInvocationRequest,
)
from aic_backend.provider_runtime.errors import (
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    UserPermissionError,
)
from aic_backend.providers.domestic_quotes import (
    MARKET_QUOTE_REALTIME,
    DomesticQuoteProvider,
    QuoteUpstream,
    build_eastmoney_quote_provider,
)

NOW = datetime(2026, 9, 21, 7, tzinfo=UTC)


def definition(
    provider_id: str = "eastmoney_quote", *, enabled: bool = True, authorized: bool = True
) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id,
        "providers.eastmoney_quote",
        enabled,
        10,
        frozenset({MARKET_QUOTE_REALTIME}),
        {"upstream_access_authorized": authorized},
    )


def request(provider_id: str) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        "request-1",
        provider_id,
        MARKET_QUOTE_REALTIME,
        {"market": "CN.SSE", "symbol": "600000", "instrument_type": "EQUITY"},
        1000,
        NOW,
    )


def index_request(provider_id: str) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        "request-index",
        provider_id,
        MARKET_QUOTE_REALTIME,
        {
            "market": "REFERENCE.INDEX",
            "symbol": "000001-SH",
            "instrument_type": "INDEX",
        },
        1000,
        NOW,
    )


class ResponseClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def get(self, url: str, *, timeout: float) -> httpx.Response:
        assert url.startswith("https://")
        assert timeout == 1
        return self.response


@pytest.mark.asyncio
async def test_eastmoney_fixture_maps_owned_quote_contract() -> None:
    response = httpx.Response(
        200,
        json={
            "data": {
                "f57": "600000",
                "f43": 1023,
                "f19": 1022,
                "f20": 1024,
                "f60": 1010,
                "f47": 1234,
                "f48": 1260000,
                "f86": 1789974000,
            }
        },
        request=httpx.Request("GET", "https://example.test"),
    )
    provider = DomesticQuoteProvider(
        definition(),
        QuoteUpstream.EASTMONEY,
        access_authorized=True,
        client=ResponseClient(response),
    )
    await provider.initialize()
    result = await provider.invoke(request("eastmoney_quote"))
    assert result.payload["last"] == "10.23"
    assert result.payload["symbol"] == "600000"


@pytest.mark.asyncio
async def test_index_quote_preserves_non_tradable_reference_identity() -> None:
    response = httpx.Response(
        200,
        json={
            "data": {
                "f57": "000001",
                "f43": 320000,
                "f19": 319999,
                "f20": 320001,
                "f60": 318000,
                "f47": 100,
                "f48": 1000,
                "f86": 1789974000,
            }
        },
        request=httpx.Request("GET", "https://example.test"),
    )
    provider = DomesticQuoteProvider(
        definition(),
        QuoteUpstream.EASTMONEY,
        access_authorized=True,
        client=ResponseClient(response),
    )
    await provider.initialize()
    result = await provider.invoke(index_request("eastmoney_quote"))
    assert result.payload["market"] == "REFERENCE.INDEX"
    assert result.payload["symbol"] == "000001-SH"
    assert result.payload["instrument_type"] == "INDEX"


@pytest.mark.asyncio
async def test_sina_and_tencent_contract_fixtures() -> None:
    sina = ["name", "10", "9.8", "10.1", "10.2", "9.7", "0", "0", "100", "1000"]
    sina.extend(["0"] * 22)
    sina[11], sina[21], sina[30], sina[31] = "10.0", "10.2", "2026-09-21", "15:00:00"
    sina_text = 'var hq_str_sh600000="' + ",".join(sina) + '";'
    tencent = ["0"] * 39
    tencent[0], tencent[1], tencent[2] = "1", "name", "600000"
    tencent[3], tencent[4], tencent[6] = "10.1", "9.8", "100"
    tencent[9], tencent[19], tencent[30], tencent[37] = "10.0", "10.2", "20260921150000", "1000"
    tencent_text = 'v_sh600000="' + "~".join(tencent) + '";'
    for upstream, text in ((QuoteUpstream.SINA, sina_text), (QuoteUpstream.TENCENT, tencent_text)):
        response = httpx.Response(
            200, text=text, request=httpx.Request("GET", "https://example.test")
        )
        provider = DomesticQuoteProvider(
            definition(f"{upstream.value}_quote"),
            upstream,
            access_authorized=True,
            client=ResponseClient(response),
        )
        await provider.initialize()
        result = await provider.invoke(request(f"{upstream.value}_quote"))
        assert result.payload["last"] == "10.1"


@pytest.mark.asyncio
async def test_malformed_empty_truncated_and_rate_limited_responses_fail_closed() -> None:
    malformed = httpx.Response(
        200, text="truncated", request=httpx.Request("GET", "https://example.test")
    )
    provider = DomesticQuoteProvider(
        definition("sina_quote"),
        QuoteUpstream.SINA,
        access_authorized=True,
        client=ResponseClient(malformed),
    )
    await provider.initialize()
    with pytest.raises(ProviderInvalidResponseError):
        await provider.invoke(request("sina_quote"))

    rate_limited = httpx.Response(429, request=httpx.Request("GET", "https://example.test"))
    provider = DomesticQuoteProvider(
        definition(),
        QuoteUpstream.EASTMONEY,
        access_authorized=True,
        client=ResponseClient(rate_limited),
    )
    await provider.initialize()
    with pytest.raises(ProviderRateLimitedError):
        await provider.invoke(request("eastmoney_quote"))


@pytest.mark.asyncio
async def test_production_activation_requires_separate_upstream_authorization() -> None:
    with pytest.raises(ValueError, match="upstream_access_authorized"):
        build_eastmoney_quote_provider(definition(authorized=False))
    provider = DomesticQuoteProvider(
        definition(enabled=False, authorized=False),
        QuoteUpstream.EASTMONEY,
        access_authorized=False,
    )
    await provider.initialize()
    with pytest.raises(UserPermissionError):
        await provider.invoke(request("eastmoney_quote"))
