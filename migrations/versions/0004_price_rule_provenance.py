"""Add provider and model provenance to configurable price rules.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_rules") as batch:
        batch.add_column(sa.Column("provider", sa.String(96), nullable=True))
        batch.add_column(sa.Column("integration", sa.String(160), nullable=True))
        batch.add_column(sa.Column("model_id", sa.String(200), nullable=True))
    op.execute("UPDATE price_rules SET provider = 'internal', integration = 'Framewise'")
    with op.batch_alter_table("price_rules") as batch:
        batch.alter_column("provider", existing_type=sa.String(96), nullable=False)
        batch.alter_column("integration", existing_type=sa.String(160), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("price_rules") as batch:
        batch.drop_column("model_id")
        batch.drop_column("integration")
        batch.drop_column("provider")
