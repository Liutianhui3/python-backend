"""注册业务：负责密码和事务，不依赖 HTTP 状态码。"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from python_backend.modules.users.models import User, UserSession
from python_backend.modules.users.schemas import RegisterRequest


class UserAlreadyExistsError(Exception):
    """用户名或邮箱违反数据库唯一约束。"""


def hash_password(password: str) -> str:
    # 与 my-blob-api 的 Node scryptSync 默认参数、盐的编码方式保持一致。
    # 每个密码生成随机盐；保存 salt:hash，绝不保存明文密码。
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return f"{salt}:{digest.hex()}"


def register_user(session: Session, request: RegisterRequest) -> User:
    user = User(
        username=request.username,
        name=request.username,  # 和旧项目一样，注册时昵称默认等于用户名。
        email=str(request.email),
        password_hash=hash_password(request.password.get_secret_value()),
    )
    session.add(user)
    try:
        # 唯一索引是最终防线：先查询再插入仍可能出现并发竞争。
        session.commit()
    except IntegrityError as error:
        session.rollback()  # 失败的事务必须回滚，会话才能继续使用。
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise UserAlreadyExistsError from error
        raise  # 非唯一约束错误不应伪装成用户名重复。
    session.refresh(user)  # 读取数据库生成的时间和资料默认值。
    return user


class InvalidCredentialsError(Exception):
    """用户名或密码不正确。"""


def verify_password(password: str, stored: str | None) -> bool:
    # 缺失或损坏的哈希也执行 scrypt，避免不存在的账号直接快速返回。
    salt, expected, valid = "0" * 32, bytes(64), False
    if stored:
        try:
            salt_value, digest = stored.split(":")
            decoded = bytes.fromhex(digest)
            if len(salt_value) == 32 and len(decoded) == 64:
                salt, expected, valid = salt_value, decoded, True
        except ValueError:
            pass
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)
    return secrets.compare_digest(actual, expected) and valid


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login_user(session: Session, username: str, password: str) -> tuple[User, str]:
    user = session.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if not verify_password(password, user.password_hash if user else None) or user is None:
        raise InvalidCredentialsError
    now = datetime.now(UTC)
    token = secrets.token_hex(32)
    session.execute(delete(UserSession).where(UserSession.expires_at <= now))
    session.add(
        UserSession(
            token_hash=token_hash(token), user_id=user.id, expires_at=now + timedelta(days=1)
        )
    )
    session.commit()
    return user, token


def current_user(session: Session, token: str) -> User | None:
    return session.scalar(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == token_hash(token),
            UserSession.expires_at > datetime.now(UTC),
        )
    )


def logout_user(session: Session, token: str) -> None:
    session.execute(delete(UserSession).where(UserSession.token_hash == token_hash(token)))
    session.commit()
