import time
from uuid import uuid4

import jwt

from python_backend.core.config import settings


def create_access_token(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "jti": uuid4().hex,
            "iat": now,
            "exp": now + settings.jwt_expire_seconds,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        options={"require": ["sub", "jti", "iat", "exp"]},
    )
    if not isinstance(payload["jti"], str) or not payload["jti"]:
        raise jwt.InvalidTokenError("Invalid jti")
    return payload
