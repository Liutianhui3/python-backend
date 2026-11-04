"""用户隔离的余弦检索；PostgreSQL 使用 pgvector 运算。"""

import math

from sqlalchemy import func, select

from python_backend.core.config import settings
from python_backend.modules.knowledge import embedding, service
from python_backend.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument


def candidates(user_id, base_id=None):
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument.name)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.base_id)
        .where(
            KnowledgeBase.user_id == user_id,
            KnowledgeChunk.embedding_model == settings.embedding_model,
            KnowledgeChunk.embedding.is_not(None),
        )
    )
    return stmt.where(KnowledgeBase.id == base_id) if base_id else stmt


def rank(session, user_id, vector, limit, base_id=None):
    stmt = candidates(user_id, base_id)
    if session.bind.dialect.name == "postgresql":
        distance = KnowledgeChunk.embedding.cosine_distance(vector)
        stmt = stmt.where(func.vector_dims(KnowledgeChunk.embedding) == len(vector))
        rows = session.execute(
            stmt.add_columns((1 - distance).label("score"))
            .order_by(distance, KnowledgeChunk.id)
            .limit(limit)
        )
    else:

        def cosine(a, b):
            if len(a) != len(b):
                return -1
            denom = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
            return sum(x * y for x, y in zip(a, b)) / denom if denom else -1

        rows = sorted(
            [(c, n, cosine(c.embedding, vector)) for c, n in session.execute(stmt)],
            key=lambda row: row[2],
            reverse=True,
        )[:limit]
    return [
        {
            "id": c.id,
            "documentId": c.document_id,
            "documentName": name,
            "position": c.position,
            "content": c.content,
            "score": float(score),
        }
        for c, name, score in rows
    ]


async def search(session, user_id, base_id, body):
    service.owned(session, user_id, base_id)
    session.rollback()
    _, vectors = await embedding.embed([body.query])
    service.owned(session, user_id, base_id)
    return {
        "items": rank(session, user_id, vectors[0], body.limit, base_id),
        "model": settings.embedding_model,
    }


async def retrieve(session, user_id, question):
    if (
        not settings.embedding_model
        or session.execute(candidates(user_id).limit(1)).first() is None
    ):
        return []
    session.rollback()
    _, vectors = await embedding.embed([question])
    return [
        {k: row[k] for k in ("documentName", "position", "content", "score")}
        for row in rank(session, user_id, vectors[0], 5)
        if row["score"] >= 0.35
    ]
