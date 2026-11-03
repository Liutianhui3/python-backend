from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from python_backend.db.base import Base


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), default="随笔")
    tags: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list
    )
    cover_url: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    version: Mapped[int] = mapped_column(server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
