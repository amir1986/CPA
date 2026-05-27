"""comparison_issues: add verification columns

Revision ID: 0003_comparison_verification
Revises: 0002_comparison_runs
Create Date: 2026-05-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_comparison_verification"
down_revision: str | None = "0002_comparison_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-side verification narratives from the new verifier agent step.
    # NULL is allowed for back-compat with existing rows and for runs where
    # the verifier couldn't run (e.g. corpus empty, synthesis fallback).
    op.add_column(
        "comparison_issues",
        sa.Column("gaap_verification", sa.Text, nullable=True),
    )
    op.add_column(
        "comparison_issues",
        sa.Column("ifrs_verification", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comparison_issues", "ifrs_verification")
    op.drop_column("comparison_issues", "gaap_verification")
