"""Initial support copilot schema.

Revision ID: 20260728_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260728_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("document_id", sa.String(length=80), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(128), nullable=False),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_table(
        "support_cases",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "suggestions",
        sa.Column("case_id", sa.String(length=80), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("subject_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_audit_events_subject_id", "audit_events", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_subject_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("suggestions")
    op.drop_table("support_cases")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
