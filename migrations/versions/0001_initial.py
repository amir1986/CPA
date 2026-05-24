"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


# create_type=False on the ENUM objects so SQLAlchemy will NOT try to
# auto-CREATE TYPE when a table that references one of these is created.
# We pre-create idempotently below via DO/EXCEPTION blocks instead.
USER_ROLE = postgresql.ENUM("partner", "manager", "senior", "staff", "admin", name="user_role", create_type=False)
ENG_TYPE = postgresql.ENUM("audit", "review", "compilation", "tax", "bookkeeping", name="engagement_type", create_type=False)
ENG_STATUS = postgresql.ENUM("planning", "fieldwork", "review", "signed_off", "archived", name="engagement_status", create_type=False)
FILE_KIND = postgresql.ENUM("trial_balance", "gl", "bank", "invoice", "financial_statements", "contract", "policy", "other", name="file_kind", create_type=False)
PARSED_STATUS = postgresql.ENUM("queued", "extracting", "canonicalizing", "done", "failed", name="parsed_status", create_type=False)
ACCOUNT_TYPE = postgresql.ENUM("asset", "liability", "equity", "revenue", "expense", name="account_type", create_type=False)
RECON_KIND = postgresql.ENUM("bank", "intercompany", name="reconciliation_kind", create_type=False)
TOKEN_KIND = postgresql.ENUM("verify_email", "password_reset", name="auth_token_kind", create_type=False)


_ENUM_DEFS = [
    ("user_role", ("partner", "manager", "senior", "staff", "admin")),
    ("engagement_type", ("audit", "review", "compilation", "tax", "bookkeeping")),
    ("engagement_status", ("planning", "fieldwork", "review", "signed_off", "archived")),
    ("file_kind", ("trial_balance", "gl", "bank", "invoice", "financial_statements", "contract", "policy", "other")),
    ("parsed_status", ("queued", "extracting", "canonicalizing", "done", "failed")),
    ("account_type", ("asset", "liability", "equity", "revenue", "expense")),
    ("reconciliation_kind", ("bank", "intercompany")),
    ("auth_token_kind", ("verify_email", "password_reset")),
]


def _create_enum_idempotent(name: str, values: tuple[str, ...]) -> None:
    """Postgres has no `CREATE TYPE IF NOT EXISTS`. Wrap in DO/EXCEPTION
    so re-runs against a half-applied database succeed instead of crashing
    on `duplicate_object`."""
    values_sql = ", ".join(f"'{v}'" for v in values)
    op.execute(f"""
    DO $$ BEGIN
        CREATE TYPE {name} AS ENUM ({values_sql});
    EXCEPTION WHEN duplicate_object THEN null;
    END $$;
    """)


_TABLES_REVERSE = [
    "audit_log", "agent_runs", "query_log",
    "audit_findings", "workpapers", "audit_programs",
    "three_way_matches", "je_test_runs", "samples",
    "reconciliations", "bank_statements",
    "coa_mappings", "trial_balances", "gl_entries", "chart_of_accounts",
    "files", "engagements", "clients",
    "auth_tokens", "user_tweaks", "users", "firms",
]


