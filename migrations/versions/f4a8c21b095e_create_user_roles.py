"""Create user-role associations."""

import sqlalchemy as sa
from alembic import op

revision = "f4a8c21b095e"
down_revision = "e3f7b92a041d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])


def downgrade() -> None:
    op.drop_table("user_roles")
