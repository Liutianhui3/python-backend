"""会话归属、分页、生成租约与消息事务，不依赖 HTTP。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update

from python_backend.core.config import settings
from python_backend.modules.ai import catalog
from python_backend.modules.ai.errors import AIError
from python_backend.modules.ai.messages import build_messages
from python_backend.modules.chat.models import Conversation, GeneratedFile, Message
from python_backend.modules.knowledge.rag import retrieve


@dataclass
class Turn:
    conversation_id: UUID
    generation_id: UUID
    user_message_id: UUID
    message_id: UUID
    messages: list
    model: catalog.ModelDefinition
    effort: str


def owned(session, user_id, conversation_id, lock=False):
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    conversation = session.scalar(stmt.with_for_update() if lock else stmt)
    if conversation is None:
        raise AIError("会话不存在", 404)
    return conversation


def conversation_data(c):
    return {"id": c.id, "title": c.title, "createdAt": c.created_at, "updatedAt": c.updated_at}


def create(session, user_id, body):
    c = Conversation(user_id=user_id, title=body.title)
    session.add(c)
    session.commit()
    return conversation_data(c)


def list_conversations(session, user_id):
    rows = session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(100)
    )
    return [conversation_data(c) for c in rows]


def remove(session, user_id, conversation_id):
    c = owned(session, user_id, conversation_id, lock=True)
    session.execute(
        delete(GeneratedFile).where(
            GeneratedFile.message_id.in_(select(Message.id).where(Message.conversation_id == c.id))
        )
    )
    session.execute(delete(Message).where(Message.conversation_id == c.id))
    session.delete(c)
    session.commit()
    return {"id": conversation_id}


def message_data(m):
    return {
        "id": m.id,
        "turnId": m.turn_id,
        "sequence": str(m.sequence),
        "role": m.role,
        "content": m.content,
        "reasoningContent": m.reasoning_content,
        "attachments": m.attachments,
        "status": m.status,
        "model": m.model,
        "reasoningEffort": m.reasoning_effort,
        "createdAt": m.created_at,
    }


def history(session, user_id, conversation_id, before, limit):
    owned(session, user_id, conversation_id)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before is not None:
        stmt = stmt.where(Message.sequence < before)
    rows = list(session.scalars(stmt.order_by(Message.sequence.desc()).limit(limit)))
    from python_backend.modules.chat.files import file_data

    files = list(
        session.scalars(
            select(GeneratedFile).where(GeneratedFile.message_id.in_([m.id for m in rows]))
        )
    )
    return [
        dict(
            message_data(m),
            files=[file_data(f, conversation_id) for f in files if f.message_id == m.id],
        )
        for m in reversed(rows)
    ]


async def prepare(session, user_id, conversation_id, body):
    model, effort = catalog.resolve(body.model, body.reasoningEffort)
    attachments = [a.model_dump(exclude_none=True) for a in body.attachments]
    build_messages([], body.content, attachments=attachments)
    owned(session, user_id, conversation_id)
    sources = await retrieve(session, user_id, body.content)
    session.rollback()
    c = owned(session, user_id, conversation_id, lock=True)
    now = datetime.now(UTC)
    expires = c.generation_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if c.generation_id and expires and expires > now:
        raise AIError("该会话正在生成回复，请稍后再试", 409)
    session.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id, Message.status == "generating")
        .values(status="failed")
    )
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.status == "completed")
            .order_by(Message.sequence.desc())
            .limit(100)
        )
    )
    assistants = {m.turn_id: m for m in rows if m.role == "assistant"}
    pairs = [
        {
            "user": m.content,
            "assistant": assistants[m.turn_id].content,
            "attachments": m.attachments,
        }
        for m in reversed(rows)
        if m.role == "user" and m.turn_id in assistants
    ]
    messages = build_messages(pairs, body.content, sources, attachments)
    generation_id, user_message_id, message_id = uuid4(), uuid4(), uuid4()
    seq = session.scalar(
        select(func.coalesce(func.max(Message.sequence), 0)).where(
            Message.conversation_id == conversation_id
        )
    )
    c.generation_id = generation_id
    c.generation_expires_at = now + timedelta(milliseconds=settings.ai_timeout_ms + 30000)
    c.updated_at = now
    session.add_all(
        [
            Message(
                id=user_message_id,
                conversation_id=c.id,
                turn_id=generation_id,
                sequence=seq + 1,
                role="user",
                content=body.content,
                attachments=attachments,
                status="completed",
            ),
            Message(
                id=message_id,
                conversation_id=c.id,
                turn_id=generation_id,
                sequence=seq + 2,
                role="assistant",
                content="",
                status="generating",
                model=model.id,
                reasoning_effort=effort,
            ),
        ]
    )
    session.commit()
    return Turn(
        conversation_id, generation_id, user_message_id, message_id, messages, model, effort
    )


def finish(session, turn, content, status, reasoning=""):
    result = session.execute(
        update(Conversation)
        .where(
            Conversation.id == turn.conversation_id,
            Conversation.generation_id == turn.generation_id,
        )
        .values(generation_id=None, generation_expires_at=None, updated_at=datetime.now(UTC))
    )
    if result.rowcount != 1:
        session.rollback()
        raise AIError("回复生成租约已失效", 409)
    result = session.execute(
        update(Message)
        .where(Message.id == turn.message_id, Message.status == "generating")
        .values(content=content, status=status, reasoning_content=reasoning)
    )
    if result.rowcount != 1:
        session.rollback()
        raise AIError("回复状态已失效", 409)
    session.commit()


def image_for_download(session, user_id, conversation_id, message_id, url):
    owned(session, user_id, conversation_id)
    m = session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.id == message_id,
            Message.role == "assistant",
        )
    )
    if m is None or not any(pattern in m.content for pattern in (f"](<{url}>)", f"]({url})")):
        raise AIError("图片不存在或无权下载", 404)
    return url
