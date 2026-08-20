"""Replace token subscriptions with a USD-cent wallet and PayPal top-ups.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wallets") as batch:
        batch.alter_column("balance_tokens", new_column_name="balance_cents", existing_type=sa.BigInteger())
    with op.batch_alter_table("credit_ledger") as batch:
        batch.alter_column("amount_tokens", new_column_name="amount_cents", existing_type=sa.BigInteger())
    with op.batch_alter_table("price_rules") as batch:
        batch.alter_column(
            "provider_cost_usd",
            new_column_name="provider_cost_per_unit_usd",
            existing_type=sa.Numeric(12, 6),
        )
        batch.alter_column("charge_tokens", new_column_name="charge_cents", existing_type=sa.BigInteger())
    with op.batch_alter_table("promo_codes") as batch:
        batch.alter_column("credit_tokens", new_column_name="bonus_cents", existing_type=sa.BigInteger())
        batch.add_column(sa.Column("bonus_percent", sa.Numeric(8, 2), nullable=True))
    op.execute("UPDATE promo_codes SET kind = 'topup_bonus', bonus_percent = 0")
    with op.batch_alter_table("promo_codes") as batch:
        batch.alter_column("bonus_percent", existing_type=sa.Numeric(8, 2), nullable=False)
        batch.drop_column("subscription_days")
    with op.batch_alter_table("promo_redemptions") as batch:
        batch.add_column(sa.Column("topup_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("bonus_cents", sa.BigInteger(), nullable=True))
        batch.create_index("ix_promo_redemptions_topup_id", ["topup_id"])
    op.execute("UPDATE promo_redemptions SET bonus_cents = 0")
    with op.batch_alter_table("promo_redemptions") as batch:
        batch.alter_column("bonus_cents", existing_type=sa.BigInteger(), nullable=False)

    op.create_table(
        "paypal_topups",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paypal_order_id", sa.String(64), nullable=True, unique=True),
        sa.Column("paypal_capture_id", sa.String(64), nullable=True, unique=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("bonus_cents", sa.BigInteger(), nullable=False),
        sa.Column("promo_code_id", sa.String(64), sa.ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(96), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paypal_topups_organization_id", "paypal_topups", ["organization_id"])
    op.create_index("ix_paypal_topups_user_id", "paypal_topups", ["user_id"])
    op.create_index("ix_paypal_topups_promo_code_id", "paypal_topups", ["promo_code_id"])
    op.create_index("ix_paypal_topups_status", "paypal_topups", ["status"])
    op.create_index("ix_paypal_topups_org_created", "paypal_topups", ["organization_id", "created_at"])
    op.execute(
        "UPDATE price_rules SET provider_cost_per_unit_usd = 0.20, charge_cents = 24, "
        "margin_percent = 20.00, unit = 'generated second per aspect ratio' "
        "WHERE feature_key = 'video.generate'"
    )
    op.execute(
        "UPDATE price_rules SET provider_cost_per_unit_usd = 0.40, charge_cents = 48, "
        "margin_percent = 20.00, unit = 'generated second per aspect ratio' "
        "WHERE feature_key = 'video.generate_native_audio'"
    )
    op.execute(
        "UPDATE price_rules SET provider_cost_per_unit_usd = 0.20, charge_cents = 24, "
        "margin_percent = 20.00, unit = 'generated second' "
        "WHERE feature_key = 'video.scene_regenerate'"
    )
    op.execute(
        "UPDATE price_rules SET provider_cost_per_unit_usd = 0.40, charge_cents = 48, "
        "margin_percent = 20.00, unit = 'generated second' "
        "WHERE feature_key = 'video.scene_regenerate_native_audio'"
    )
    op.execute(
        "UPDATE price_rules SET provider_cost_per_unit_usd = 0.02, charge_cents = 3, "
        "margin_percent = 20.00 WHERE feature_key = 'project.website_analysis'"
    )
    op.execute(
        "UPDATE price_rules SET provider_cost_per_unit_usd = 0.05, charge_cents = 6, "
        "margin_percent = 20.00 WHERE feature_key = 'research.run'"
    )
    op.execute(
        "UPDATE price_rules SET provider_cost_per_unit_usd = 0.04, charge_cents = 5, "
        "margin_percent = 20.00 WHERE feature_key = 'character.generate'"
    )
    op.drop_table("subscriptions")


def downgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("organization_id", sa.String(64), primary_key=True),
        sa.Column("plan", sa.String(48), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.drop_index("ix_paypal_topups_org_created", table_name="paypal_topups")
    op.drop_table("paypal_topups")
    with op.batch_alter_table("promo_redemptions") as batch:
        batch.drop_index("ix_promo_redemptions_topup_id")
        batch.drop_column("bonus_cents")
        batch.drop_column("topup_id")
    with op.batch_alter_table("promo_codes") as batch:
        batch.add_column(sa.Column("subscription_days", sa.Integer(), nullable=False, server_default="0"))
        batch.drop_column("bonus_percent")
        batch.alter_column("bonus_cents", new_column_name="credit_tokens", existing_type=sa.BigInteger())
    with op.batch_alter_table("price_rules") as batch:
        batch.alter_column("charge_cents", new_column_name="charge_tokens", existing_type=sa.BigInteger())
        batch.alter_column(
            "provider_cost_per_unit_usd",
            new_column_name="provider_cost_usd",
            existing_type=sa.Numeric(12, 6),
        )
    with op.batch_alter_table("credit_ledger") as batch:
        batch.alter_column("amount_cents", new_column_name="amount_tokens", existing_type=sa.BigInteger())
    with op.batch_alter_table("wallets") as batch:
        batch.alter_column("balance_cents", new_column_name="balance_tokens", existing_type=sa.BigInteger())
