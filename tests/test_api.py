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
from python_backend.modules.roles.models import Role, UserRole
from python_backend.modules.users.models import User
from python_backend.modules.users.service import UserAlreadyExistsError


@pytest.fixture
def client_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Role(id=1, name="admin", name_cn="管理员"),
                Role(id=2, name="common", name_cn="普通用户"),
            ]
        )
        session.commit()
        app.dependency_overrides[get_session] = lambda: session
        try:
            with patch("python_backend.modules.users.router.redis_client.set"):
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
    assert "isAdmin" not in data
    assert data["roles"] == [{"id": 2, "name": "common", "nameCn": "普通用户"}]
    assert data["skills"] == data["workExperiences"] == []
    assert data["avatar"] == data["about"] == ""
    assert data["id"] and data["createdAt"] and data["updatedAt"]
    assert not any("password" in key.lower() for key in data)
    user = session.scalar(select(User))
    assert session.get(UserRole, (user.id, 2)) is not None
    assert session.get(UserRole, (user.id, 1)) is None
    session.add(UserRole(user_id=user.id, role_id=1))
    session.commit()
    role_ids = session.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id))
    assert set(role_ids) == {1, 2}
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
    client, session = client_session
    payload = {"username": "alice", "email": "alice@example.com", "password": "password123"}
    user = client.post("/users/register", json=payload).json()
    assert client.get("/users/me").status_code == 401
    response = client.post("/users/login", json={"username": " ALICE ", "password": "password123"})
    assert response.status_code == 200
    data = response.json()
    assert data["user"] == user
    token = data["token"]
    assert len(token.split(".")) == 3
    headers = {"Authorization": f"Bearer {token}"}
    with patch("python_backend.modules.users.router.redis_client.exists", return_value=0):
        assert client.get("/users/me", headers=headers).json() == user
    with patch("python_backend.modules.users.router.redis_client.set") as redis_set:
        assert client.post("/users/logout", headers=headers).content == b""
        redis_set.assert_called_once()
        assert redis_set.call_args.args[0].startswith("blacklist:")
        assert redis_set.call_args.kwargs["ex"] > 0
    with patch("python_backend.modules.users.router.redis_client.exists", return_value=1):
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


