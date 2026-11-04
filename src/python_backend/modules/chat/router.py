"""会话 HTTP 接口；业务、SDK 和 SSE 实现在独立文件。"""

import asyncio
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from python_backend.modules.ai.catalog import models as model_catalog
from python_backend.modules.ai.errors import AIError
from python_backend.modules.chat import service
from python_backend.modules.chat.documents import extract_document
from python_backend.modules.chat.files import download
from python_backend.modules.chat.image_download import download_image
from python_backend.modules.chat.schemas import ConversationInput, ImageDownloadInput, MessageInput
from python_backend.modules.chat.streaming import prepare_stream
from python_backend.modules.users.router import AuthenticatedUser, SessionDependency

router = APIRouter(prefix="/conversations", tags=["chat"])


@router.post("")
def create(body: ConversationInput, session: SessionDependency, user: AuthenticatedUser):
    return service.create(session, user.id, body)


@router.get("")
def list_conversations(session: SessionDependency, user: AuthenticatedUser):
    return service.list_conversations(session, user.id)


@router.get("/models")
def models(user: AuthenticatedUser):
    return model_catalog()


@router.post("/attachments/extract")
async def extract(user: AuthenticatedUser, file: Annotated[UploadFile, File()]):
    data = await file.read(10 * 1024 * 1024 + 1)
    return await run_in_threadpool(extract_document, file.filename or "", data)


@router.delete("/{conversation_id}")
def remove(conversation_id: UUID, session: SessionDependency, user: AuthenticatedUser):
    return service.remove(session, user.id, conversation_id)


@router.get("/{conversation_id}/messages")
def history(
    conversation_id: UUID,
    session: SessionDependency,
    user: AuthenticatedUser,
    before: Annotated[int | None, Query(ge=1, le=9223372036854775807)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    return service.history(session, user.id, conversation_id, before, limit)


@router.post("/{conversation_id}/messages/stream")
async def stream(
    conversation_id: UUID, body: MessageInput, session: SessionDependency, user: AuthenticatedUser
):
    try:
        events = await prepare_stream(session, user.id, conversation_id, body)
    except TimeoutError as error:
        raise AIError("模型回复超时", 504) from error
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/{conversation_id}/messages/{message_id}/images/download")
async def image_download(
    conversation_id: UUID,
    message_id: UUID,
    body: ImageDownloadInput,
    session: SessionDependency,
    user: AuthenticatedUser,
):
    url = service.image_for_download(session, user.id, conversation_id, message_id, body.url)
    data, mime = await asyncio.to_thread(download_image, url)
    suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
    return Response(
        data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="AI-image.{suffix}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{conversation_id}/messages/{message_id}/files/{file_id}/download")
def file_download(
    conversation_id: UUID,
    message_id: UUID,
    file_id: UUID,
    session: SessionDependency,
    user: AuthenticatedUser,
):
    file = download(session, user.id, conversation_id, message_id, file_id)
    return Response(
        file.data,
        media_type=file.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
