"""Create authentication sessions compatible with my-blob-api."""

import sqlalchemy as sa
from alembic import op

revision = "b137d42f8a90"
down_revision = "92f0b3c1a801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_sessions")
