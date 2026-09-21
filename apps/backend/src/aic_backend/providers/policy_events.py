"""Official policy/document adapters and a discovery-only GDELT radar adapter."""

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol

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

OFFICIAL_DOCUMENT_READ = ProviderCapability("official.document.read", "1.0.0", CapabilityMode.BATCH)
OFFICIAL_FEED_READ = ProviderCapability("official.feed.read", "1.0.0", CapabilityMode.BATCH)
OFFICIAL_ISSUER_READ = ProviderCapability("official.issuer.read", "1.0.0", CapabilityMode.BATCH)
EVENT_RADAR_READ = ProviderCapability("event.radar.read", "1.0.0", CapabilityMode.BATCH)

FEDERAL_RESERVE_IMPLEMENTATION = "providers.federal_reserve_feed"
SEC_EDGAR_IMPLEMENTATION = "providers.sec_edgar_official"
GDELT_IMPLEMENTATION = "providers.gdelt_radar"

_FED_FEEDS = {
    "press_all": "https://www.federalreserve.gov/feeds/press_all.xml",
    "speeches": "https://www.federalreserve.gov/feeds/speeches.xml",
    "testimony": "https://www.federalreserve.gov/feeds/testimony.xml",
}
_ACCESSION = re.compile(r"^(\d{10})-(\d{2})-(\d{6})$")
_SEC_FILE = re.compile(r"^CIK\d{10}-submissions-\d{3}\.json$")


class HttpGetClient(Protocol):
    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float,
    ) -> httpx.Response: ...


def _timestamp(value: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("timestamp is empty")
    try:
        parsed = (
            parsedate_to_datetime(raw)
            if "," in raw
            else datetime.fromisoformat(raw.replace("Z", "+00:00"))
        )
    except (TypeError, ValueError) as error:
        raise ValueError("timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone information")
    return parsed.astimezone(UTC)


def _response_error(response: httpx.Response, source: str) -> None:
    if response.status_code == 429:
        raise ProviderRateLimitedError(f"{source} rate limit was reached.")
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ProviderUnavailableError(f"{source} is unavailable.") from error


class _HttpProvider:
    def __init__(self, definition: ProviderDefinition, client: HttpGetClient | None) -> None:
        self._definition = definition
        self._client = client or httpx.AsyncClient()
        self._initialized = False

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return self._definition.capabilities

    async def shutdown(self) -> None:
        self._initialized = False
        close = getattr(self._client, "aclose", None)
        if callable(close):
            await close()

    async def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            HealthStatus.HEALTHY if self._initialized else HealthStatus.UNKNOWN,
            datetime.now(UTC),
            message="configured" if self._initialized else "not-initialized",
        )


