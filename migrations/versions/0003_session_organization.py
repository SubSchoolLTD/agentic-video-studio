"""Bind refresh sessions to one organization.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("organization_id", sa.String(64), nullable=True))
    # Sessions created before organization binding cannot be refreshed safely.
    # Revoking them is deterministic and affects authentication only, not user data.
    op.execute("DELETE FROM auth_sessions")
    with op.batch_alter_table("auth_sessions") as batch:
        batch.alter_column("organization_id", existing_type=sa.String(64), nullable=False)
        batch.create_index("ix_auth_sessions_organization_id", ["organization_id"])


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_index("ix_auth_sessions_organization_id")
        batch.drop_column("organization_id")
