"""Make promo codes independent fixed-value balance credits.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE promo_codes SET kind = 'balance_credit', bonus_percent = 0")


def downgrade() -> None:
    op.execute("UPDATE promo_codes SET kind = 'topup_bonus'")
