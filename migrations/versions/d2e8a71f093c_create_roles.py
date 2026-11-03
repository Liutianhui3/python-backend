"""Create roles with id, name and nameCn."""

import sqlalchemy as sa
from alembic import op

revision = "d2e8a71f093c"
down_revision = "c8d0f6a12b34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("nameCn", sa.String(100), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("roles")
