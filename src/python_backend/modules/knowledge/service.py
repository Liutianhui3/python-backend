"""知识库归属校验、文档事务与切片分页。"""

from pathlib import Path

from sqlalchemy import delete, func, select

from python_backend.core.config import settings
from python_backend.modules.ai.errors import AIError
from python_backend.modules.knowledge import embedding
from python_backend.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from python_backend.modules.knowledge.split_text import split_text


def owned(session, user_id, base_id):
    base = session.scalar(
        select(KnowledgeBase).where(KnowledgeBase.id == base_id, KnowledgeBase.user_id == user_id)
    )
    if base is None:
        raise AIError("知识库不存在", 404)
    return base


def document(session, user_id, base_id, document_id, lock=False):
    owned(session, user_id, base_id)
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.id == document_id, KnowledgeDocument.base_id == base_id
    )
    doc = session.scalar(stmt.with_for_update() if lock else stmt)
    if doc is None:
        raise AIError("文档不存在", 404)
    return doc


def base_data(session, base):
    count, chunks = session.execute(
        select(func.count(), func.coalesce(func.sum(KnowledgeDocument.chunk_count), 0)).where(
            KnowledgeDocument.base_id == base.id
        )
    ).one()
    return {
        "id": base.id,
        "name": base.name,
        "description": base.description,
        "createdAt": base.created_at,
        "documentCount": count,
        "chunkCount": chunks,
    }


def list_bases(session, user_id):
    bases = session.scalars(
        select(KnowledgeBase)
        .where(KnowledgeBase.user_id == user_id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    return [base_data(session, base) for base in bases]


def create(session, user_id, body):
    base = KnowledgeBase(user_id=user_id, **body.model_dump())
    session.add(base)
    session.commit()
    return base_data(session, base)


def document_data(doc):
    return {
        "id": doc.id,
        "name": doc.name,
        "size": doc.size,
        "chunkSize": doc.chunk_size,
        "chunkOverlap": doc.chunk_overlap,
        "chunkCount": doc.chunk_count,
        "createdAt": doc.created_at,
    }


def documents(session, user_id, base_id):
    owned(session, user_id, base_id)
    result = []
    for doc in session.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.base_id == base_id)
        .order_by(KnowledgeDocument.created_at.desc())
    ):
        count = session.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(
                KnowledgeChunk.document_id == doc.id,
                KnowledgeChunk.embedding.is_not(None),
                KnowledgeChunk.embedding_model == settings.embedding_model,
            )
        )
        result.append({**document_data(doc), "embeddedChunks": count})
    return result


def upload(session, user_id, base_id, filename, data, options):
    owned(session, user_id, base_id)
    if Path(filename).suffix.lower() not in (".txt", ".md") or not 0 < len(data) <= 1024 * 1024:
        raise AIError("请选择 1 B–1 MB 的 TXT 或 Markdown 文件")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise AIError("请上传 UTF-8 编码的文本文件") from error
    chunks = split_text(text, options.chunkSize, options.chunkOverlap)
    doc = KnowledgeDocument(
        base_id=base_id,
        name=filename[:255],
        size=len(data),
        content=text,
        chunk_size=options.chunkSize,
        chunk_overlap=options.chunkOverlap,
        chunk_count=len(chunks),
    )
    session.add(doc)
    session.flush()
    session.add_all([KnowledgeChunk(document_id=doc.id, **c) for c in chunks])
    session.commit()
    return document_data(doc)


def chunks(session, user_id, base_id, document_id, page):
    doc = document(session, user_id, base_id, document_id)
    items = session.scalars(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == document_id)
        .order_by(KnowledgeChunk.position)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return {
        "items": [
            {"id": c.id, "position": c.position, "content": c.content, "charCount": c.char_count}
            for c in items
        ],
        "total": doc.chunk_count,
        "page": page,
    }


def remove_document(session, user_id, base_id, document_id):
    doc = document(session, user_id, base_id, document_id)
    session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
    session.delete(doc)
    session.commit()
    return {"id": document_id}


async def embed_document(session, user_id, base_id, document_id):
    document(session, user_id, base_id, document_id)
    rows = list(
        session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.position)
        )
    )
    texts = [c.content for c in rows]
    ids = [c.id for c in rows]
    session.rollback()  # 不跨远程调用持有数据库事务。
    model, vectors = await embedding.embed(texts)
    document(session, user_id, base_id, document_id, lock=True)
    current = list(session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids))))
    if len(current) != len(ids):
        raise AIError("文档已发生变化，请重试", 409)
    lookup = dict(zip(ids, vectors, strict=True))
    for chunk in current:
        chunk.embedding = lookup[chunk.id]
        chunk.embedding_model = model
    session.commit()
    return {
        "documentId": document_id,
        "model": model,
        "dimensions": settings.embedding_dimensions,
        "embeddedChunks": len(vectors),
    }
