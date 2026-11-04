"""Persist provider-exposed reasoning separately from final answers."""

import sqlalchemy as sa
from alembic import op

revision = "a4f71b0d93e2"
down_revision = "92fe31c8a104"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "messages", sa.Column("reasoning_content", sa.Text(), nullable=False, server_default="")
    )
    op.alter_column("messages", "reasoning_content", server_default=None)


def downgrade():
    op.drop_column("messages", "reasoning_content")
