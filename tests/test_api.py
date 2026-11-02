"""SQLite 隔离业务测试，不向开发数据库写入测试用户。"""

import hashlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from python_backend.db.base import Base
from python_backend.db.session import get_session
from python_backend.main import app
from python_backend.modules.users.models import User
from python_backend.modules.users.service import UserAlreadyExistsError


@pytest.fixture
def client_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        app.dependency_overrides[get_session] = lambda: session
        try:
            with TestClient(app) as client:
                yield client, session
        finally:
            app.dependency_overrides.clear()
    engine.dispose()


def test_register(client_session):
    client, session = client_session
    response = client.post(
        "/users/register",
        json={
            "username": " Alice ",
            "email": " Alice@Example.com ",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == data["name"] == "Alice"
    assert data["email"] == "alice@example.com"
    assert data["isAdmin"] is False
    assert data["skills"] == data["workExperiences"] == []
    assert data["avatar"] == data["about"] == ""
    assert data["id"] and data["createdAt"] and data["updatedAt"]
    assert not any("password" in key.lower() for key in data)
    user = session.scalar(select(User))
    salt, digest = user.password_hash.split(":")
    assert (
        digest
        == hashlib.scrypt(b"password123", salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "ab"},
        {"email": "bad"},
        {"password": "abcdefgh"},
        {"password": "12345678"},
        {"isAdmin": True},
        {"password": "short1"},
    ],
)
def test_invalid_registration(client_session, changes):
    client, session = client_session
    payload = {"username": "alice", "email": "alice@example.com", "password": "password123"}
    assert client.post("/users/register", json=payload | changes).status_code == 422
    assert session.scalar(select(User)) is None


def test_conflict_response(client_session):
    client, _ = client_session
    with patch(
        "python_backend.modules.users.router.register_user", side_effect=UserAlreadyExistsError
    ):
        response = client.post(
            "/users/register",
            json={
                "username": "alice",
                "email": "alice@example.com",
                "password": "password123",
            },
        )
    assert response.status_code == 409
    assert response.json() == {"code": 409, "message": "用户名或邮箱已被使用"}


@pytest.mark.parametrize(
    "method,path,code,message",
    [
        ("get", "/missing", 404, "接口不存在"),
        ("get", "/users/register", 405, "请求方法不支持"),
    ],
)
def test_framework_error_format(client_session, method, path, code, message):
    client, _ = client_session
    response = getattr(client, method)(path)
    assert response.status_code == code
    assert response.json() == {"code": code, "message": message}
    if code == 405:
        assert "POST" in response.headers["allow"]


def test_validation_error_format(client_session):
    client, _ = client_session
    response = client.post(
        "/users/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "private",
        },
    )
    assert response.status_code == 422
    assert response.json() == {
        "code": 422,
        "message": "密码需为 8–128 字符，且包含英文字母和数字",
    }
    assert "private" not in response.text
    response = client.post(
        "/users/register", content="{", headers={"Content-Type": "application/json"}
    )
    assert response.json() == {"code": 422, "message": "请求体不是有效的 JSON"}


def test_unexpected_error_format(client_session):
    # TestClient 默认重新抛出服务端异常，关闭后才能断言实际发给浏览器的 500。
    with TestClient(app, raise_server_exceptions=False) as client:
        with patch(
            "python_backend.modules.users.router.register_user", side_effect=RuntimeError("secret")
        ):
            response = client.post(
                "/users/register",
                json={
                    "username": "alice",
                    "email": "alice@example.com",
                    "password": "password123",
                },
            )
    assert response.status_code == 500
    assert response.json() == {"code": 500, "message": "服务器内部错误，请稍后重试"}


def test_login_me_logout(client_session):
    from python_backend.modules.users.models import UserSession
    from python_backend.modules.users.service import token_hash

    client, session = client_session
    payload = {"username": "alice", "email": "alice@example.com", "password": "password123"}
    user = client.post("/users/register", json=payload).json()
    assert client.get("/users/me").status_code == 401
    response = client.post("/users/login", json={"username": " ALICE ", "password": "password123"})
    assert response.status_code == 200
    data = response.json()
    assert data["user"] == user
    token = data["token"]
    assert len(token) == 64
    stored = session.scalar(select(UserSession))
    assert stored.token_hash == token_hash(token) != token
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/users/me", headers=headers).json() == user
    assert client.post("/users/logout", headers=headers).content == b""
    assert client.get("/users/me", headers=headers).status_code == 401
    assert client.post("/users/logout", headers=headers).status_code == 204
    assert client.post("/users/logout").status_code == 204


@pytest.mark.parametrize("stored", [None, "broken", "salt:ff"])
def test_invalid_password_hash(client_session, stored):
    client, session = client_session
    client.post(
        "/users/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    user = session.scalar(select(User))
    user.password_hash = stored
    session.commit()
    response = client.post("/users/login", json={"username": "alice", "password": "password123"})
    assert response.status_code == 401
    assert response.json() == {"code": 401, "message": "用户名或密码不正确"}


@pytest.mark.parametrize("username,password", [("alice", "wrong"), ("unknown", "password123")])
def test_bad_credentials(client_session, username, password):
    client, _ = client_session
    client.post(
        "/users/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    response = client.post("/users/login", json={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json()["message"] == "用户名或密码不正确"


def test_expired_session(client_session):
    from datetime import UTC, datetime, timedelta

    from python_backend.modules.users.models import UserSession

    client, session = client_session
    client.post(
        "/users/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    credentials = {"username": "alice", "password": "password123"}
    token = client.post("/users/login", json=credentials).json()["token"]
    stored = session.scalar(select(UserSession))
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.post("/users/login", json=credentials).status_code == 200
    assert len(session.scalars(select(UserSession)).all()) == 1


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer bad", "Bearer " + "g" * 64])
def test_invalid_token(client_session, authorization):
    client, _ = client_session
    response = client.get("/users/me", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json() == {"code": 401, "message": "请先登录"}


@pytest.mark.parametrize(
    "changes", [{"password": ""}, {"password": "x" * 129}, {"email": "a@b.com"}]
)
def test_login_validation(client_session, changes):
    client, _ = client_session
    response = client.post("/users/login", json={"username": "alice", "password": "a1"} | changes)
    assert response.status_code == 422
