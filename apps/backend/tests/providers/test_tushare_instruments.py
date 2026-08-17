from datetime import UTC, datetime

import httpx
import pytest

from aic_backend.provider_runtime import (
    ProviderDefinition,
    ProviderInvocationRequest,
)
from aic_backend.provider_runtime.errors import InvalidRequestError
from aic_backend.providers.tushare import (
    TUSHARE_INSTRUMENT_MASTER,
    TUSHARE_TRADING_STATUS,
    TushareDailyProvider,
)

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def request(capability, payload):
    return ProviderInvocationRequest("req", "tushare", capability, payload, 5000, NOW)


class Client:
    def __init__(self, fields, item):
        self.fields, self.item, self.body = fields, item, None

    async def post(self, url, *, json, timeout):
        self.body = json
        return httpx.Response(
            200,
            content=__import__("json")
            .dumps({"code": 0, "data": {"fields": self.fields, "items": [self.item]}})
            .encode(),
            request=httpx.Request("POST", url),
        )


def definition(*capabilities):
    return ProviderDefinition(
        "tushare", "providers.tushare_daily", True, 1, frozenset(capabilities), {}
    )


@pytest.mark.parametrize(
    ("capability", "payload", "api_name", "params", "fields", "item"),
    [
        (
            TUSHARE_INSTRUMENT_MASTER,
            {"exchange": "SZSE", "list_status": "D"},
            "stock_basic",
            {"exchange": "SZSE", "list_status": "D"},
            ["ts_code", "symbol", "name", "exchange", "list_status", "list_date", "delist_date"],
            ["000001.SZ", "000001", "平安银行", "SZSE", "D", "19910403", "20260817"],
        ),
        (
            TUSHARE_TRADING_STATUS,
            {
                "market": "CN.SSE",
                "symbol": "600000",
                "start_date": "2026-08-01",
                "end_date": "2026-08-17",
            },
            "suspend_d",
            {"ts_code": "600000.SH", "start_date": "20260801", "end_date": "20260817"},
            ["ts_code", "trade_date", "suspend_timing", "suspend_type"],
            ["600000.SH", "20260817", None, "S"],
        ),
    ],
)
async def test_tushare_instrument_capabilities_are_separate(
    capability, payload, api_name, params, fields, item
):
    client = Client(fields, item)
    provider = TushareDailyProvider(definition(capability), "token", client)
    await provider.initialize()
    response = await provider.invoke(request(capability, payload))
    assert client.body["api_name"] == api_name
    assert client.body["params"] == params
    assert response.payload["rows"][0]["ts_code"] == item[0]


@pytest.mark.parametrize(
    "capability,payload",
    [
        (TUSHARE_INSTRUMENT_MASTER, {"exchange": "BSE"}),
        (TUSHARE_INSTRUMENT_MASTER, {"exchange": "SSE", "list_status": "X"}),
        (
            TUSHARE_TRADING_STATUS,
            {"market": "CN.OTHER", "symbol": "1", "start_date": "x", "end_date": "y"},
        ),
        (
            TUSHARE_TRADING_STATUS,
            {"market": "CN.SSE", "symbol": "600000", "start_date": "20260101"},
        ),
    ],
)
async def test_tushare_instrument_parameters_are_strict(capability, payload):
    provider = TushareDailyProvider(definition(capability), "token", Client([], []))
    await provider.initialize()
    with pytest.raises(InvalidRequestError):
        await provider.invoke(request(capability, payload))
