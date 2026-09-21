"""Source-neutral policy, people, document, and event evidence models."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from aic_backend.domain.market_data import AuthorityLevel, SourceLineage


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional_text(value: str | None, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone information")
    return value.astimezone(UTC)


def _digest(value: str, field: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


class EntityType(StrEnum):
    INSTITUTION = "INSTITUTION"
    PERSON = "PERSON"
    ISSUER = "ISSUER"
    SECURITY = "SECURITY"
    LOCATION = "LOCATION"


class DocumentType(StrEnum):
    POLICY_DECISION = "POLICY_DECISION"
    STATEMENT = "STATEMENT"
    MINUTES = "MINUTES"
    SPEECH = "SPEECH"
    REGULATORY_FILING = "REGULATORY_FILING"
    SANCTIONS_NOTICE = "SANCTIONS_NOTICE"
    OFFICIAL_RELEASE = "OFFICIAL_RELEASE"
    OTHER = "OTHER"


class EvidenceVerification(StrEnum):
    VERIFIED_OFFICIAL = "VERIFIED_OFFICIAL"
    UNVERIFIED = "UNVERIFIED"
    QUARANTINED = "QUARANTINED"
    RADAR_ONLY = "RADAR_ONLY"


class EventDocumentRelation(StrEnum):
    DISCOVERED_BY = "DISCOVERED_BY"
    VERIFIED_BY = "VERIFIED_BY"
    ACTUAL_RELEASE = "ACTUAL_RELEASE"


@dataclass(frozen=True, slots=True)
class EntityIdentity:
    entity_id: str
    entity_type: EntityType
    namespace: str
    official_identifier: str
    canonical_name: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("entity_id", "namespace", "official_identifier", "canonical_name"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        aliases = tuple(sorted({_text(value, "alias") for value in self.aliases}))
        if self.canonical_name in aliases:
            aliases = tuple(value for value in aliases if value != self.canonical_name)
        object.__setattr__(self, "aliases", aliases)

    @property
    def authority_key(self) -> tuple[str, str]:
        return self.namespace, self.official_identifier


@dataclass(frozen=True, slots=True)
class SourceDocument:
    document_version_id: str
    document_id: str
    publisher_entity_id: str
    document_type: DocumentType
    title: str
    language: str
    event_time: datetime
    published_at: datetime
    observed_at: datetime
    ingested_at: datetime
    source_uri: str
    source_record_id: str
    content_hash: str
    raw_observation_id: str
    version: int
    predecessor_version_id: str | None
    verification: EvidenceVerification
    lineage: SourceLineage
    speaker_entity_id: str | None = None
    source_declared_role: str | None = None
    normalized_text_hash: str | None = None

    RECORD_TYPE = "SOURCE_DOCUMENT"

    def __post_init__(self) -> None:
        for field in (
            "document_version_id",
            "document_id",
            "publisher_entity_id",
            "title",
            "language",
            "source_uri",
            "source_record_id",
            "raw_observation_id",
        ):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in ("event_time", "published_at", "observed_at", "ingested_at"):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        object.__setattr__(self, "content_hash", _digest(self.content_hash, "content_hash"))
        if self.normalized_text_hash is not None:
            object.__setattr__(
                self,
                "normalized_text_hash",
                _digest(self.normalized_text_hash, "normalized_text_hash"),
            )
        if self.version <= 0 or (self.version == 1) != (self.predecessor_version_id is None):
            raise ValueError("document version and predecessor are inconsistent")
        object.__setattr__(
            self,
            "predecessor_version_id",
            _optional_text(self.predecessor_version_id, "predecessor_version_id"),
        )
        object.__setattr__(
            self, "speaker_entity_id", _optional_text(self.speaker_entity_id, "speaker_entity_id")
        )
        object.__setattr__(
            self,
            "source_declared_role",
            _optional_text(self.source_declared_role, "source_declared_role"),
        )
        if (self.speaker_entity_id is None) != (self.source_declared_role is None):
            raise ValueError("speaker identity and source-declared role must be supplied together")
        if self.published_at > self.observed_at or self.observed_at > self.ingested_at:
            raise ValueError("document publication, observation and ingestion order is invalid")
        if self.lineage.published_at != self.published_at:
            raise ValueError("document published_at must match source lineage")
        if (self.lineage.observed_at, self.lineage.ingested_at) != (
            self.observed_at,
            self.ingested_at,
        ):
            raise ValueError("document timestamps must match source lineage")
        if (self.lineage.source_uri, self.lineage.source_record_id) != (
            self.source_uri,
            self.source_record_id,
        ):
            raise ValueError("document source identity must match source lineage")
        if self.verification is EvidenceVerification.VERIFIED_OFFICIAL:
            if self.lineage.authority_level is not AuthorityLevel.PRIMARY:
                raise ValueError("only primary authority can produce verified official evidence")
        elif self.lineage.authority_level is AuthorityLevel.RADAR:
            raise ValueError("radar evidence cannot be promoted to a source document")


@dataclass(frozen=True, slots=True)
class EventCandidate:
    candidate_id: str
    event_category: str
    event_time: datetime
    detected_at: datetime
    observed_at: datetime
    ingested_at: datetime
    entity_ids: tuple[str, ...]
    location_codes: tuple[str, ...]
    source_document_version_ids: tuple[str, ...]
    authority_level: AuthorityLevel
    confidence: Decimal
    verification: EvidenceVerification
    lineage: SourceLineage

    RECORD_TYPE = "EVENT_CANDIDATE"

    def __post_init__(self) -> None:
        for field in ("candidate_id", "event_category"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in ("event_time", "detected_at", "observed_at", "ingested_at"):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        for field in ("entity_ids", "location_codes", "source_document_version_ids"):
            values = tuple(sorted({_text(value, field[:-1]) for value in getattr(self, field)}))
            object.__setattr__(self, field, values)
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("event confidence must be between zero and one")
        if self.detected_at > self.observed_at or self.observed_at > self.ingested_at:
            raise ValueError("event detection, observation and ingestion order is invalid")
        if self.authority_level is not self.lineage.authority_level:
            raise ValueError("event authority must match source lineage")
        if self.authority_level is AuthorityLevel.RADAR:
            if self.verification is not EvidenceVerification.RADAR_ONLY:
                raise ValueError("radar event candidates must remain radar-only")
        elif self.verification is EvidenceVerification.VERIFIED_OFFICIAL:
            if self.authority_level is not AuthorityLevel.PRIMARY:
                raise ValueError("verified events require primary authority")
            if not self.source_document_version_ids:
                raise ValueError("verified events require official source-document evidence")


@dataclass(frozen=True, slots=True)
class EventDocumentLink:
    link_id: str
    candidate_id: str
    document_version_id: str
    relation: EventDocumentRelation
    linked_at: datetime

    def __post_init__(self) -> None:
        for field in ("link_id", "candidate_id", "document_version_id"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "linked_at", _utc(self.linked_at, "linked_at"))


@dataclass(frozen=True, slots=True)
class EvidenceQuarantine:
    quarantine_id: str
    raw_observation_id: str
    upstream_source_id: str
    reason_code: str
    detail: str
    observed_at: datetime
    ingested_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "quarantine_id",
            "raw_observation_id",
            "upstream_source_id",
            "reason_code",
            "detail",
        ):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        object.__setattr__(self, "ingested_at", _utc(self.ingested_at, "ingested_at"))
        if self.observed_at > self.ingested_at:
            raise ValueError("quarantine observation must not follow ingestion")
