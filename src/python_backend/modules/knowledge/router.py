"""知识库 HTTP 路由：参数、认证和业务服务转发。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile

from python_backend.modules.ai.errors import AIError
from python_backend.modules.knowledge import rag, service
from python_backend.modules.knowledge.schemas import BaseInput, ChunkOptions, SearchInput
from python_backend.modules.users.router import AuthenticatedUser, SessionDependency

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


@router.get("")
def list_bases(session: SessionDependency, user: AuthenticatedUser):
    return service.list_bases(session, user.id)


@router.post("")
def create(body: BaseInput, session: SessionDependency, user: AuthenticatedUser):
    return service.create(session, user.id, body)


@router.get("/{base_id}/documents")
def documents(base_id: UUID, session: SessionDependency, user: AuthenticatedUser):
    return service.documents(session, user.id, base_id)


@router.post("/{base_id}/documents")
async def upload(
    base_id: UUID,
    session: SessionDependency,
    user: AuthenticatedUser,
    file: Annotated[UploadFile, File()],
    chunkSize: Annotated[int, Form(ge=100, le=2000)] = 500,
    chunkOverlap: Annotated[int, Form(ge=0)] = 50,
):
    if chunkOverlap >= chunkSize:
        raise AIError("重叠长度需小于切片长度", 422)
    # 在读文件前检查归属。
    service.owned(session, user.id, base_id)
    data = await file.read(1024 * 1024 + 1)
    return service.upload(
        session,
        user.id,
        base_id,
        file.filename or "",
        data,
        ChunkOptions(chunkSize=chunkSize, chunkOverlap=chunkOverlap),
    )


@router.get("/{base_id}/documents/{document_id}/chunks")
def chunks(
    base_id: UUID,
    document_id: UUID,
    session: SessionDependency,
    user: AuthenticatedUser,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
):
    return service.chunks(session, user.id, base_id, document_id, page)


@router.delete("/{base_id}/documents/{document_id}")
def remove(base_id: UUID, document_id: UUID, session: SessionDependency, user: AuthenticatedUser):
    return service.remove_document(session, user.id, base_id, document_id)


@router.post("/{base_id}/documents/{document_id}/embeddings")
async def embed(
    base_id: UUID, document_id: UUID, session: SessionDependency, user: AuthenticatedUser
):
    return await service.embed_document(session, user.id, base_id, document_id)


@router.post("/{base_id}/search")
async def search(
    base_id: UUID, body: SearchInput, session: SessionDependency, user: AuthenticatedUser
):
    return await rag.search(session, user.id, base_id, body)
