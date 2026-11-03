"""角色表定义。"""

from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from python_backend.db.base import Base


class Role(Base):
    __tablename__ = "roles"

    # 系统角色使用固定整数 ID，新增角色时显式指定。
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100))
    name_cn: Mapped[str] = mapped_column("nameCn", String(100))


class UserRole(Base):
    """联合主键防止同一用户重复分配同一角色。"""

    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, index=True
    )
