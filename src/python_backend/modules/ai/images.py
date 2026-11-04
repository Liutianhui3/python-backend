"""通过千问原生多模态接口生成图片，供聊天工具调用。"""

import re
from urllib.parse import urlsplit

import httpx2 as httpx

from python_backend.core.config import settings
from python_backend.modules.ai.errors import AIError

IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "当用户要求画图、生成图片、插画或海报时调用。将用户要求转换为完整的图片描述，"
            "保留风格、主体、构图及需要呈现的文字。仅分析已有图片或讨论画图时不要调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
}


def image_markdown(url):
    if not isinstance(url, str) or len(url) > 12000000 or re.search(r"[<>\r\n]", url):
        raise AIError("图片服务返回的图片格式无效", 502)
    if not re.fullmatch(r"data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}", url):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise AIError("图片服务返回的图片格式无效", 502)
    return f"\n\n![AI 生成的图片](<{url}>)\n\n"


async def generate_image(prompt):
    url = settings.ai_image_base_url.strip()
    parsed = urlsplit(url)
    key = settings.ai_image_api_key.get_secret_value() or settings.ai_api_key.get_secret_value()
    if (
        not key
        or parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or any((parsed.username, parsed.password, parsed.query, parsed.fragment))
    ):
        raise AIError("请配置图片服务 API Key 和 AI_IMAGE_BASE_URL 完整接口地址", 503)
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_ms / 1000) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": settings.ai_image_model,
                    "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                    "parameters": {"prompt_extend": True},
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException as error:
        raise AIError("图片生成超时，请稍后重试", 504) from error
    except httpx.RequestError as error:
        raise AIError("无法连接图片服务，请检查图片服务地址、网络及代理", 502) from error
    except httpx.HTTPStatusError as error:
        raise AIError(
            f"图片服务返回错误（HTTP {error.response.status_code}），"
            "请检查图片模型、接口及额度配置",
            502,
        ) from error
    try:
        result = response.json()
        if result.get("code"):
            raise AIError("图片生成失败，请检查图片模型、接口及额度配置", 502)
        images = []
        for choice in result.get("output", {}).get("choices", []):
            for part in choice.get("message", {}).get("content", []):
                if part.get("image"):
                    images.append(image_markdown(part["image"]))
        if images:
            return "".join(images)
    except (ValueError, TypeError, AttributeError) as error:
        raise AIError("图片服务返回的响应格式无效", 502) from error
    raise AIError("图片服务未返回图片", 502)