def test_expired_token(client_session):
    import jwt

    from python_backend.core.config import settings

    client, session = client_session
    client.post(
        "/users/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    user = session.scalar(select(User))
    token = jwt.encode(
        {"sub": str(user.id), "jti": "expired", "iat": 1, "exp": 2},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    assert client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


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


@pytest.fixture
def role_accounts(client_session):
    from python_backend.core.security import create_access_token
    from python_backend.modules.users.service import hash_password

    client, session = client_session
    session.add(Role(id=3, name="editor", name_cn="文章编辑"))
    accounts = {}
    for label, role_id in [("admin", 1), ("reader", 2), ("editor", 3)]:
        user = User(
            username=label,
            name=label,
            email=f"{label}@example.com",
            password_hash=hash_password("password123"),
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role_id))
        accounts[label] = (
            user.id,
            {"Authorization": f"Bearer {create_access_token(str(user.id))}"},
        )
    session.commit()
    with patch("python_backend.modules.users.router.redis_client.exists", return_value=0):
        yield client, session, accounts


def test_role_assignment_and_live_permissions(role_accounts):
    client, session, accounts = role_accounts
    admin_id, admin = accounts["admin"]
    reader_id, reader = accounts["reader"]
    _, editor = accounts["editor"]
    assert client.get("/admin/users", headers=reader).status_code == 403
    assert client.get("/admin/users", headers=editor).status_code == 403
    assert client.get("/admin/users").status_code == 401
    assert len(client.get("/admin/roles", headers=admin).json()) == 3
    response = client.get("/admin/users", params={"q": "reader"}, headers=admin)
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["roles"][0]["id"] == 2
    response = client.patch(
        f"/admin/users/{reader_id}/role", headers=admin, json={"roleIds": [2, 3, 3]}
    )
    assert response.status_code == 200
    assert [r["id"] for r in response.json()["roles"]] == [2, 3]
    assert (
        client.patch(
            f"/admin/users/{reader_id}/role", headers=admin, json={"roleIds": []}
        ).status_code
        == 422
    )
    assert session.get(UserRole, (reader_id, 2)) is not None
    assert client.get("/articles/manage", headers=reader).status_code == 200
    assert (
        client.patch(
            f"/admin/users/{reader_id}/role", headers=editor, json={"roleIds": [1]}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/admin/users/{reader_id}/role", headers=admin, json={"roleIds": [999]}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/admin/users/{admin_id}/role", headers=admin, json={"roleIds": [2]}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/admin/users/{reader_id}/role", headers=admin, json={"roleIds": [2]}
        ).status_code
        == 200
    )
    assert client.get("/articles/manage", headers=reader).status_code == 403


def test_editor_article_crud_and_visibility(role_accounts):
    client, _, accounts = role_accounts
    _, reader = accounts["reader"]
    _, editor = accounts["editor"]
    body = {"title": "文章", "content": "<p>正文</p><script>alert(1)</script>", "status": "draft"}
    assert client.post("/articles", json=body, headers=reader).status_code == 403
    response = client.post("/articles", json=body, headers=editor)
    assert response.status_code == 200
    article = response.json()
    assert "<script" not in article["content"]
    assert client.get(f"/articles/{article['id']}").status_code == 404
    assert client.get("/articles").json()["total"] == 0
    assert client.get("/articles/manage", headers=editor).json()["total"] == 1
    response = client.patch(
        f"/articles/{article['id']}",
        headers=editor,
        json={**body, "status": "published", "version": 1},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert client.get("/articles").json()["total"] == 1
    assert (
        client.patch(
            f"/articles/{article['id']}", headers=editor, json={**body, "version": 1}
        ).status_code
        == 409
    )
    assert client.delete(f"/articles/{article['id']}", headers=reader).status_code == 403
    assert client.delete(f"/articles/{article['id']}", headers=editor).status_code == 204


@pytest.mark.parametrize("status", ["draft", "published"])
def test_article_owner_isolation(role_accounts, status):
    client, session, accounts = role_accounts
    admin_id, admin = accounts["admin"]
    other_id, other_editor = accounts["reader"]
    _, editor = accounts["editor"]
    session.add_all([UserRole(user_id=other_id, role_id=3), UserRole(user_id=admin_id, role_id=3)])
    session.commit()
    session.expire_all()
    body = {"title": "隔离文章", "content": "<p>正文</p>", "status": status}
    own = client.post("/articles", json=body, headers=editor).json()
    other = client.post("/articles", json=body, headers=other_editor).json()
    admin_article = client.post("/articles", json=body, headers=admin).json()

    for headers, expected in [(editor, own), (other_editor, other)]:
        response = client.get(
            "/articles/manage",
            headers=headers,
            params={"q": "隔离", "status": status, "limit": 1},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert [a["id"] for a in response.json()["items"]] == [expected["id"]]
        assert client.get(f"/articles/manage/{expected['id']}", headers=headers).status_code == 200

    for article in [other, admin_article]:
        article_id = article["id"]
        assert client.get(f"/articles/manage/{article_id}", headers=editor).status_code == 404
        assert (
            client.patch(
                f"/articles/{article_id}",
                headers=editor,
                json={**body, "title": "越权修改", "version": 1},
            ).status_code
            == 404
        )
        assert client.delete(f"/articles/{article_id}", headers=editor).status_code == 404
        detail = client.get(f"/articles/manage/{article_id}", headers=admin)
        assert detail.status_code == 200
        assert detail.json()["title"] == body["title"]
        assert detail.json()["version"] == 1

    assert client.get("/articles/manage", headers=admin).json()["total"] == 3
    assert client.get("/articles").json()["total"] == (3 if status == "published" else 0)
    assert (
        client.patch(
            f"/articles/{other['id']}",
            headers=admin,
            json={**body, "title": "管理员修改", "version": 1},
        ).status_code
        == 200
    )
    assert client.delete(f"/articles/{other['id']}", headers=admin).status_code == 204
