"""comparison_runs: cache Hebrew translations of memo prose

Revision ID: 0005_comparison_translations_he
Revises: 0004_standards_ingest_runs
Create Date: 2026-05-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_comparison_translations_he"
down_revision: str | None = "0004_standards_ingest_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Server default '{}' so existing rows backfill to an empty dict
    # without a separate UPDATE pass; the column is NOT NULL.
    op.add_column(
        "comparison_runs",
        sa.Column(
            "translations_he",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("comparison_runs", "translations_he")
