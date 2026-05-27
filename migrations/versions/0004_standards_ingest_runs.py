"""standards_ingest_runs — track refreshes of the standards corpus

Revision ID: 0004_standards_ingest_runs
Revises: 0003_comparison_verification
Create Date: 2026-05-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_standards_ingest_runs"
down_revision: str | None = "0003_comparison_verification"
branch_labels = None
depends_on = None


INGEST_STATUS = postgresql.ENUM(
    "running", "done", "failed",
    name="standards_ingest_status", create_type=False,
)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE standards_ingest_status AS ENUM ('running', 'done', 'failed');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.create_table(
        "standards_ingest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # source_id from config/sources.yaml — string, not FK, because the
        # registry lives in YAML not the DB.
        sa.Column("source_id", sa.String(80), nullable=False),
        sa.Column("status", INGEST_STATUS, nullable=False, server_default="running"),
        sa.Column("chunks_count", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_standards_ingest_runs_source_id",
        "standards_ingest_runs",
        ["source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_standards_ingest_runs_source_id", table_name="standards_ingest_runs")
    op.drop_table("standards_ingest_runs")
    op.execute("DROP TYPE IF EXISTS standards_ingest_status CASCADE;")
