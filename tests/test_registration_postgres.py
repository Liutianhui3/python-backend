"""可选真实数据库测试：TEST_POSTGRES=1 uv run pytest。

用外层事务包住请求中的 commit，测试结束统一回滚，不留下测试用户。
"""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from python_backend.db.engine import engine
from python_backend.db.session import get_session
from python_backend.main import app


@pytest.mark.skipif(os.environ.get("TEST_POSTGRES") != "1", reason="需显式启用 PostgreSQL 测试")
def test_postgres_unique_constraints_and_rollback():
    suffix = uuid4().hex[:16]
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            app.dependency_overrides[get_session] = lambda: session
            try:
                with TestClient(app) as client:
                    payload = {
                        "username": f"user_{suffix}",
                        "email": f"{suffix}@example.com",
                        "password": "password123",
                    }
                    assert client.post("/users/register", json=payload).status_code == 201
                    # 分别触发两个大小写不敏感的唯一索引。
                    for changes in (
                        {
                            "username": payload["username"].upper(),
                            "email": f"new{suffix}@example.com",
                        },
                        {"username": f"other_{suffix}", "email": payload["email"].upper()},
                    ):
                        response = client.post("/users/register", json=payload | changes)
                        assert response.status_code == 409
                    # 前一次事务失败后仍能成功注册，说明 rollback 生效。
                    assert (
                        client.post(
                            "/users/register",
                            json=payload
                            | {
                                "username": f"ok_{suffix}",
                                "email": f"ok{suffix}@example.com",
                            },
                        ).status_code
                        == 201
                    )
            finally:
                app.dependency_overrides.clear()
                transaction.rollback()
