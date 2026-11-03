from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from python_backend.db.base import Base
from python_backend.modules.roles.models import Role


class User(Base):
    """用户数据库模型；定义结构不会自动在数据库中建表。"""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # 旧项目支持仅创建资料的用户，因此用户名、密码允许 NULL；注册时仍必填。
    username: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100))
    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles", viewonly=True, order_by=Role.id
    )
    # 资料默认空字符串，不要求注册时填写；管理员权限不能从注册请求传入。
    location: Mapped[str] = mapped_column(String(60), server_default="")
    website: Mapped[str] = mapped_column(String(240), server_default="")
    bio: Mapped[str] = mapped_column(String(200), server_default="")
    avatar: Mapped[str] = mapped_column(Text, server_default="")
    phone: Mapped[str] = mapped_column(String(30), server_default="")
    about: Mapped[str] = mapped_column(String(2000), server_default="")
    # PostgreSQL 实际使用 JSONB；JSON 变体也方便用 SQLite 隔离测试。
    skills: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), server_default=text("'[]'")
    )
    work_experiences: Mapped[list[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), server_default=text("'[]'")
    )
    email: Mapped[str] = mapped_column(String(254))
    # 只保存密码哈希，不保存注册请求中的明文密码。
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 与原注册逻辑一致：用户名和邮箱不能仅大小写不同就重复注册。
    __table_args__ = (
        Index("users_username_unique", func.lower(username), unique=True),
        Index("users_email_unique", func.lower(email), unique=True),
    )
