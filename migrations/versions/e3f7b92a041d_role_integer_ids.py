"""Use explicit integer role IDs and seed system roles."""

import sqlalchemy as sa
from alembic import op

revision = "e3f7b92a041d"
down_revision = "d2e8a71f093c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # UUID 无法直接转换为业务整数 ID；有数据时应先设计映射，不能静默丢弃。
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE roles IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(sa.text("SELECT count(*) FROM roles")):
        raise RuntimeError("roles must be empty before switching UUID IDs to integer IDs")
    op.alter_column(
        "roles",
        "id",
        existing_type=sa.Uuid(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="NULL::integer",
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String(100)),
        sa.column("nameCn", sa.String(100)),
    )
    op.bulk_insert(
        roles,
        [
            {"id": 1, "name": "admin", "nameCn": "管理员"},
            {"id": 2, "name": "common", "nameCn": "普通用户"},
        ],
    )


def downgrade() -> None:
    raise RuntimeError("Integer role IDs cannot be restored to their original UUID values")
