"""角色管理 HTTP 路由：参数、管理员认证和业务异常转换。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from python_backend.modules.roles import service
from python_backend.modules.roles.schemas import RoleAssignment, UserPage
from python_backend.modules.users.models import User
from python_backend.modules.users.router import SessionDependency, require_admin
from python_backend.modules.users.schemas import RoleResponse, UserResponse

router = APIRouter(prefix="/admin", tags=["roles"], dependencies=[Depends(require_admin)])


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(session: SessionDependency):
    return service.list_roles(session)


@router.get("/users", response_model=UserPage)
def list_users(
    session: SessionDependency,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str, Query(max_length=100)] = "",
    role: Annotated[str, Query(max_length=100)] = "",
):
    return service.list_users(session, page, limit, q, role)


@router.patch("/users/{user_id}/role", response_model=UserResponse)
def assign_roles(
    user_id: UUID,
    body: RoleAssignment,
    session: SessionDependency,
    actor: Annotated[User, Depends(require_admin)],
):
    try:
        return service.assign_roles(user_id, body, session, actor)
    except service.RolePermissionError as error:
        raise HTTPException(403, str(error)) from error
    except service.UserNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except service.InvalidRoleError as error:
        raise HTTPException(422, str(error)) from error
    except service.LastAdminError as error:
        raise HTTPException(409, str(error)) from error
