"""Add human-approved engineering handoffs.

Revision ID: 20260729_0002
Revises: 20260728_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0002"
down_revision: str | None = "20260728_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "engineering_handoffs",
        sa.Column("case_id", sa.String(length=80), primary_key=True),
        sa.Column("provider_ticket_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_engineering_handoffs_provider_ticket_id",
        "engineering_handoffs",
        ["provider_ticket_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_engineering_handoffs_provider_ticket_id",
        table_name="engineering_handoffs",
    )
    op.drop_table("engineering_handoffs")
