"""Deterministic normalization for official documents and radar event candidates."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from aic_backend.domain.evidence import (
    DocumentType,
    EntityIdentity,
    EntityType,
    EventCandidate,
    EventDocumentLink,
    EventDocumentRelation,
    EvidenceVerification,
    SourceDocument,
)
from aic_backend.domain.market_data import AuthorityLevel, SourceLineage, SourceType


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _optional_text(value: object, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _timestamp(value: object, field: str) -> datetime:
    raw = _text(value, field).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone information")
    return parsed.astimezone(UTC)


def _rows(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be a sequence")
    return value


def _row(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must contain mappings")
    return value


def _hash(*values: str) -> str:
    return hashlib.sha256(":".join(values).encode()).hexdigest()


class PolicyEventNormalizer:
    transformation_version = "policy-event-canonical/v1"

    def normalize_official_documents(
        self,
        payload: Mapping[str, object],
        *,
        adapter_id: str,
        expected_upstream_source_id: str,
        observed_at: datetime,
        ingested_at: datetime,
        raw_hash: str,
    ) -> tuple[tuple[EntityIdentity, ...], tuple[SourceDocument, ...]]:
        upstream = _text(payload.get("upstream_source_id"), "upstream_source_id")
        if upstream != expected_upstream_source_id:
            raise ValueError("official document upstream identity mismatch")
        entities: list[EntityIdentity] = []
        by_id: dict[str, EntityIdentity] = {}
        for value in _rows(payload.get("entities"), "entities"):
            item = _row(value, "entities")
            entity = EntityIdentity(
                _text(item.get("entity_id"), "entity_id"),
                EntityType(_text(item.get("entity_type"), "entity_type")),
                _text(item.get("namespace"), "namespace"),
                _text(item.get("official_identifier"), "official_identifier"),
                _text(item.get("canonical_name"), "canonical_name"),
                tuple(_text(alias, "alias") for alias in _rows(item.get("aliases", ()), "aliases")),
            )
            if entity.entity_id in by_id and by_id[entity.entity_id] != entity:
                raise ValueError("conflicting entity identity in one payload")
            by_id[entity.entity_id] = entity
            entities.append(entity)
        documents: list[SourceDocument] = []
        for value in _rows(payload.get("documents"), "documents"):
            item = _row(value, "documents")
            publisher_id = _text(item.get("publisher_entity_id"), "publisher_entity_id")
            if publisher_id not in by_id:
                raise ValueError("document publisher is not present in official identities")
            source_record_id = _text(item.get("source_record_id"), "source_record_id")
            document_id = _text(item.get("document_id", source_record_id), "document_id")
            version = int(str(item.get("version", 1)))
            content_hash_value = item.get("content_hash")
            content_hash = (
                _text(content_hash_value, "content_hash")
                if content_hash_value is not None
                else _hash(json.dumps(dict(item), sort_keys=True, default=str))
            )
            version_id = "docv_" + _hash(document_id, str(version), content_hash)
            published_at = _timestamp(item.get("published_at"), "published_at")
            event_time = _timestamp(item.get("event_time", item.get("published_at")), "event_time")
            source_uri = _text(item.get("source_uri"), "source_uri")
            predecessor = _optional_text(
                item.get("predecessor_version_id"), "predecessor_version_id"
            )
            lineage = SourceLineage(
                adapter_id,
                upstream,
                AuthorityLevel.PRIMARY,
                SourceType.OFFICIAL_DOCUMENT,
                event_time,
                observed_at,
                ingested_at,
                raw_hash,
                self.transformation_version,
                published_at=published_at,
                source_uri=source_uri,
                source_record_id=source_record_id,
                license_id=_optional_text(payload.get("license_id"), "license_id"),
            )
            documents.append(
                SourceDocument(
                    version_id,
                    document_id,
                    publisher_id,
                    DocumentType(_text(item.get("document_type"), "document_type")),
                    _text(item.get("title"), "title"),
                    _text(item.get("language", "und"), "language"),
                    event_time,
                    published_at,
                    observed_at,
                    ingested_at,
                    source_uri,
                    source_record_id,
                    content_hash,
                    _text(payload.get("raw_observation_id"), "raw_observation_id"),
                    version,
                    predecessor,
                    EvidenceVerification.VERIFIED_OFFICIAL,
                    lineage,
                    _optional_text(item.get("speaker_entity_id"), "speaker_entity_id"),
                    _optional_text(item.get("source_declared_role"), "source_declared_role"),
                    _optional_text(item.get("normalized_text_hash"), "normalized_text_hash"),
                )
            )
        return tuple(entities), tuple(documents)

    def normalize_radar_candidates(
        self,
        payload: Mapping[str, object],
        *,
        adapter_id: str,
        observed_at: datetime,
        ingested_at: datetime,
        raw_hash: str,
    ) -> tuple[EventCandidate, ...]:
        upstream = _text(payload.get("upstream_source_id"), "upstream_source_id")
        if upstream != "GDELT":
            raise ValueError("radar payload must retain the GDELT upstream identity")
        candidates: list[EventCandidate] = []
        for value in _rows(payload.get("candidates"), "candidates"):
            item = _row(value, "candidates")
            source_uri = _text(item.get("source_uri"), "source_uri")
            source_record_id = _text(item.get("source_record_id", source_uri), "source_record_id")
            event_time = _timestamp(item.get("event_time"), "event_time")
            detected_at = _timestamp(item.get("detected_at"), "detected_at")
            try:
                confidence = Decimal(str(item.get("confidence", "0.5")))
            except InvalidOperation as error:
                raise ValueError("confidence must be decimal") from error
            candidate_id = "event_" + _hash(upstream, source_record_id, event_time.isoformat())
            lineage = SourceLineage(
                adapter_id,
                upstream,
                AuthorityLevel.RADAR,
                SourceType.RADAR_FEED,
                event_time,
                observed_at,
                ingested_at,
                raw_hash,
                self.transformation_version,
                published_at=detected_at,
                source_uri=source_uri,
                source_record_id=source_record_id,
                license_id="GDELT-UNRESTRICTED-WITH-ATTRIBUTION",
            )
            candidates.append(
                EventCandidate(
                    candidate_id,
                    _text(item.get("event_category", "NEWS_MENTION"), "event_category"),
                    event_time,
                    detected_at,
                    observed_at,
                    ingested_at,
                    tuple(
                        _text(entity, "entity_id")
                        for entity in _rows(item.get("entity_ids", ()), "entity_ids")
                    ),
                    tuple(
                        _text(location, "location_code")
                        for location in _rows(item.get("location_codes", ()), "location_codes")
                    ),
                    (),
                    AuthorityLevel.RADAR,
                    confidence,
                    EvidenceVerification.RADAR_ONLY,
                    lineage,
                )
            )
        return tuple(candidates)

    @staticmethod
    def verification_link(
        candidate: EventCandidate,
        document: SourceDocument,
        *,
        linked_at: datetime,
    ) -> EventDocumentLink:
        if document.verification is not EvidenceVerification.VERIFIED_OFFICIAL:
            raise ValueError("verification links require a verified official document")
        link_id = "link_" + _hash(candidate.candidate_id, document.document_version_id)
        return EventDocumentLink(
            link_id,
            candidate.candidate_id,
            document.document_version_id,
            EventDocumentRelation.VERIFIED_BY,
            linked_at,
        )
