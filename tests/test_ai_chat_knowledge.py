"""Isolated migration coverage; SDK calls never leave the process."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from python_backend.core.config import settings
from python_backend.db.base import Base
from python_backend.db.session import get_session
from python_backend.main import app
from python_backend.modules.ai.errors import AIError
from python_backend.modules.chat import service
from python_backend.modules.chat.models import Conversation, Message
from python_backend.modules.chat.schemas import MessageInput
from python_backend.modules.knowledge import embedding
from python_backend.modules.users.models import User
from python_backend.modules.users.router import authenticated_user


@pytest.fixture
def context(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="alice", name="Alice", email="alice@example.com", password_hash="x")
        session.add(user)
        session.commit()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[authenticated_user] = lambda: user
        monkeypatch.setattr(settings, "embedding_model", "test-embedding")
        monkeypatch.setattr(settings, "embedding_dimensions", 3)
        with TestClient(app) as client:
            yield client, session, user
        app.dependency_overrides.clear()
    engine.dispose()


async def fake_embed(texts):
    return "test-embedding", [[1.0, 0.0, 0.0] for _ in texts]


def test_knowledge_upload_embed_search_and_ownership(context):
    client, session, user = context
    base = client.post("/knowledge-bases", json={"name": "知识库"}).json()
    url = f"/knowledge-bases/{base['id']}"
    result = client.post(
        url + "/documents",
        files={"file": ("test.md", ("你好世界" * 100).encode())},
        data={"chunkSize": "100", "chunkOverlap": "20"},
    )
    assert result.status_code == 200, result.text
    doc = result.json()
    assert doc["chunkCount"] == 5
    doc_url = url + f"/documents/{doc['id']}"
    with patch.object(embedding, "embed", side_effect=fake_embed):
        assert client.post(doc_url + "/embeddings").json()["embeddedChunks"] == 5
        result = client.post(url + "/search", json={"query": "你好"})
        assert result.status_code == 200, result.text
        assert result.json()["items"][0]["score"] == 1
    assert client.get(url + "/documents").json()[0]["embeddedChunks"] == 5
    assert client.get(doc_url + "/chunks").json()["total"] == 5
    app.dependency_overrides[authenticated_user] = lambda: User(id=uuid4())
    assert client.get(url + "/documents").status_code == 404
    app.dependency_overrides[authenticated_user] = lambda: user
    assert client.delete(doc_url).status_code == 200
    assert client.get(url + "/documents").json() == []


def test_sse_completed_and_failed(context):
    client, session, user = context
    conversation = client.post("/conversations", json={}).json()
    url = f"/conversations/{conversation['id']}/messages"

    @asynccontextmanager
    async def opened(*args, **kwargs):
        async def deltas():
            yield {"text": "你好"}
            yield {"finishReason": "stop"}

        yield deltas()

    with patch("python_backend.modules.ai.service.open_stream", opened):
        response = client.post(url + "/stream", json={"content": "你好"})
    assert response.status_code == 200
    assert all(f"event: {name}" in response.text for name in ("start", "delta", "done"))
    messages = client.get(url).json()
    assert [m["status"] for m in messages] == ["completed", "completed"]
    assert messages[-1]["content"] == "你好"

    @asynccontextmanager
    async def failing(*args, **kwargs):
        async def deltas():
            yield {"text": "部分"}
            raise AIError("中断", 502)

        yield deltas()

    with patch("python_backend.modules.ai.service.open_stream", failing):
        response = client.post(url + "/stream", json={"content": "继续"})
    assert "event: error" in response.text
    assert client.get(url).json()[-1]["status"] == "failed"
    assert session.get(Conversation, UUID(conversation["id"])).generation_id is None
    assert client.delete(f"/conversations/{conversation['id']}").status_code == 200
    assert session.scalar(select(Message)) is None


def test_lease_and_validation(context):
    client, session, user = context
    conversation = client.post("/conversations", json={}).json()

    turn = asyncio.run(
        service.prepare(session, user.id, UUID(conversation["id"]), MessageInput(content="开始"))
    )
    with pytest.raises(AIError) as error:
        asyncio.run(
            service.prepare(session, user.id, turn.conversation_id, MessageInput(content="并发"))
        )
    assert error.value.code == 409
    session.rollback()
    service.finish(session, turn, "", "cancelled")
    url = f"/conversations/{conversation['id']}/messages/stream"
    assert client.post(url, json={"content": "", "attachments": []}).status_code == 422
    assert client.post(url, json={"content": "你好", "model": "unlisted"}).status_code == 400
    base = client.post("/knowledge-bases", json={"name": "库"}).json()
    response = client.post(
        f"/knowledge-bases/{base['id']}/documents",
        files={"file": ("t.txt", b"test")},
        data={"chunkSize": "100", "chunkOverlap": "100"},
    )
    assert response.status_code == 422


def test_sdk_stream_and_embedding_contract(monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock, MagicMock

    from python_backend.modules.ai import service as ai
    from python_backend.modules.ai.catalog import ModelDefinition

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __aiter__(self):
            async def values():
                yield NS(
                    choices=[
                        NS(index=0, delta=NS(content="SDK", tool_calls=[]), finish_reason=None)
                    ]
                )
                yield NS(
                    choices=[
                        NS(index=0, delta=NS(content=None, tool_calls=[]), finish_reason="stop")
                    ]
                )

            return values()

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=Stream())
    client.embeddings.create = AsyncMock(
        return_value=NS(data=[NS(index=0, embedding=[1.0, 0.0, 0.0])])
    )
    monkeypatch.setattr(settings, "embedding_model", "test")
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    with (
        patch("python_backend.modules.ai.service.create_client", return_value=client),
        patch("python_backend.modules.knowledge.embedding.create_client", return_value=client),
    ):

        async def run():
            async with ai.open_stream(
                [{"role": "user", "content": "hi"}], ModelDefinition(id="test"), "auto"
            ) as stream:
                assert [item async for item in stream] == [
                    {"text": "SDK"},
                    {"finishReason": "stop"},
                ]
            model, vectors = await embedding.embed(["test"])
            assert model == "test" and vectors == [[1.0, 0.0, 0.0]]

        asyncio.run(run())
    assert client.chat.completions.create.call_args.kwargs["stream"] is True
    assert "reasoning_effort" not in client.chat.completions.create.call_args.kwargs
    client.__aexit__.assert_awaited()


def test_disconnect_preserves_partial_and_releases_lease(context):
    from python_backend.modules.chat.streaming import stream_events

    client, session, user = context
    conversation = client.post("/conversations", json={}).json()

    async def run():
        turn = await service.prepare(
            session, user.id, UUID(conversation["id"]), MessageInput(content="hi")
        )

        async def deltas():
            yield {"text": "partial"}
            await asyncio.sleep(30)

        @asynccontextmanager
        async def manager():
            yield deltas()

        context_manager = manager()
        stream = await context_manager.__aenter__()
        events = stream_events(
            session, turn, stream, context_manager, asyncio.get_running_loop().time() + 60
        )
        assert "event: start" in await anext(events)
        assert "partial" in await anext(events)
        await events.aclose()
        row = session.get(Message, turn.message_id)
        assert row.status == "cancelled" and row.content == "partial"
        assert session.get(Conversation, turn.conversation_id).generation_id is None

    asyncio.run(run())


@pytest.mark.parametrize("base64_image", [False, True])
def test_automatic_image_tool_stream_and_persistence(context, monkeypatch, base64_image):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock, MagicMock

    client, session, user = context
    monkeypatch.setattr(settings, "ai_image_tools_enabled", True)
    monkeypatch.setattr(settings, "ai_image_model", "qwen-image-3.0-pro")
    conversation = client.post("/conversations", json={}).json()

    class ToolStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __aiter__(self):
            async def values():
                for name, arguments, tool_id in [
                    ("generate_", '{"prompt":"', "call_image"),
                    ("image", '窗边晒太阳的猫"}', None),
                ]:
                    tool = NS(index=0, id=tool_id, function=NS(name=name, arguments=arguments))
                    yield NS(
                        choices=[
                            NS(
                                index=0,
                                delta=NS(content=None, tool_calls=[tool]),
                                finish_reason=None,
                            )
                        ]
                    )
                yield NS(
                    choices=[
                        NS(
                            index=0,
                            delta=NS(content=None, tool_calls=[]),
                            finish_reason="tool_calls",
                        )
                    ]
                )

            return values()

    sdk = MagicMock()
    sdk.__aenter__ = AsyncMock(return_value=sdk)
    sdk.__aexit__ = AsyncMock()
    sdk.chat.completions.create = AsyncMock(return_value=ToolStream())
    image_url = "https://images.example.com/cat.png"
    import httpx2 as httpx

    endpoint = "https://images.example.com/api/v1/services/aigc/multimodal-generation/generation"
    monkeypatch.setattr(settings, "ai_image_base_url", endpoint)
    monkeypatch.setattr(settings, "ai_image_api_key", SecretStr("image-key"))
    expected = "data:image/png;base64,aW1hZ2U=" if base64_image else image_url
    transport = MagicMock()
    transport.__aenter__ = AsyncMock(return_value=transport)
    transport.__aexit__ = AsyncMock()
    transport.post = AsyncMock(
        return_value=httpx.Response(
            200,
            request=httpx.Request("POST", endpoint),
            json={"output": {"choices": [{"message": {"content": [{"image": expected}]}}]}},
        )
    )
    with (
        patch("python_backend.modules.ai.service.create_client", return_value=sdk),
        patch("python_backend.modules.ai.images.httpx.AsyncClient", return_value=transport),
    ):
        response = client.post(
            f"/conversations/{conversation['id']}/messages/stream",
            json={"content": "帮我画一只在窗边晒太阳的猫", "model": settings.ai_model},
        )
    assert response.status_code == 200
    assert "event: image_generation" in response.text
    assert "event: done" in response.text and "event: error" not in response.text
    expected = "data:image/png;base64,aW1hZ2U=" if base64_image else image_url
    assert expected in response.text
    saved = client.get(f"/conversations/{conversation['id']}/messages").json()[-1]
    assert saved["status"] == "completed" and expected in saved["content"]
    options = sdk.chat.completions.create.call_args.kwargs
    assert options["model"] == settings.ai_model
    assert options["tool_choice"] == "auto"
    assert "generate_image" in {t["function"]["name"] for t in options["tools"]}
    transport.post.assert_awaited_once_with(
        endpoint,
        headers={"Authorization": "Bearer image-key"},
        json={
            "model": "qwen-image-3.0-pro",
            "input": {"messages": [{"role": "user", "content": [{"text": "窗边晒太阳的猫"}]}]},
            "parameters": {"prompt_extend": True},
        },
    )


def test_invalid_image_tool_does_not_generate(monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock

    from python_backend.modules.ai.service import read_completion

    monkeypatch.setattr(settings, "ai_image_tools_enabled", True)

    async def chunks():
        yield NS(
            choices=[
                NS(
                    index=0,
                    delta=NS(
                        content=None,
                        tool_calls=[
                            NS(
                                index=0,
                                id="bad",
                                function=NS(name="generate_image", arguments='{"prompt":123}'),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ]
        )

    generated = AsyncMock()
    with patch("python_backend.modules.ai.service.generate_image", generated):

        async def consume():
            return [delta async for delta in read_completion(chunks())]

        with pytest.raises(AIError):
            asyncio.run(consume())
    generated.assert_not_awaited()


@pytest.mark.parametrize(
    "status,payload,message",
    [
        (400, {"message": "private provider detail"}, "HTTP 400"),
        (200, {"code": "InvalidParameter", "message": "private provider detail"}, "图片生成失败"),
        (200, {"output": {"choices": []}}, "未返回图片"),
        (200, {"output": None}, "响应格式无效"),
    ],
)
def test_native_image_errors(monkeypatch, status, payload, message):
    import httpx2 as httpx

    from python_backend.modules.ai.images import generate_image

    endpoint = "https://images.example.com/generation"
    monkeypatch.setattr(settings, "ai_image_base_url", endpoint)
    monkeypatch.setattr(settings, "ai_image_api_key", SecretStr("image-key"))
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    client = httpx.AsyncClient(transport=transport)
    with patch("python_backend.modules.ai.images.httpx.AsyncClient", return_value=client):
        with pytest.raises(AIError, match=message):
            asyncio.run(generate_image("画猫"))


@pytest.mark.parametrize("kind", ["excel", "word"])
def test_generated_file_stream_history_download(context, monkeypatch, kind):
    import json
    from io import BytesIO
    from types import SimpleNamespace as NS

    from python_backend.modules.ai.files import generate_file
    from python_backend.modules.ai.service import read_completion

    client, session, user = context
    conversation = client.post("/conversations", json={}).json()
    body = (
        {
            "filename": "测试.xlsx",
            "sheets": [{"name": "资料", "rows": [["名称", "值"], ["测试", "=1+1"]]}],
        }
        if kind == "excel"
        else {
            "filename": "测试.docx",
            "title": "测试文档",
            "blocks": [{"type": "paragraph", "text": "你好世界"}],
        }
    )

    async def chunks():
        yield NS(
            choices=[
                NS(
                    index=0,
                    delta=NS(
                        content=None,
                        tool_calls=[
                            NS(
                                index=0,
                                id="file-call",
                                function=NS(name=f"generate_{kind}", arguments=json.dumps(body)),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ]
        )

    @asynccontextmanager
    async def open_file(*args, **kwargs):
        yield read_completion(chunks())

    monkeypatch.setattr("python_backend.modules.chat.streaming.ai.open_stream", open_file)
    result = client.post(
        f"/conversations/{conversation['id']}/messages/stream", json={"content": "生成文件"}
    )
    assert "event: file_generation" in result.text
    assert "event: file\n" in result.text and "event: done" in result.text
    history = client.get(f"/conversations/{conversation['id']}/messages").json()
    file = history[-1]["files"][0]
    downloaded = client.get(file["downloadUrl"])
    assert downloaded.status_code == 200
    assert "filename*=UTF-8" in downloaded.headers["content-disposition"]
    assert len(downloaded.content) == file["size"]
    if kind == "excel":
        from openpyxl import load_workbook

        book = load_workbook(BytesIO(downloaded.content))
        assert book["资料"]["B2"].value == "=1+1"
        assert book["资料"]["B2"].data_type == "s"
    else:
        from docx import Document

        doc = Document(BytesIO(downloaded.content))
        assert [p.text for p in doc.paragraphs] == ["测试文档", "你好世界"]
    other = client.post("/conversations", json={}).json()
    assert (
        client.get(file["downloadUrl"].replace(conversation["id"], other["id"])).status_code == 404
    )
    app.dependency_overrides[authenticated_user] = lambda: NS(id=uuid4())
    assert client.get(file["downloadUrl"]).status_code == 404
    app.dependency_overrides[authenticated_user] = lambda: user
    assert client.delete(f"/conversations/{conversation['id']}").status_code == 200
    assert client.get(file["downloadUrl"]).status_code == 404
    with pytest.raises(AIError):
        generate_file("generate_excel", {"filename": "x.xlsx", "sheets": []})


@pytest.mark.parametrize("fail", [False, True])
def test_reasoning_stream_persistence_and_context(context, monkeypatch, fail):
    from types import SimpleNamespace as NS

    from python_backend.modules.ai.messages import build_messages
    from python_backend.modules.ai.service import read_completion

    client, session, user = context
    conversation = client.post("/conversations", json={}).json()

    async def chunks():
        for text in ["先整理", "再分析"]:
            yield NS(
                choices=[
                    NS(
                        index=0,
                        delta=NS(reasoning_content=text, content=None, tool_calls=[]),
                        finish_reason=None,
                    )
                ]
            )
        if fail:
            raise AIError("测试中断", 502)
        yield NS(
            choices=[NS(index=0, delta=NS(content="最终回答", tool_calls=[]), finish_reason="stop")]
        )

    @asynccontextmanager
    async def open_reasoning(*args, **kwargs):
        yield read_completion(chunks())

    monkeypatch.setattr("python_backend.modules.chat.streaming.ai.open_stream", open_reasoning)
    response = client.post(
        f"/conversations/{conversation['id']}/messages/stream", json={"content": "问题"}
    )
    assert "event: reasoning" in response.text
    history = client.get(f"/conversations/{conversation['id']}/messages").json()
    reply = history[-1]
    assert reply["reasoningContent"] == "先整理再分析"
    assert reply["content"] == ("" if fail else "最终回答")
    assert reply["status"] == ("failed" if fail else "completed")
    messages = build_messages([{"user": "问题", "assistant": reply["content"]}], "继续")
    assert "先整理" not in str(messages)


def test_platform_tool_ownership_validation_and_empty(context):
    from python_backend.modules.ai.platform import query_platform
    from python_backend.modules.articles.models import Article
    from python_backend.modules.roles.models import Role, UserRole

    client, session, user = context
    other = User(username="other", name="Other", email="other@example.com")
    session.add(other)
    session.flush()
    session.add_all(
        [
            Article(user_id=user.id, title="我的草稿", status="draft"),
            Article(user_id=user.id, title="我的文章", status="published"),
            Article(user_id=other.id, title="他人秘密"),
            Role(id=987, name="writer", name_cn="作者"),
        ]
    )
    session.flush()
    session.add(UserRole(user_id=user.id, role_id=987))
    session.commit()
    result = query_platform(session, user.id, {"scope": "all"})
    assert result["profile"] == {"username": "alice", "displayName": "Alice"}
    assert query_platform(session, user.id, {"scope": "profile"}) == {"profile": result["profile"]}
    assert result["articles"]["total"] == 2
    assert {r["title"] for r in result["articles"]["items"]} == {"我的草稿", "我的文章"}
    assert result["roles"] == [{"id": 987, "name": "writer", "label": "作者"}]
    assert query_platform(session, other.id, {"scope": "roles"}) == {"roles": []}
    assert query_platform(session, uuid4(), {"scope": "articles"})["articles"]["total"] == 0
    for arguments in [
        {"scope": "all", "user_id": str(other.id)},
        {"scope": "bad"},
        {"scope": "articles", "offset": -1},
    ]:
        with pytest.raises(AIError):
            query_platform(session, user.id, arguments)


@pytest.mark.parametrize("mode", ["answer", "excel", "limit"])
def test_platform_tool_sdk_roundtrip(context, mode):
    import json
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock, MagicMock

    client, session, user = context

    class Stream:
        def __init__(self, delta, finish):
            self.delta, self.finish = delta, finish

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __aiter__(self):
            async def chunks():
                yield NS(choices=[NS(index=0, delta=self.delta, finish_reason=self.finish)])

            return chunks()

    sdk = MagicMock()
    sdk.__aenter__ = AsyncMock(return_value=sdk)
    sdk.__aexit__ = AsyncMock()
    sdk.chat.completions.create = AsyncMock(
        side_effect=[
            Stream(
                NS(
                    content=None,
                    tool_calls=[
                        NS(
                            index=0,
                            id="platform-call",
                            function=NS(name="get_my_platform_info", arguments='{"scope":"all"}'),
                        )
                    ],
                ),
                "tool_calls",
            ),
            Stream(NS(content="你还没有文章，也尚未分配角色。", tool_calls=[]), "stop"),
        ]
    )
    if mode == "excel":
        sdk.chat.completions.create.side_effect = [
            sdk.chat.completions.create.side_effect.__next__(),
            Stream(
                NS(
                    content=None,
                    tool_calls=[
                        NS(
                            index=0,
                            id="excel-call",
                            function=NS(
                                name="generate_excel",
                                arguments=json.dumps(
                                    {
                                        "filename": "我的资料.xlsx",
                                        "sheets": [
                                            {
                                                "name": "账户",
                                                "rows": [
                                                    ["用户名", "文章数", "角色"],
                                                    ["alice", 0, "未分配"],
                                                ],
                                            }
                                        ],
                                    }
                                ),
                            ),
                        )
                    ],
                ),
                "tool_calls",
            ),
        ]
    elif mode == "limit":
        sdk.chat.completions.create.side_effect = [
            Stream(
                NS(
                    content=None,
                    tool_calls=[
                        NS(
                            index=0,
                            id=f"query-{i}",
                            function=NS(name="get_my_platform_info", arguments='{"scope":"all"}'),
                        )
                    ],
                ),
                "tool_calls",
            )
            for i in range(5)
        ]
    conversation = client.post("/conversations", json={}).json()
    with patch("python_backend.modules.ai.service.create_client", return_value=sdk):
        response = client.post(
            f"/conversations/{conversation['id']}/messages/stream",
            json={"content": "我的文章和角色是什么？"},
        )
    if mode == "limit":
        assert "event: error" in response.text and "次数过多" in response.text
        assert sdk.chat.completions.create.await_count == 5
        return
    assert "event: done" in response.text and "event: error" not in response.text
    calls = sdk.chat.completions.create.call_args_list
    assert len(calls) == 2
    assert any(t["function"]["name"] == "get_my_platform_info" for t in calls[0].kwargs["tools"])
    followup = calls[1].kwargs["messages"]
    assert followup[-1]["role"] == "tool" and followup[-1]["tool_call_id"] == "platform-call"
    data = json.loads(followup[-1]["content"])
    assert data["articles"]["total"] == 0 and data["roles"] == []
    assert "password" not in followup[-1]["content"]
    assert calls[1].kwargs["tool_choice"] == "auto"
    if mode == "excel":
        from io import BytesIO

        from openpyxl import load_workbook

        saved = client.get(f"/conversations/{conversation['id']}/messages").json()[-1]
        file = saved["files"][0]
        download = client.get(file["downloadUrl"])
        assert download.status_code == 200
        book = load_workbook(BytesIO(download.content))
        assert list(book["账户"].values)[1] == ("alice", 0, "未分配")
        return
    assert (
        client.get(f"/conversations/{conversation['id']}/messages").json()[-1]["content"]
        == "你还没有文章，也尚未分配角色。"
    )
