from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
import pytest

from aic_backend.provider_runtime import ProviderDefinition, ProviderInvocationRequest
from aic_backend.provider_runtime.errors import InvalidRequestError, UserPermissionError
from aic_backend.providers.fred import FRED_IMPLEMENTATION, MACRO_VINTAGE_READ, FredProvider


class FixtureClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def get(
        self, url: str, *, params: Mapping[str, object], timeout: float
    ) -> httpx.Response:
        del timeout
        self.calls.append((url, params))
        if url.endswith("/series"):
            body = {
                "seriess": [
                    {
                        "title": "Payrolls",
                        "frequency_short": "M",
                        "seasonal_adjustment_short": "SA",
                        "units": "Thousands",
                    }
                ]
            }
        elif url.endswith("/series/observations"):
            body = {
                "count": 1,
                "limit": 1000,
                "observations": [
                    {
                        "date": "2020-01-01",
                        "value": "100",
                        "realtime_start": "2020-02-07",
                        "realtime_end": "9999-12-31",
                    }
                ],
            }
        else:
            body = {"vintage_dates": ["2020-02-07"]}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    async def aclose(self) -> None:
        return None


def definition() -> ProviderDefinition:
    return ProviderDefinition(
        "fred_official",
        FRED_IMPLEMENTATION,
        True,
        100,
        frozenset({MACRO_VINTAGE_READ}),
        {},
    )


@pytest.mark.asyncio
async def test_fred_alfred_official_vintage_contract_preserves_source_agency() -> None:
    client = FixtureClient()
    provider = FredProvider(definition(), "secret", client=client)
    await provider.initialize()
    response = await provider.invoke(
        ProviderInvocationRequest(
            "request-1",
            "fred_official",
            MACRO_VINTAGE_READ,
            {"series_id": "payems", "source_agency_id": "BLS", "geography": "US"},
            5000,
            datetime(2026, 9, 21, tzinfo=UTC),
        )
    )
    assert response.payload["series"]["source_agency_id"] == "BLS"
    assert response.payload["vintage_dates"] == ("2020-02-07",)
    assert len(client.calls) == 3
    assert all("api_key" not in url for url, _ in client.calls)
    assert all(params["api_key"] == "secret" for _, params in client.calls)
    observation_params = client.calls[1][1]
    assert observation_params["output_type"] == 4
    assert observation_params["realtime_start"] == "1776-07-04"
    assert observation_params["realtime_end"] == "9999-12-31"


@pytest.mark.asyncio
async def test_fred_fails_closed_without_credentials_or_valid_series() -> None:
    provider = FredProvider(definition(), None, client=FixtureClient())
    with pytest.raises(UserPermissionError):
        await provider.initialize()
    configured = FredProvider(definition(), "secret", client=FixtureClient())
    await configured.initialize()
    with pytest.raises(InvalidRequestError):
        await configured.invoke(
            ProviderInvocationRequest(
                "request-2",
                "fred_official",
                MACRO_VINTAGE_READ,
                {"series_id": "../bad"},
                5000,
                datetime(2026, 9, 21, tzinfo=UTC),
            )
        )