class FederalReserveFeedProvider(_HttpProvider):
    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            self._definition.provider_id,
            "Federal Reserve Official Feeds",
            ProviderType.NEWS,
            "1.0.0",
            vendor="Board of Governors of the Federal Reserve System",
            priority=self._definition.priority,
            enabled=self._definition.enabled,
            tags=frozenset({"official", "primary", "rss", "pit"}),
        )

    async def initialize(self) -> None:
        self._initialized = True

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResponse:
        if request.capability not in {OFFICIAL_FEED_READ, OFFICIAL_DOCUMENT_READ}:
            raise InvalidRequestError("Federal Reserve capability is unsupported.")
        if not self._initialized:
            raise ProviderUnavailableError("Federal Reserve provider is not initialized.")
        feed = str(request.payload.get("feed", "press_all"))
        if feed not in _FED_FEEDS:
            raise InvalidRequestError("Federal Reserve feed is not allowlisted.")
        headers = {}
        if etag := str(request.payload.get("etag", "")).strip():
            headers["If-None-Match"] = etag
        if modified := str(request.payload.get("last_modified", "")).strip():
            headers["If-Modified-Since"] = modified
        try:
            response = await self._client.get(
                _FED_FEEDS[feed], headers=headers, timeout=request.timeout_ms / 1000
            )
            if response.status_code == 304:
                return ProviderInvocationResponse(
                    {
                        "upstream_source_id": "FEDERAL_RESERVE",
                        "entities": (),
                        "documents": (),
                        "not_modified": True,
                        "etag": response.headers.get("etag"),
                        "last_modified": response.headers.get("last-modified"),
                    }
                )
            _response_error(response, "Federal Reserve feed")
        except (ProviderRateLimitedError, ProviderUnavailableError):
            raise
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("Federal Reserve feed timed out.") from error
        if len(response.content) > 2_000_000:
            raise ProviderInvalidResponseError("Federal Reserve feed exceeds the payload limit.")
        lowered = response.content.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise ProviderInvalidResponseError("Federal Reserve feed contains forbidden XML.")
        try:
            root = ET.fromstring(response.content)
            items = root.findall(".//item") or root.findall(".//{*}entry")
            documents: list[dict[str, object]] = []
            latest: datetime | None = None
            for item in items[:500]:
                title = (item.findtext("title") or item.findtext("{*}title") or "").strip()
                identifier = (
                    item.findtext("guid") or item.findtext("{*}id") or item.findtext("link") or ""
                ).strip()
                link_node = item.find("{*}link")
                link = (item.findtext("link") or "").strip()
                if not link and link_node is not None:
                    link = str(link_node.attrib.get("href", "")).strip()
                published_raw = (
                    item.findtext("pubDate")
                    or item.findtext("{*}published")
                    or item.findtext("{*}updated")
                    or ""
                )
                published = _timestamp(published_raw)
                if (
                    not title
                    or not identifier
                    or not link.startswith("https://www.federalreserve.gov/")
                ):
                    raise ValueError("feed item identity is invalid")
                latest = published if latest is None else max(latest, published)
                lowered_title = title.casefold()
                document_type = (
                    "MINUTES"
                    if "minutes" in lowered_title
                    else "SPEECH"
                    if feed in {"speeches", "testimony"}
                    else "POLICY_DECISION"
                    if "federal funds" in lowered_title or "fomc" in lowered_title
                    else "OFFICIAL_RELEASE"
                )
                item_bytes = ET.tostring(item, encoding="utf-8")
                documents.append(
                    {
                        "document_id": identifier,
                        "source_record_id": identifier,
                        "publisher_entity_id": "institution:FEDERAL_RESERVE_BOARD",
                        "document_type": document_type,
                        "title": title,
                        "language": "en",
                        "event_time": published.isoformat(),
                        "published_at": published.isoformat(),
                        "source_uri": link,
                        "content_hash": hashlib.sha256(item_bytes).hexdigest(),
                        "version": 1,
                    }
                )
        except (ET.ParseError, ValueError) as error:
            raise ProviderInvalidResponseError("Federal Reserve feed is malformed.") from error
        payload: dict[str, object] = {
            "upstream_source_id": "FEDERAL_RESERVE",
            "license_id": "FEDERAL-RESERVE-PUBLIC-RSS",
            "entities": (
                {
                    "entity_id": "institution:FEDERAL_RESERVE_BOARD",
                    "entity_type": "INSTITUTION",
                    "namespace": "OFFICIAL_US_AGENCY",
                    "official_identifier": "FEDERAL_RESERVE_BOARD",
                    "canonical_name": "Board of Governors of the Federal Reserve System",
                    "aliases": ("Federal Reserve Board",),
                },
            ),
            "documents": tuple(documents),
            "not_modified": False,
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }
        return ProviderInvocationResponse(payload, latest)


