from datetime import UTC, datetime

import httpx
import pytest

from aic_backend.provider_runtime import ProviderDefinition, ProviderInvocationRequest
from aic_backend.provider_runtime.errors import InvalidRequestError
from aic_backend.providers.tushare import (
    TUSHARE_ADJUSTMENT_FACTOR,
    TUSHARE_CORPORATE_ACTION,
    TushareDailyProvider,
)

NOW = datetime(2026, 8, 17, tzinfo=UTC)


class Client:
    def __init__(self):
        self.body = None

    async def post(self, url, *, json, timeout):
        self.body = json
        fields = json["fields"].split(",")
        return httpx.Response(
            200,
            json={"code": 0, "data": {"fields": fields, "items": []}},
            request=httpx.Request("POST", url),
        )


def provider(capability, client):
    definition = ProviderDefinition(
        "tushare", "providers.tushare_daily", True, 1, frozenset({capability}), {}
    )
    return TushareDailyProvider(definition, "fixture", client)


async def test_adjustment_and_action_capabilities_use_separate_official_apis() -> None:
    client = Client()
    value = provider(TUSHARE_ADJUSTMENT_FACTOR, client)
    await value.initialize()
    request = ProviderInvocationRequest(
        "r",
        "tushare",
        TUSHARE_ADJUSTMENT_FACTOR,
        {
            "market": "CN.SSE",
            "symbol": "600000",
            "start_date": "2026-08-01",
            "end_date": "2026-08-17",
        },
        5000,
        NOW,
    )
    await value.invoke(request)
    assert client.body["api_name"] == "adj_factor"
    assert client.body["params"] == {
        "ts_code": "600000.SH",
        "start_date": "20260801",
        "end_date": "20260817",
    }
    action = provider(TUSHARE_CORPORATE_ACTION, client)
    await action.initialize()
    await action.invoke(
        ProviderInvocationRequest(
            "r",
            "tushare",
            TUSHARE_CORPORATE_ACTION,
            {"market": "CN.SZSE", "symbol": "000001"},
            5000,
            NOW,
        )
    )
    assert client.body["api_name"] == "dividend"
    assert client.body["params"] == {"ts_code": "000001.SZ"}


@pytest.mark.parametrize(
    "payload",
    [
        {"market": "US", "symbol": "x", "start_date": "1", "end_date": "2"},
        {"market": "CN.SSE", "symbol": "600000", "start_date": "1"},
    ],
)
async def test_adjustment_parameters_are_strict(payload) -> None:
    value = provider(TUSHARE_ADJUSTMENT_FACTOR, Client())
    await value.initialize()
    with pytest.raises(InvalidRequestError):
        await value.invoke(
            ProviderInvocationRequest("r", "tushare", TUSHARE_ADJUSTMENT_FACTOR, payload, 5000, NOW)
        )