def upgrade() -> None:
    # Defensive reset: an earlier deploy crashed partway through this
    # initial migration (after creating some tables/types but before
    # completing), leaving the DB in a half-applied state that vanilla
    # CREATE TABLE / CREATE TYPE can't reconcile. Drop everything CASCADE
    # so the rest of upgrade() runs against a clean slate. Safe because
    # this is the initial migration — no user data could exist yet that
    # we wouldn't already be recreating.
    op.execute(f"DROP TABLE IF EXISTS {', '.join(_TABLES_REVERSE)} CASCADE;")
    op.execute(
        "DROP TYPE IF EXISTS "
        + ", ".join(name for name, _ in _ENUM_DEFS)
        + " CASCADE;"
    )

    for name, values in _ENUM_DEFS:
        _create_enum_idempotent(name, values)

    op.create_table(
        "firms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("default_jurisdiction", sa.String(8), nullable=True),
        sa.Column("base_currency", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("firms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False, server_default="staff"),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("locale", sa.String(8), nullable=False, server_default="en"),
        sa.Column("api_key_hash", sa.String(255), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_firm_id", "users", ["firm_id"])

    op.create_table(
        "user_tweaks",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("top_k", sa.Integer, nullable=True),
        sa.Column("min_score", sa.Float, nullable=True),
        sa.Column("lang_strict", sa.Boolean, nullable=True),
        sa.Column("ratio_overrides", postgresql.JSONB, nullable=True),
        sa.Column("sampling_overrides", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", TOKEN_KIND, nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"])

    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("firms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("jurisdiction", sa.String(8), nullable=True),
        sa.Column("base_currency", sa.String(8), nullable=True),
        sa.Column("fy_end", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clients_firm_id", "clients", ["firm_id"])

    op.create_table(
        "engagements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", ENG_TYPE, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("period_start", sa.Date, nullable=True),
        sa.Column("period_end", sa.Date, nullable=True),
        sa.Column("materiality", sa.Numeric(20, 2), nullable=True),
        sa.Column("performance_materiality", sa.Numeric(20, 2), nullable=True),
        sa.Column("status", ENG_STATUS, nullable=False, server_default="planning"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_engagements_client_id", "engagements", ["client_id"])

    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", FILE_KIND, nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("s3_uri", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(255), nullable=True),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("parsed_status", PARSED_STATUS, nullable=False, server_default="queued"),
        sa.Column("parsed_summary", postgresql.JSONB, nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_files_engagement_id", "files", ["engagement_id"])
    op.create_index("ix_files_sha256", "files", ["sha256"])

    op.create_table(
        "chart_of_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", ACCOUNT_TYPE, nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("engagement_id", "code", name="uq_chart_of_accounts_engagement_id_code"),
    )
    op.create_index("ix_chart_of_accounts_engagement_id", "chart_of_accounts", ["engagement_id"])

    op.create_table(
        "gl_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("je_number", sa.String(64), nullable=True),
        sa.Column("je_date", sa.Date, nullable=True),
        sa.Column("posting_date", sa.Date, nullable=True),
        sa.Column("debit", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("fx_rate", sa.Numeric(20, 8), nullable=True),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("document_ref", sa.String(255), nullable=True),
        sa.Column("preparer", sa.String(120), nullable=True),
        sa.Column("approver", sa.String(120), nullable=True),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gl_entries_engagement_id", "gl_entries", ["engagement_id"])
    op.create_index("ix_gl_entries_account_id", "gl_entries", ["account_id"])
    op.create_index("ix_gl_entries_je_date", "gl_entries", ["je_date"])

    op.create_table(
        "trial_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_code", sa.String(64), nullable=True),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("opening", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("debit_total", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("credit_total", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("closing", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trial_balances_engagement_id", "trial_balances", ["engagement_id"])

    op.create_table(
        "coa_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule", postgresql.JSONB, nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("learned_from_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_coa_mappings_engagement_id", "coa_mappings", ["engagement_id"])

    op.create_table(
        "bank_statements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chart_of_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("statement_date", sa.Date, nullable=True),
        sa.Column("line_no", sa.Integer, nullable=True),
        sa.Column("value_date", sa.Date, nullable=True),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("balance", sa.Numeric(20, 4), nullable=True),
        sa.Column("matched_je_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gl_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bank_statements_engagement_id", "bank_statements", ["engagement_id"])

    op.create_table(
        "reconciliations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", RECON_KIND, nullable=False),
        sa.Column("period_end", sa.Date, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("summary", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reconciliations_engagement_id", "reconciliations", ["engagement_id"])

    op.create_table(
        "samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("population_query", postgresql.JSONB, nullable=False),
        sa.Column("sample_size", sa.Integer, nullable=False),
        sa.Column("sample_ids", postgresql.JSONB, nullable=False),
        sa.Column("seed", sa.BigInteger, nullable=False),
        sa.Column("performance_materiality", sa.Numeric(20, 2), nullable=True),
        sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_samples_engagement_id", "samples", ["engagement_id"])

    op.create_table(
        "je_test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_kind", sa.String(48), nullable=False),
        sa.Column("filters", postgresql.JSONB, nullable=False),
        sa.Column("hits_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hits", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ran_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_je_test_runs_engagement_id", "je_test_runs", ["engagement_id"])

    op.create_table(
        "three_way_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("results_summary", postgresql.JSONB, nullable=False),
        sa.Column("exceptions", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_three_way_matches_engagement_id", "three_way_matches", ["engagement_id"])

    op.create_table(
        "audit_programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("area", sa.String(64), nullable=False),
        sa.Column("procedures", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_programs_engagement_id", "audit_programs", ["engagement_id"])

    op.create_table(
        "workpapers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body_md", sa.Text, nullable=False),
        sa.Column("pdf_s3_uri", sa.String(1024), nullable=True),
        sa.Column("references", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("prepared_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workpapers_engagement_id", "workpapers", ["engagement_id"])

    op.create_table(
        "audit_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workpaper_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workpapers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assertion", sa.String(64), nullable=True),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_findings_engagement_id", "audit_findings", ["engagement_id"])

    op.create_table(
        "query_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("language", sa.String(8), nullable=True),
        sa.Column("citations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("refused", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_query_log_engagement_id", "query_log", ["engagement_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("engagement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engagements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request", sa.Text, nullable=False),
        sa.Column("plan", postgresql.JSONB, nullable=True),
        sa.Column("tool_calls", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("final_answer", sa.Text, nullable=True),
        sa.Column("citations", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_engagement_id", "agent_runs", ["engagement_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(48), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("meta", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_firm_id", "audit_log", ["firm_id"])


def downgrade() -> None:
    for table in [
        "audit_log", "agent_runs", "query_log",
        "audit_findings", "workpapers", "audit_programs",
        "three_way_matches", "je_test_runs", "samples",
        "reconciliations", "bank_statements",
        "coa_mappings", "trial_balances", "gl_entries", "chart_of_accounts",
        "files", "engagements", "clients",
        "auth_tokens", "user_tweaks", "users", "firms",
    ]:
        op.drop_table(table)
    bind = op.get_bind()
    for enum in (TOKEN_KIND, RECON_KIND, ACCOUNT_TYPE, PARSED_STATUS, FILE_KIND, ENG_STATUS, ENG_TYPE, USER_ROLE):
        enum.drop(bind, checkfirst=True)
