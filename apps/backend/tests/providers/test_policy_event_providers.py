from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
import pytest

from aic_backend.provider_runtime import ProviderDefinition, ProviderInvocationRequest
from aic_backend.provider_runtime.errors import (
    InvalidRequestError,
    ProviderInvalidResponseError,
    UserPermissionError,
)
from aic_backend.providers.policy_events import (
    EVENT_RADAR_READ,
    FEDERAL_RESERVE_IMPLEMENTATION,
    GDELT_IMPLEMENTATION,
    OFFICIAL_FEED_READ,
    OFFICIAL_ISSUER_READ,
    SEC_EDGAR_IMPLEMENTATION,
    FederalReserveFeedProvider,
    GdeltRadarProvider,
    SecEdgarProvider,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


class FixtureClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, object] | None, Mapping[str, str] | None]] = []

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float,
    ) -> httpx.Response:
        del timeout
        self.calls.append((url, params, headers))
        return self.responses.pop(0)

    async def aclose(self) -> None:
        return None


def response(status: int, *, content: bytes | None = None, body: object = None) -> httpx.Response:
    request = httpx.Request("GET", "https://source.test")
    if content is not None:
        return httpx.Response(status, content=content, request=request)
    return httpx.Response(status, json=body, request=request)


def definition(provider_id: str, implementation: str, capability: object) -> ProviderDefinition:
    return ProviderDefinition(
        provider_id,
        implementation,
        True,
        100,
        frozenset({capability}),  # type: ignore[arg-type]
        {},
    )


def request(
    provider_id: str, capability: object, payload: dict[str, object]
) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        "request-1",
        provider_id,
        capability,  # type: ignore[arg-type]
        payload,
        5000,
        NOW,
    )


@pytest.mark.asyncio
async def test_federal_reserve_rss_is_bounded_conditional_and_official() -> None:
    xml = b"""<?xml version='1.0'?>
    <rss><channel><item><title>Federal Reserve issues FOMC statement</title>
    <guid>fomc-2026-09</guid><link>https://www.federalreserve.gov/newsevents/a.htm</link>
    <pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate></item></channel></rss>"""
    client = FixtureClient(
        [
            httpx.Response(
                200,
                content=xml,
                headers={"etag": '"v1"'},
                request=httpx.Request("GET", "https://source.test"),
            ),
            response(304, content=b""),
        ]
    )
    provider = FederalReserveFeedProvider(
        definition("fed_official", FEDERAL_RESERVE_IMPLEMENTATION, OFFICIAL_FEED_READ), client
    )
    await provider.initialize()
    first = await provider.invoke(request("fed_official", OFFICIAL_FEED_READ, {}))
    assert first.payload["upstream_source_id"] == "FEDERAL_RESERVE"
    assert first.payload["documents"][0]["document_type"] == "POLICY_DECISION"
    second = await provider.invoke(request("fed_official", OFFICIAL_FEED_READ, {"etag": '"v1"'}))
    assert second.payload["not_modified"] is True
    assert client.calls[1][2] == {"If-None-Match": '"v1"'}


@pytest.mark.asyncio
async def test_federal_reserve_rejects_oversized_or_entity_expanding_xml() -> None:
    malicious = b"<!DOCTYPE rss [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><rss/>"
    provider = FederalReserveFeedProvider(
        definition("fed_official", FEDERAL_RESERVE_IMPLEMENTATION, OFFICIAL_FEED_READ),
        FixtureClient([response(200, content=malicious)]),
    )
    await provider.initialize()
    with pytest.raises(ProviderInvalidResponseError, match="forbidden XML"):
        await provider.invoke(request("fed_official", OFFICIAL_FEED_READ, {}))

    oversized = FederalReserveFeedProvider(
        definition("fed_official", FEDERAL_RESERVE_IMPLEMENTATION, OFFICIAL_FEED_READ),
        FixtureClient([response(200, content=b"x" * 2_000_001)]),
    )
    await oversized.initialize()
    with pytest.raises(ProviderInvalidResponseError, match="payload limit"):
        await oversized.invoke(request("fed_official", OFFICIAL_FEED_READ, {}))


def sec_body(
    *, cik: str = "0000320193", accession: str = "0000320193-26-000001"
) -> dict[str, object]:
    return {
        "cik": cik,
        "name": "Apple Inc.",
        "formerNames": (),
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "form": ["8-K"],
                "filingDate": ["2026-09-21"],
                "acceptanceDateTime": ["2026-09-21T16:30:00-04:00"],
                "primaryDocument": ["form8-k.htm"],
            },
            "files": [{"name": "CIK0000320193-submissions-001.json", "from": "2015", "to": "2020"}],
        },
    }


@pytest.mark.asyncio
async def test_sec_edgar_declares_identity_preserves_accession_and_paginates() -> None:
    client = FixtureClient([response(200, body=sec_body())])
    provider = SecEdgarProvider(
        definition("sec_edgar", SEC_EDGAR_IMPLEMENTATION, OFFICIAL_ISSUER_READ),
        "AIC engineering@example.com",
        client=client,
    )
    await provider.initialize()
    result = await provider.invoke(
        request("sec_edgar", OFFICIAL_ISSUER_READ, {"cik": "0000320193"})
    )
    assert result.payload["upstream_source_id"] == "SEC_EDGAR"
    assert result.payload["next_cursor"] == "CIK0000320193-submissions-001.json"
    assert result.payload["documents"][0]["source_record_id"].startswith("0000320193-")
    assert client.calls[0][2]["User-Agent"] == "AIC engineering@example.com"


@pytest.mark.asyncio
async def test_sec_edgar_identity_mismatch_and_undeclared_client_fail_closed() -> None:
    unconfigured = SecEdgarProvider(
        definition("sec_edgar", SEC_EDGAR_IMPLEMENTATION, OFFICIAL_ISSUER_READ),
        None,
        client=FixtureClient([]),
    )
    with pytest.raises(UserPermissionError):
        await unconfigured.initialize()

    provider = SecEdgarProvider(
        definition("sec_edgar", SEC_EDGAR_IMPLEMENTATION, OFFICIAL_ISSUER_READ),
        "AIC engineering@example.com",
        client=FixtureClient([response(200, body=sec_body(cik="0000789019"))]),
    )
    await provider.initialize()
    with pytest.raises(ProviderInvalidResponseError, match="schema"):
        await provider.invoke(request("sec_edgar", OFFICIAL_ISSUER_READ, {"cik": "0000320193"}))
    with pytest.raises(InvalidRequestError, match="cursor"):
        await provider.invoke(
            request(
                "sec_edgar",
                OFFICIAL_ISSUER_READ,
                {"cik": "0000320193", "cursor": "../secret"},
            )
        )


@pytest.mark.asyncio
async def test_gdelt_adapter_emits_radar_candidates_without_official_authority() -> None:
    body = {
        "articles": [
            {
                "url": "https://news.example.test/a",
                "title": "Policy report",
                "seendate": "2026-09-22T12:00:00Z",
                "sourcecountry": "United States",
            }
        ]
    }
    client = FixtureClient([response(200, body=body)])
    provider = GdeltRadarProvider(
        definition("gdelt_radar", GDELT_IMPLEMENTATION, EVENT_RADAR_READ), client
    )
    await provider.initialize()
    result = await provider.invoke(
        request("gdelt_radar", EVENT_RADAR_READ, {"query": "central bank", "limit": 10})
    )
    assert result.payload["upstream_source_id"] == "GDELT"
    assert result.payload["candidates"][0]["event_category"] == "NEWS_MENTION"
    assert client.calls[0][1]["mode"] == "artlist"
