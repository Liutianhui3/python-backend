"""对应 NestJS Controller：只负责 HTTP 输入、输出和异常映射。"""

import time
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from python_backend.core.redis_client import redis_client
from python_backend.core.security import decode_access_token
from python_backend.db.session import get_session
from python_backend.modules.users.models import User
from python_backend.modules.users.schemas import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
)
from python_backend.modules.users.service import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    current_user,
    login_user,
    register_user,
)

router = APIRouter(prefix="/users", tags=["users"])
bearer = HTTPBearer(auto_error=False)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: RegisterRequest, session: Annotated[Session, Depends(get_session)]
) -> UserResponse:
    # 同步数据库和 scrypt 使用普通 def，FastAPI 会在线程池运行，避免阻塞事件循环。
    try:
        user = register_user(session, request)
    except UserAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail="用户名或邮箱已被使用") from error
    return UserResponse.model_validate(user)


SessionDependency = Annotated[Session, Depends(get_session)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def token_payload(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        return decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError as error:
        raise HTTPException(status_code=401, detail="请先登录") from error


def is_revoked(jti: str) -> bool:
    try:
        return bool(redis_client.exists(f"blacklist:{jti}"))
    except RedisError as error:
        raise HTTPException(status_code=503, detail="认证服务暂不可用") from error


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, session: SessionDependency) -> LoginResponse:
    try:
        user, token = login_user(session, request.username, request.password.get_secret_value())
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail="用户名或密码不正确") from error
    return LoginResponse(user=UserResponse.model_validate(user), token=token)


def authenticated_user(credentials: Credentials, session: SessionDependency) -> User:
    payload = token_payload(credentials)
    if is_revoked(payload["jti"]):
        raise HTTPException(status_code=401, detail="请先登录")
    user = current_user(session, payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


AuthenticatedUser = Annotated[User, Depends(authenticated_user)]


def require_admin(user: AuthenticatedUser) -> User:
    if not any(role.id == 1 for role in user.roles):
        raise HTTPException(status_code=403, detail="无权限访问，请重新登录")
    return user


def require_editor(user: AuthenticatedUser) -> User:
    if not any(role.id in (1, 3) for role in user.roles):
        raise HTTPException(status_code=403, detail="无权限访问，请重新登录")
    return user


@router.get("/me", response_model=UserResponse)
def me(user: AuthenticatedUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=204)
def logout(credentials: Credentials) -> Response:
    if credentials is None:
        return Response(status_code=204)
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        return Response(status_code=204)
    remaining = payload["exp"] - int(time.time())
    if remaining > 0:
        try:
            redis_client.set(f"blacklist:{payload['jti']}", "1", ex=remaining)
        except RedisError as error:
            raise HTTPException(status_code=503, detail="认证服务暂不可用") from error
    return Response(status_code=204)