class SecEdgarProvider(_HttpProvider):
    def __init__(
        self,
        definition: ProviderDefinition,
        user_agent: str | None,
        *,
        client: HttpGetClient | None = None,
    ) -> None:
        super().__init__(definition, client)
        self._user_agent = user_agent

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            self._definition.provider_id,
            "SEC EDGAR Official API",
            ProviderType.FUNDAMENTAL_DATA,
            "1.0.0",
            vendor="U.S. Securities and Exchange Commission",
            priority=self._definition.priority,
            enabled=self._definition.enabled,
            tags=frozenset({"official", "primary", "filings", "pit"}),
        )

    async def initialize(self) -> None:
        if self._definition.enabled and not self._user_agent:
            raise UserPermissionError("SEC EDGAR requires a declared User-Agent identity.")
        self._initialized = True

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResponse:
        if request.capability not in {OFFICIAL_ISSUER_READ, OFFICIAL_DOCUMENT_READ}:
            raise InvalidRequestError("SEC EDGAR capability is unsupported.")
        if not self._initialized or not self._user_agent:
            raise UserPermissionError("SEC EDGAR User-Agent is not configured.")
        cik = str(request.payload.get("cik", "")).strip()
        if len(cik) != 10 or not cik.isdigit():
            raise InvalidRequestError("SEC EDGAR CIK must contain ten digits.")
        cursor = str(request.payload.get("cursor", "")).strip()
        if cursor and not _SEC_FILE.fullmatch(cursor):
            raise InvalidRequestError("SEC EDGAR cursor is invalid.")
        url = f"https://data.sec.gov/submissions/{cursor or f'CIK{cik}.json'}"
        headers = {"User-Agent": self._user_agent, "Accept-Encoding": "gzip, deflate"}
        if etag := str(request.payload.get("etag", "")).strip():
            headers["If-None-Match"] = etag
        try:
            response = await self._client.get(
                url, headers=headers, timeout=request.timeout_ms / 1000
            )
            if response.status_code == 304:
                return ProviderInvocationResponse(
                    {
                        "upstream_source_id": "SEC_EDGAR",
                        "entities": (),
                        "documents": (),
                        "not_modified": True,
                    }
                )
            _response_error(response, "SEC EDGAR")
        except (ProviderRateLimitedError, ProviderUnavailableError):
            raise
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("SEC EDGAR request timed out.") from error
        if len(response.content) > 5_000_000:
            raise ProviderInvalidResponseError("SEC EDGAR response exceeds the payload limit.")
        try:
            body = response.json()
            if not isinstance(body, Mapping):
                raise ValueError("response is not an object")
            response_cik = str(body.get("cik", cik)).zfill(10)
            if response_cik != cik:
                raise ValueError("CIK mismatch")
            issuer_name = str(body.get("name") or request.payload.get("issuer_name") or "").strip()
            if not issuer_name:
                raise ValueError("issuer name missing")
            filings = body.get("filings", {})
            if not isinstance(filings, Mapping):
                raise ValueError("filings missing")
            recent_value = filings.get("recent", body if cursor else {})
            if not isinstance(recent_value, Mapping):
                raise ValueError("recent filings missing")
            accessions = recent_value.get("accessionNumber", ())
            forms = recent_value.get("form", ())
            filing_dates = recent_value.get("filingDate", ())
            accepted = recent_value.get("acceptanceDateTime", ())
            primary_documents = recent_value.get("primaryDocument", ())
            values = (accessions, forms, filing_dates, accepted, primary_documents)
            if not all(isinstance(value, list) for value in values):
                raise ValueError("filing columns are invalid")
            if len({len(value) for value in values}) != 1:
                raise ValueError("filing columns are misaligned")
            documents: list[dict[str, object]] = []
            latest: datetime | None = None
            for accession, form, filing_date, accepted_at, primary_document in zip(
                *values, strict=True
            ):
                accession_value = str(accession)
                if _ACCESSION.fullmatch(accession_value) is None:
                    raise ValueError("accession identity is invalid")
                form_value = str(form).strip()
                primary_value = str(primary_document).strip()
                if (
                    not form_value
                    or not primary_value
                    or "/" in primary_value
                    or "\\" in primary_value
                ):
                    raise ValueError("filing identity is invalid")
                published = _timestamp(str(accepted_at))
                latest = published if latest is None else max(latest, published)
                accession_compact = accession_value.replace("-", "")
                source_uri = (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{accession_compact}/{primary_value}"
                )
                identity = f"{accession_value}:{primary_value}"
                documents.append(
                    {
                        "document_id": accession_value,
                        "source_record_id": identity,
                        "publisher_entity_id": f"issuer:SEC_CIK_{cik}",
                        "document_type": "REGULATORY_FILING",
                        "title": f"{form_value} — {issuer_name}",
                        "language": "en",
                        "event_time": published.isoformat(),
                        "published_at": published.isoformat(),
                        "source_uri": source_uri,
                        "content_hash": hashlib.sha256(
                            json.dumps(
                                [
                                    accession_value,
                                    form_value,
                                    filing_date,
                                    accepted_at,
                                    primary_value,
                                ]
                            ).encode()
                        ).hexdigest(),
                        "version": 1,
                    }
                )
            files = filings.get("files", ()) if not cursor else ()
            next_cursor = None
            if files:
                if not isinstance(files, list) or not isinstance(files[0], Mapping):
                    raise ValueError("filing page metadata is invalid")
                next_cursor = str(files[0].get("name", ""))
                if not _SEC_FILE.fullmatch(next_cursor):
                    raise ValueError("filing page cursor is invalid")
        except (TypeError, ValueError) as error:
            raise ProviderInvalidResponseError("SEC EDGAR response schema is invalid.") from error
        former_names = body.get("formerNames", ())
        aliases = (
            tuple(
                str(value.get("name", "")).strip()
                for value in former_names
                if isinstance(value, Mapping) and str(value.get("name", "")).strip()
            )
            if isinstance(former_names, list)
            else ()
        )
        return ProviderInvocationResponse(
            {
                "upstream_source_id": "SEC_EDGAR",
                "license_id": "SEC-FAIR-ACCESS",
                "entities": (
                    {
                        "entity_id": f"issuer:SEC_CIK_{cik}",
                        "entity_type": "ISSUER",
                        "namespace": "SEC_CIK",
                        "official_identifier": cik,
                        "canonical_name": issuer_name,
                        "aliases": aliases,
                    },
                ),
                "documents": tuple(documents),
                "next_cursor": next_cursor,
                "not_modified": False,
                "etag": response.headers.get("etag"),
            },
            latest,
        )


