"""角色管理接口请求与响应结构。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from python_backend.modules.users.schemas import UserResponse


class UserPage(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    limit: int


class RoleAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    role_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(
        alias="roleIds", min_length=1, max_length=100
    )
