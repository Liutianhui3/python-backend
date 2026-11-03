"""Add the article editor system role."""

import sqlalchemy as sa
from alembic import op

revision = "b6c0e43d217a"
down_revision = "a5b9d32c106f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    roles = sa.table(
        "roles",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String(100)),
        sa.column("nameCn", sa.String(100)),
    )
    op.bulk_insert(roles, [{"id": 3, "name": "editor", "nameCn": "文章编辑"}])


def downgrade() -> None:
    # 系统角色可能已经分配给用户，禁止回退时级联删除这些关联。
    raise RuntimeError("The editor role may be in use and cannot be automatically removed")
