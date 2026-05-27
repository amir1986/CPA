"""comparison_runs + comparison_issues, plus comparisons engagement type

Revision ID: 0002_comparison_runs
Revises: 0001_initial
Create Date: 2026-05-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_comparison_runs"
down_revision: str | None = "0001_initial"
branch_labels = None
depends_on = None


COMPARISON_STATUS = postgresql.ENUM(
    "parsing", "detecting", "comparing", "done", "failed",
    name="comparison_status", create_type=False,
)
COMPARISON_FRAMEWORK = postgresql.ENUM(
    "US", "IFRS", name="comparison_framework", create_type=False,
)


def _create_enum_idempotent(name: str, values: tuple[str, ...]) -> None:
    """Postgres has no CREATE TYPE IF NOT EXISTS — wrap in DO/EXCEPTION."""
    values_sql = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE {name} AS ENUM ({values_sql});
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )


def upgrade() -> None:
    # 1. Extend the existing engagement_type enum with 'comparisons' so the
    #    hidden per-user comparisons engagement can be created.
    op.execute(
        """
        DO $$ BEGIN
            ALTER TYPE engagement_type ADD VALUE IF NOT EXISTS 'comparisons';
        EXCEPTION WHEN undefined_object THEN null;
        END $$;
        """
    )

    # 2. New enums for the comparison-runs subsystem.
    _create_enum_idempotent("comparison_status", ("parsing", "detecting", "comparing", "done", "failed"))
    _create_enum_idempotent("comparison_framework", ("US", "IFRS"))

    op.create_table(
        "comparison_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engagements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", COMPARISON_STATUS, nullable=False, server_default="parsing"),
        sa.Column("detected_framework", COMPARISON_FRAMEWORK, nullable=True),
        sa.Column("override_framework", COMPARISON_FRAMEWORK, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("file_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_comparison_runs_engagement_id", "comparison_runs", ["engagement_id"])
    op.create_index("ix_comparison_runs_user_id", "comparison_runs", ["user_id"])

    op.create_table(
        "comparison_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("comparison_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("current_summary", sa.Text, nullable=False),
        sa.Column("current_user_cites", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("gaap_summary", sa.Text, nullable=True),
        sa.Column("gaap_citations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("ifrs_summary", sa.Text, nullable=True),
        sa.Column("ifrs_citations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("differences", sa.Text, nullable=True),
        sa.Column("conversion_impact", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_comparison_issues_run_id", "comparison_issues", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_comparison_issues_run_id", table_name="comparison_issues")
    op.drop_table("comparison_issues")
    op.drop_index("ix_comparison_runs_user_id", table_name="comparison_runs")
    op.drop_index("ix_comparison_runs_engagement_id", table_name="comparison_runs")
    op.drop_table("comparison_runs")
    op.execute("DROP TYPE IF EXISTS comparison_framework CASCADE;")
    op.execute("DROP TYPE IF EXISTS comparison_status CASCADE;")
    # We can't remove 'comparisons' from engagement_type cleanly in Postgres;
    # leave it (additive change).
