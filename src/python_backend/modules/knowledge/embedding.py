"""OpenAI SDK 向量批处理与响应校验。"""

import math

from openai import OpenAIError

from python_backend.core.config import settings
from python_backend.modules.ai.client import create_client
from python_backend.modules.ai.errors import AIError


async def embed(texts):
    if not settings.embedding_model:
        raise AIError("请配置 EMBEDDING_MODEL", 503)
    vectors = []
    try:
        async with create_client(embedding=True) as client:
            for start in range(0, len(texts), 16):
                batch = texts[start : start + 16]
                response = await client.embeddings.create(
                    model=settings.embedding_model, input=batch, encoding_format="float"
                )
                items = sorted(response.data, key=lambda item: item.index)
                if [item.index for item in items] != list(range(len(batch))):
                    raise ValueError()
                for item in items:
                    vector = item.embedding
                    if (
                        len(vector) != settings.embedding_dimensions
                        or not all(math.isfinite(x) for x in vector)
                        or not any(vector)
                    ):
                        raise ValueError()
                    vectors.append(vector)
    except (OpenAIError, ValueError, TypeError) as error:
        raise AIError("向量服务调用失败或向量维度不匹配", 502) from error
    return settings.embedding_model, vectors
