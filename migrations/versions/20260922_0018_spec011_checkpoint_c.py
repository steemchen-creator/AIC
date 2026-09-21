"""Add policy, document, entity, and event evidence for SPEC-011 Checkpoint C.

Revision ID: 20260922_0018
Revises: 20260921_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0018"
down_revision: str | None = "20260921_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_entities",
        sa.Column("entity_id", sa.String(160), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("namespace", sa.String(96), nullable=False),
        sa.Column("official_identifier", sa.String(255), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("aliases", sa.ARRAY(sa.Text()), nullable=False),
        sa.UniqueConstraint(
            "namespace", "official_identifier", name="uq_evidence_entity_authority"
        ),
    )
    op.create_table(
        "source_documents",
        sa.Column("document_version_id", sa.String(96), primary_key=True),
        sa.Column("document_id", sa.String(160), nullable=False),
        sa.Column("publisher_entity_id", sa.String(160), nullable=False),
        sa.Column("document_type", sa.String(48), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("speaker_entity_id", sa.String(160)),
        sa.Column("source_declared_role", sa.Text()),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_uri", sa.String(2048), nullable=False),
        sa.Column("source_record_id", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_observation_id", sa.String(96), nullable=False),
        sa.Column("normalized_text_hash", sa.String(64)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("predecessor_version_id", sa.String(96)),
        sa.Column("verification", sa.String(32), nullable=False),
        sa.Column("adapter_id", sa.String(64), nullable=False),
        sa.Column("upstream_source_id", sa.String(96), nullable=False),
        sa.Column("authority_level", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("transformation_version", sa.String(96), nullable=False),
        sa.Column("license_id", sa.String(96)),
        sa.ForeignKeyConstraint(["publisher_entity_id"], ["evidence_entities.entity_id"]),
        sa.ForeignKeyConstraint(["speaker_entity_id"], ["evidence_entities.entity_id"]),
        sa.ForeignKeyConstraint(
            ["predecessor_version_id"], ["source_documents.document_version_id"]
        ),
    )
    op.create_index("ix_source_documents_document_id", "source_documents", ["document_id"])
    op.create_index(
        "ix_source_documents_document_version",
        "source_documents",
        ["document_id", "version"],
        unique=True,
    )
    op.create_index(
        "ix_source_documents_pit",
        "source_documents",
        ["published_at", "observed_at", "ingested_at"],
    )
    op.create_table(
        "event_candidates",
        sa.Column("candidate_id", sa.String(96), primary_key=True),
        sa.Column("event_category", sa.String(96), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entity_ids", sa.ARRAY(sa.String(160)), nullable=False),
        sa.Column("location_codes", sa.ARRAY(sa.String(64)), nullable=False),
        sa.Column("source_document_version_ids", sa.ARRAY(sa.String(96)), nullable=False),
        sa.Column("authority_level", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 7), nullable=False),
        sa.Column("verification", sa.String(32), nullable=False),
        sa.Column("adapter_id", sa.String(64), nullable=False),
        sa.Column("upstream_source_id", sa.String(96), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("transformation_version", sa.String(96), nullable=False),
        sa.Column("source_uri", sa.String(2048)),
        sa.Column("source_record_id", sa.String(255)),
        sa.Column("license_id", sa.String(96)),
    )
    op.create_index(
        "ix_event_candidates_pit",
        "event_candidates",
        ["detected_at", "observed_at", "ingested_at"],
    )
    op.create_table(
        "event_document_links",
        sa.Column("link_id", sa.String(96), primary_key=True),
        sa.Column("candidate_id", sa.String(96), nullable=False),
        sa.Column("document_version_id", sa.String(96), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["event_candidates.candidate_id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["source_documents.document_version_id"]),
    )
    op.create_index("ix_event_document_links_candidate", "event_document_links", ["candidate_id"])
    op.create_table(
        "evidence_quarantines",
        sa.Column("quarantine_id", sa.String(96), primary_key=True),
        sa.Column("raw_observation_id", sa.String(96), nullable=False),
        sa.Column("upstream_source_id", sa.String(96), nullable=False),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_evidence_quarantines_raw_observation_id",
        "evidence_quarantines",
        ["raw_observation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_quarantines_raw_observation_id", table_name="evidence_quarantines")
    op.drop_table("evidence_quarantines")
    op.drop_index("ix_event_document_links_candidate", table_name="event_document_links")
    op.drop_table("event_document_links")
    op.drop_index("ix_event_candidates_pit", table_name="event_candidates")
    op.drop_table("event_candidates")
    op.drop_index("ix_source_documents_pit", table_name="source_documents")
    op.drop_index("ix_source_documents_document_version", table_name="source_documents")
    op.drop_index("ix_source_documents_document_id", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_table("evidence_entities")
