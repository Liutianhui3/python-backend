"""对应 NestJS Controller：只负责 HTTP 输入、输出和异常映射。"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from python_backend.db.session import get_session
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
    logout_user,
    register_user,
)

router = APIRouter(prefix="/users", tags=["users"])


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


def session_token(request: Request) -> str:
    match = re.fullmatch(r"Bearer ([a-f0-9]{64})", request.headers.get("authorization", ""), re.I)
    return match[1] if match else ""


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, session: SessionDependency) -> LoginResponse:
    try:
        user, token = login_user(session, request.username, request.password.get_secret_value())
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail="用户名或密码不正确") from error
    return LoginResponse(user=UserResponse.model_validate(user), token=token)


@router.get("/me", response_model=UserResponse)
def me(request: Request, session: SessionDependency) -> UserResponse:
    user = current_user(session, session_token(request))
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDependency) -> Response:
    logout_user(session, session_token(request))
    return Response(status_code=204)
