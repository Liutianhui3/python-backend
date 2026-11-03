"""角色查询、用户筛选及角色分配事务，不依赖 HTTP。"""

from uuid import UUID

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from python_backend.modules.roles.models import Role, UserRole
from python_backend.modules.roles.schemas import RoleAssignment
from python_backend.modules.users.models import User
from python_backend.modules.users.schemas import UserResponse


class RolePermissionError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class InvalidRoleError(Exception):
    pass


class LastAdminError(Exception):
    pass


def list_roles(session: Session):
    return session.scalars(select(Role).order_by(Role.id)).all()


def list_users(session: Session, page: int = 1, limit: int = 20, q: str = "", role: str = ""):
    conditions = []
    if q.strip():
        conditions.append(
            or_(
                User.username.icontains(q.strip(), autoescape=True),
                User.name.icontains(q.strip(), autoescape=True),
                User.email.icontains(q.strip(), autoescape=True),
            )
        )
    if role:
        conditions.append(User.roles.any(Role.name == ("common" if role == "user" else role)))
    total = session.scalar(select(func.count()).select_from(User).where(*conditions))
    users = session.scalars(
        select(User)
        .where(*conditions)
        .options(selectinload(User.roles))
        .order_by(User.created_at.desc(), User.id)
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()
    return {"items": users, "total": total, "page": page, "limit": limit}


def assign_roles(user_id: UUID, body: RoleAssignment, session: Session, actor: User):
    try:
        # 串行角色写入；锁内重查调用者，防止并发降权后仍可授权。
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(72401963)"))
        if (
            session.scalar(
                select(UserRole).where(UserRole.user_id == actor.id, UserRole.role_id == 1)
            )
            is None
        ):
            raise RolePermissionError("无权限访问，请重新登录")
        target = session.get(User, user_id)
        if target is None:
            raise UserNotFoundError("用户不存在")
        role_ids = set(body.role_ids)
        existing = set(session.scalars(select(Role.id).where(Role.id.in_(role_ids))))
        if existing != role_ids:
            raise InvalidRoleError("包含不存在的角色")
        has_admin = session.get(UserRole, (user_id, 1)) is not None
        if has_admin and 1 not in role_ids:
            count = session.scalar(
                select(func.count()).select_from(UserRole).where(UserRole.role_id == 1)
            )
            if count <= 1:
                raise LastAdminError("请至少保留一位管理员")
        session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        session.add_all(UserRole(user_id=user_id, role_id=role_id) for role_id in role_ids)
        session.commit()
        session.expire(target, ["roles"])
        return UserResponse.model_validate(target)
    except Exception:
        session.rollback()
        raise
