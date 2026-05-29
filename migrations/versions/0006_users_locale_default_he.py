"""align users.locale server default with the ORM (he)

Revision ID: 0006_users_locale_default_he
Revises: 0005_comparison_translations_he
Create Date: 2026-05-29

Commit 597beda made Hebrew the default locale and changed the ORM column
default to "he", but the original 0001 migration still pinned the Postgres
``server_default`` to "en". Any INSERT that doesn't go through the ORM (raw
SQL, ``INSERT ... DEFAULT``) therefore disagreed with the application and
landed an English locale. Realign the server default so the DB and the app
agree.
"""
from __future__ import annotations

from alembic import op

revision: str = "0006_users_locale_default_he"
down_revision: str | None = "0005_comparison_translations_he"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "locale", server_default="he")


def downgrade() -> None:
    op.alter_column("users", "locale", server_default="en")
