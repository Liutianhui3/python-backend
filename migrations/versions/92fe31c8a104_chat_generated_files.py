"""Persist generated Office files linked to chat messages."""

import sqlalchemy as sa
from alembic import op

revision = "92fe31c8a104"
down_revision = "71ad6c209e45"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_generated_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_chat_generated_files_message_id", "chat_generated_files", ["message_id"])


def downgrade():
    op.drop_table("chat_generated_files")