class GdeltRadarProvider(_HttpProvider):
    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            self._definition.provider_id,
            "GDELT DOC 2.0 Radar",
            ProviderType.NEWS,
            "1.0.0",
            vendor="GDELT Project",
            priority=self._definition.priority,
            enabled=self._definition.enabled,
            tags=frozenset({"radar", "discovery-only", "attribution-required"}),
        )

    async def initialize(self) -> None:
        self._initialized = True

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResponse:
        if request.capability != EVENT_RADAR_READ:
            raise InvalidRequestError("GDELT radar capability is unsupported.")
        if not self._initialized:
            raise ProviderUnavailableError("GDELT provider is not initialized.")
        query = str(request.payload.get("query", "")).strip()
        if not query or len(query) > 500:
            raise InvalidRequestError("GDELT query is invalid.")
        params: dict[str, str | int] = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(int(str(request.payload.get("limit", 250))), 250),
            "sort": "datedesc",
        }
        for field in ("startdatetime", "enddatetime"):
            if value := str(request.payload.get(field, "")).strip():
                if len(value) != 14 or not value.isdigit():
                    raise InvalidRequestError(f"GDELT {field} is invalid.")
                params[field] = value
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        try:
            response = await self._client.get(url, params=params, timeout=request.timeout_ms / 1000)
            _response_error(response, "GDELT DOC API")
        except (ProviderRateLimitedError, ProviderUnavailableError):
            raise
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("GDELT DOC API timed out.") from error
        if len(response.content) > 5_000_000:
            raise ProviderInvalidResponseError("GDELT response exceeds the payload limit.")
        try:
            body = response.json()
            articles = body.get("articles") if isinstance(body, Mapping) else None
            if not isinstance(articles, list):
                raise ValueError("articles missing")
            candidates: list[dict[str, object]] = []
            latest: datetime | None = None
            for article in articles:
                if not isinstance(article, Mapping):
                    raise ValueError("article is invalid")
                source_uri = str(article.get("url", "")).strip()
                title = str(article.get("title", "")).strip()
                seen = _timestamp(str(article.get("seendate", "")))
                if not source_uri.startswith(("http://", "https://")) or not title:
                    raise ValueError("article identity is invalid")
                latest = seen if latest is None else max(latest, seen)
                candidates.append(
                    {
                        "source_uri": source_uri,
                        "source_record_id": hashlib.sha256(source_uri.encode()).hexdigest(),
                        "event_category": "NEWS_MENTION",
                        "event_time": seen.isoformat(),
                        "detected_at": seen.isoformat(),
                        "entity_ids": (),
                        "location_codes": tuple(
                            value
                            for value in (str(article.get("sourcecountry", "")).strip().upper(),)
                            if value
                        ),
                        "confidence": "0.5",
                        "title": title,
                    }
                )
        except (TypeError, ValueError) as error:
            raise ProviderInvalidResponseError("GDELT response schema is invalid.") from error
        return ProviderInvocationResponse(
            {"upstream_source_id": "GDELT", "candidates": tuple(candidates)}, latest
        )


def build_federal_reserve_feed_provider(
    definition: ProviderDefinition,
) -> FederalReserveFeedProvider:
    return FederalReserveFeedProvider(definition, None)


def build_sec_edgar_provider(definition: ProviderDefinition) -> SecEdgarProvider:
    configured = os.getenv("AIC_SEC_USER_AGENT")
    identity = configured.strip() if configured and configured.strip() else None
    if definition.enabled and identity is None:
        raise ValueError("enabled SEC EDGAR provider requires AIC_SEC_USER_AGENT")
    return SecEdgarProvider(definition, identity)


def build_gdelt_radar_provider(definition: ProviderDefinition) -> GdeltRadarProvider:
    return GdeltRadarProvider(definition, None)
