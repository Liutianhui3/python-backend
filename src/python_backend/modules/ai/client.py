"""OpenAI 兼容 SDK 工厂；密钥仅在调用时读取，不在导入时连接服务。"""

from urllib.parse import urlsplit

from openai import AsyncOpenAI

from python_backend.core.config import settings
from python_backend.modules.ai.errors import AIError


def create_client(*, embedding=False):
    key = settings.embedding_api_key.get_secret_value() if embedding else ""
    key = key or settings.ai_api_key.get_secret_value()
    base = settings.embedding_base_url if embedding else settings.ai_base_url
    url = urlsplit(base)
    if (
        not key
        or url.scheme not in ("https", "http")
        or not url.hostname
        or any((url.username, url.password, url.query, url.fragment))
    ):
        raise AIError("请检查模型 API Key 和 Base URL 配置", 503)
    return AsyncOpenAI(
        api_key=key,
        base_url=base.rstrip("/"),
        timeout=settings.ai_timeout_ms / 1000,
        max_retries=0,
    )
