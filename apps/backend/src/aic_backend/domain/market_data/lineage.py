"""Source identity and point-in-time lineage for external evidence."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import parse_qsl, urlsplit

from aic_backend.domain.market_data.errors import InvalidProvenanceError


class AuthorityLevel(StrEnum):
    PRIMARY = "PRIMARY"
    HIGH_QUALITY_PUBLIC = "HIGH_QUALITY_PUBLIC"
    RADAR = "RADAR"
    COMMERCIAL = "COMMERCIAL"


class SourceType(StrEnum):
    OFFICIAL_API = "OFFICIAL_API"
    OFFICIAL_FEED = "OFFICIAL_FEED"
    OFFICIAL_DOCUMENT = "OFFICIAL_DOCUMENT"
    PUBLIC_MARKET_FEED = "PUBLIC_MARKET_FEED"
    RADAR_FEED = "RADAR_FEED"
    LICENSED_MARKET_FEED = "LICENSED_MARKET_FEED"


_SECRET_QUERY_FIELDS = frozenset(
    {"access_token", "api_key", "apikey", "auth", "key", "secret", "signature", "token"}
)


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InvalidProvenanceError(f"{field} must not be empty")
    return normalized


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidProvenanceError(f"{field} must include timezone information")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SourceLineage:
    adapter_id: str
    upstream_source_id: str
    authority_level: AuthorityLevel
    source_type: SourceType
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    raw_hash: str
    transformation_version: str
    published_at: datetime | None = None
    source_uri: str | None = None
    source_record_id: str | None = None
    license_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("adapter_id", "upstream_source_id", "transformation_version"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in ("event_time", "observed_at", "ingested_at"):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", _utc(self.published_at, "published_at"))
        if self.observed_at > self.ingested_at:
            raise InvalidProvenanceError("observed_at must not follow ingested_at")
        if self.published_at is not None and self.published_at > self.observed_at:
            raise InvalidProvenanceError("published_at must not follow first observation")
        if len(self.raw_hash) != 64 or any(c not in "0123456789abcdef" for c in self.raw_hash):
            raise InvalidProvenanceError("raw_hash must be a lowercase SHA-256 digest")
        for field in ("source_record_id", "license_id"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _text(value, field))
        if self.source_uri is not None:
            uri = _text(self.source_uri, "source_uri")
            parsed = urlsplit(uri)
            query_fields = {key.casefold() for key, _ in parse_qsl(parsed.query)}
            if parsed.username or parsed.password or query_fields & _SECRET_QUERY_FIELDS:
                raise InvalidProvenanceError("source_uri must not contain credentials")
            object.__setattr__(self, "source_uri", uri)
