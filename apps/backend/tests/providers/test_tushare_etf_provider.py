from datetime import UTC, datetime

import httpx
import pytest

from aic_backend.provider_runtime import ProviderInvocationRequest
from aic_backend.provider_runtime.errors import InvalidRequestError
from aic_backend.provider_runtime.models import ProviderDefinition
from aic_backend.providers.tushare import (
    TUSHARE_ETF_ADJUSTMENT_FACTOR,
    TUSHARE_ETF_BENCHMARK,
    TUSHARE_ETF_DAILY,
    TUSHARE_ETF_MASTER,
    TUSHARE_ETF_VALUATION,
    TUSHARE_INDEX_DAILY,
    TUSHARE_INDEX_REFERENCE,
    TushareDailyProvider,
)

CAPABILITIES = frozenset(
    {
        TUSHARE_ETF_MASTER,
        TUSHARE_ETF_BENCHMARK,
        TUSHARE_ETF_DAILY,
        TUSHARE_ETF_ADJUSTMENT_FACTOR,
        TUSHARE_ETF_VALUATION,
        TUSHARE_INDEX_REFERENCE,
        TUSHARE_INDEX_DAILY,
    }
)


class Client:
    def __init__(self) -> None:
        self.body: dict[str, object] = {}

    async def post(self, url: str, *, json, timeout: float) -> httpx.Response:
        del url, timeout
        self.body = dict(json)
        return httpx.Response(
            200,
            json={"code": 0, "data": {"fields": [], "items": []}},
            request=httpx.Request("POST", "https://api.tushare.pro"),
        )


def definition() -> ProviderDefinition:
    return ProviderDefinition(
        "tushare_pro", "providers.tushare_daily", True, 100, CAPABILITIES, {}
    )


def request(capability, payload: dict[str, str]) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        f"request-{capability.name}",
        "tushare_pro",
        capability,
        payload,
        1000,
        datetime(2026, 9, 6, tzinfo=UTC),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability", "payload", "api_name"),
    [
        (TUSHARE_ETF_MASTER, {"market": "CN.SSE", "list_status": "L"}, "etf_basic"),
        (TUSHARE_ETF_BENCHMARK, {"ts_code": "NDX.GI"}, "etf_index"),
        (TUSHARE_INDEX_REFERENCE, {"ts_code": "NDX.GI"}, "etf_index"),
        (
            TUSHARE_ETF_DAILY,
            {"ts_code": "513100.SH", "start_date": "2026-09-01"},
            "fund_daily",
        ),
        (
            TUSHARE_ETF_ADJUSTMENT_FACTOR,
            {
                "market": "CN.SSE",
                "symbol": "513100",
                "start_date": "2026-09-01",
                "end_date": "2026-09-05",
            },
            "fund_adj",
        ),
        (TUSHARE_ETF_VALUATION, {"ts_code": "513100.SH"}, "etf_share_size"),
        (TUSHARE_INDEX_DAILY, {"ts_code": "NDX.GI"}, "index_daily"),
    ],
)
async def test_etf_and_index_capabilities_use_verified_tushare_endpoints(
    capability, payload: dict[str, str], api_name: str
) -> None:
    client = Client()
    provider = TushareDailyProvider(definition(), "secret", client)
    await provider.initialize()
    result = await provider.invoke(request(capability, payload))
    assert result.payload == {"rows": []}
    assert client.body["api_name"] == api_name
    assert "token" in client.body
    assert "fields" in client.body


def test_etf_master_parameters_are_allowlisted_and_normalized() -> None:
    assert TushareDailyProvider._etf_master_parameters(
        {
            "market": "CN.SZSE",
            "list_status": "D",
            "list_date": "2026-09-01",
            "ignored": "never-forwarded",
        }
    ) == {"exchange": "SZ", "list_status": "D", "list_date": "20260901"}
    assert TushareDailyProvider._index_reference_parameters(
        {"ts_code": "NDX.GI", "base_date": "1985-01-31", "ignored": "x"}
    ) == {"ts_code": "NDX.GI", "base_date": "19850131"}


@pytest.mark.parametrize(
    "payload",
    [
        {"market": "US.NASDAQ"},
        {"market": "CN.SSE", "list_status": "G"},
    ],
)
def test_etf_master_invalid_scope_fails_before_network(payload: dict[str, str]) -> None:
    with pytest.raises(InvalidRequestError):
        TushareDailyProvider._etf_master_parameters(payload)
