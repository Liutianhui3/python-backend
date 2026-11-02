"""Align users with my-blob-api without recreating the table."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "92f0b3c1a801"
down_revision = "4a74ba13dd88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 先允许 NULL，回填已有用户昵称后再加非空约束，保留原有数据。
    op.add_column("users", sa.Column("name", sa.String(100), nullable=True))
    op.execute("UPDATE users SET name = username")
    op.alter_column("users", "name", nullable=False)
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    for name, kind in (
        ("location", sa.String(60)),
        ("website", sa.String(240)),
        ("bio", sa.String(200)),
        ("avatar", sa.Text()),
        ("phone", sa.String(30)),
        ("about", sa.String(2000)),
    ):
        op.add_column("users", sa.Column(name, kind, nullable=False, server_default=""))
    for name in ("skills", "work_experiences"):
        op.add_column(
            "users",
            sa.Column(
                name, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
            ),
        )
    op.alter_column("users", "username", nullable=True)
    op.alter_column("users", "password_hash", nullable=True)


def downgrade() -> None:
    # 存在仅资料用户时拒绝回退，避免为了恢复非空约束而删用户。
    op.alter_column("users", "username", nullable=False)
    op.alter_column("users", "password_hash", nullable=False)
    for name in (
        "name",
        "is_admin",
        "location",
        "website",
        "bio",
        "avatar",
        "phone",
        "about",
        "skills",
        "work_experiences",
    ):
        op.drop_column("users", name)
