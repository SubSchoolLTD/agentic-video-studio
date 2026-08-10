"""Add users, secure sessions, billing, promo codes, and platform admin data.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_status", "users", ["status"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_session_id", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "email_tokens",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_tokens_user_id", "email_tokens", ["user_id"])
    op.create_index("ix_email_tokens_email_kind", "email_tokens", ["email", "kind", "created_at"])
    op.create_table(
        "wallets",
        sa.Column("organization_id", sa.String(64), primary_key=True),
        sa.Column("balance_tokens", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("amount_tokens", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("feature_key", sa.String(96), nullable=True),
        sa.Column("reference_id", sa.String(128), nullable=True),
        sa.Column("monetary_amount_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_ledger_organization_id", "credit_ledger", ["organization_id"])
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])
    op.create_index("ix_credit_ledger_event_type", "credit_ledger", ["event_type"])
    op.create_index("ix_credit_ledger_org_created", "credit_ledger", ["organization_id", "created_at"])
    op.create_table(
        "price_rules",
        sa.Column("feature_key", sa.String(96), primary_key=True),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("provider_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("charge_tokens", sa.BigInteger(), nullable=False),
        sa.Column("margin_percent", sa.Numeric(8, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_prefix", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("credit_tokens", sa.BigInteger(), nullable=False),
        sa.Column("subscription_days", sa.Integer(), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redemption_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_promo_codes_code_prefix", "promo_codes", ["code_prefix"])
    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("promo_code_id", sa.String(64), sa.ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("promo_code_id", "user_id", name="uq_promo_user"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("organization_id", sa.String(64), primary_key=True),
        sa.Column("plan", sa.String(48), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
    op.drop_table("promo_redemptions")
    op.drop_index("ix_promo_codes_code_prefix", table_name="promo_codes")
    op.drop_table("promo_codes")
    op.drop_table("price_rules")
    op.drop_index("ix_credit_ledger_org_created", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_event_type", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_user_id", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_organization_id", table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_table("wallets")
    op.drop_index("ix_email_tokens_email_kind", table_name="email_tokens")
    op.drop_index("ix_email_tokens_user_id", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
