"""Remove database-backed authentication sessions."""

from alembic import op

revision = "c8d0f6a12b34"
down_revision = "b137d42f8a90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("user_sessions")


def downgrade() -> None:
    raise RuntimeError(
        "user_sessions was replaced by JWT and Redis; this migration is irreversible"
    )
