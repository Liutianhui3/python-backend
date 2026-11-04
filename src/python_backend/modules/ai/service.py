"""SDK 流式响应转换；不依赖 HTTP 路由或手工 fetch/SSE 解析。"""

import asyncio
import json
from contextlib import asynccontextmanager

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAIError

from python_backend.core.config import settings
from python_backend.modules.ai.client import create_client
from python_backend.modules.ai.errors import AIError
from python_backend.modules.ai.files import FILE_TOOLS, generate_file
from python_backend.modules.ai.images import IMAGE_TOOL, generate_image
from python_backend.modules.ai.platform import PLATFORM_TOOL


@asynccontextmanager
async def open_stream(messages, model, effort, tool_executor=None):
    options = {
        "model": model.id,
        "messages": messages,
        "stream": True,
        model.tokenParameter: settings.ai_max_tokens,
    }
    if effort != "auto":
        options["reasoning_effort"] = effort
    options["tools"] = [
        *FILE_TOOLS,
        *([PLATFORM_TOOL] if tool_executor else []),
        *([IMAGE_TOOL] if settings.ai_image_tools_enabled else []),
    ]
    options["tool_choice"] = "auto"
    options["parallel_tool_calls"] = False
    try:
        async with create_client() as client:
            history = list(messages)
            query_count = 0
            stream = await client.chat.completions.create(**options)
            async with stream:

                async def continue_with_tool(call):
                    nonlocal history, query_count
                    if query_count >= 4:
                        raise AIError("本轮工具查询次数过多，请缩小查询范围", 502)
                    query_count += 1
                    result = tool_executor(json.loads(call["arguments"]))
                    followup = [
                        *history,
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": "get_my_platform_info",
                                        "arguments": call["arguments"],
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        },
                    ]
                    # 保留完整工具结果，允许继续查询或调用文件生成工具。
                    history = followup
                    next_options = dict(options, messages=followup, tool_choice="auto")
                    next_stream = await client.chat.completions.create(**next_options)
                    async with next_stream:
                        async for delta in read_completion(next_stream, continue_with_tool):
                            yield delta

                yield read_completion(stream, continue_with_tool if tool_executor else None)
    except APITimeoutError as error:
        raise AIError("连接模型服务超时，请检查服务地址和网络", 504) from error
    except APIConnectionError as error:
        raise AIError("无法连接模型服务，请检查 AI_BASE_URL、网络及代理设置", 502) from error
    except APIStatusError as error:
        messages = {
            401: "模型服务认证失败，请检查 API Key",
            403: "模型服务拒绝访问，请检查密钥权限或服务地区限制",
            404: "模型或接口不存在，请检查 AI_MODEL 和 AI_BASE_URL",
            429: "模型服务限流或额度不足，请检查额度后重试",
        }
        message = messages.get(error.status_code, f"模型服务返回错误（HTTP {error.status_code}）")
        raise AIError(message, 502) from error
    except OpenAIError as error:
        raise AIError("模型服务调用失败", 502) from error


async def read_completion(stream, platform_handler=None):
    finished = None
    has_text = False
    tool_name = ""
    arguments = ""
    tool_id = None
    async for chunk in stream:
        if not chunk.choices:
            continue
        choice = next((c for c in chunk.choices if c.index == 0), None)
        if choice is None:
            continue
        if finished:
            raise AIError("模型输出格式不正确", 502)
        for tool in choice.delta.tool_calls or []:
            if tool.index != 0 or (tool_id and tool.id and tool.id != tool_id):
                raise AIError("每轮仅支持一个工具", 502)
            if tool.id:
                tool_id = tool.id
            if tool.function:
                tool_name += tool.function.name or ""
                arguments += tool.function.arguments or ""
            if len(arguments.encode()) > 200000 or len(tool_name) > 80:
                raise AIError("工具输入过大", 502)
        reasoning = getattr(choice.delta, "reasoning_content", None)
        if reasoning:
            if not isinstance(reasoning, str):
                raise AIError("模型分析内容格式无效", 502)
            yield {"reasoning": reasoning}
        if choice.delta.content:
            has_text = True
            yield {"text": choice.delta.content}
        if choice.finish_reason:
            finished = choice.finish_reason
    if finished == "tool_calls":
        if tool_name == "get_my_platform_info":
            if platform_handler is None or not tool_id:
                raise AIError("平台查询工具不可用", 502)
            try:
                async for delta in platform_handler({"id": tool_id, "arguments": arguments}):
                    yield delta
            except (ValueError, TypeError) as error:
                raise AIError("平台查询工具参数无效", 502) from error
            return
        if tool_name in ("generate_excel", "generate_word"):
            try:
                body = json.loads(arguments)
            except ValueError as error:
                raise AIError("文件工具参数无效", 502) from error
            yield {"fileGeneration": "generating"}
            yield {"file": await asyncio.to_thread(generate_file, tool_name, body)}
            yield {"finishReason": "stop"}
            return
        try:
            prompt = json.loads(arguments)["prompt"]
            if (
                not settings.ai_image_tools_enabled
                or tool_name != "generate_image"
                or not isinstance(prompt, str)
                or not 1 <= len(prompt.strip()) <= 16000
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError) as error:
            raise AIError("图片工具参数无效", 502) from error
        yield {"imageGeneration": "generating"}
        yield {"text": await generate_image(prompt)}
        yield {"finishReason": "stop"}
    elif finished in ("stop", "length") and has_text:
        yield {"finishReason": finished}
    else:
        raise AIError("模型输出中断或未产生有效回复", 502)
