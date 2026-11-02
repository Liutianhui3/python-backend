import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator
from pydantic.alias_generators import to_camel


class RegisterRequest(BaseModel):
    """注册时前端提交的数据；不是数据库表模型。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("username", "email", mode="before")
    @classmethod
    def normalize_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not re.search(r"[a-zA-Z]", password) or not re.search(r"[0-9]", password):
            raise ValueError("密码需包含字母和数字")
        return value


class WorkExperience(BaseModel):
    """JSONB 工作经历结构，与旧接口的字段名一致。"""

    id: str
    company: str
    position: str
    startDate: str
    endDate: str
    description: str


class UserResponse(BaseModel):
    """只列出公开字段；即使 ORM 有密码哈希，也不会被返回。"""

    model_config = ConfigDict(from_attributes=True, alias_generator=to_camel, populate_by_name=True)

    id: UUID
    is_admin: bool
    name: str
    email: str
    username: str | None
    location: str
    website: str
    bio: str
    avatar: str
    phone: str
    about: str
    skills: list[str]
    work_experiences: list[WorkExperience]
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def trim_username(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class LoginResponse(BaseModel):
    user: UserResponse
    token: str
