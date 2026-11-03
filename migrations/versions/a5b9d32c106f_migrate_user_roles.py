"""Backfill user roles and remove is_admin."""

import sqlalchemy as sa
from alembic import op

revision = "a5b9d32c106f"
down_revision = "f4a8c21b095e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为已有用户补普通角色；保留原管理员权限，避免删除字段后丢失。
    op.execute(
        sa.text(
            "INSERT INTO user_roles (user_id, role_id) SELECT id, 2 FROM users "
            "ON CONFLICT (user_id, role_id) DO NOTHING"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO user_roles (user_id, role_id) SELECT id, 1 FROM users WHERE is_admin "
            "ON CONFLICT (user_id, role_id) DO NOTHING"
        )
    )
    op.drop_column("users", "is_admin")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.execute(
        sa.text(
            "UPDATE users SET is_admin = true WHERE EXISTS "
            "(SELECT 1 FROM user_roles WHERE user_id = users.id AND role_id = 1)"
        )
    )
    # 角色关联可能在迁移后被业务修改，回退时保留它们。
