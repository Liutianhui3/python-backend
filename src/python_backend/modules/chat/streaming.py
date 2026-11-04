"""SSE 协议、总超时、心跳、取消和最终消息状态。"""

import asyncio
import json
import logging

import anyio
from fastapi.encoders import jsonable_encoder

from python_backend.core.config import settings
from python_backend.modules.ai import service as ai
from python_backend.modules.ai.errors import AIError
from python_backend.modules.ai.platform import query_platform
from python_backend.modules.chat import service
from python_backend.modules.chat.files import save_file

logger = logging.getLogger(__name__)


def event(name, data):
    return f"event: {name}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


async def stream_events(session, turn, stream, manager, deadline):
    content = ""
    reasoning = ""
    size = 0
    finish_reason = None
    status = "failed"
    pending = None
    files = []
    try:
        yield event(
            "start",
            {
                "conversationId": turn.conversation_id,
                "userMessageId": turn.user_message_id,
                "messageId": turn.message_id,
                "model": turn.model.id,
                "reasoningEffort": turn.effort,
            },
        )
        async with asyncio.timeout_at(deadline):
            while True:
                pending = asyncio.create_task(anext(stream))
                while not pending.done():
                    done, _ = await asyncio.wait({pending}, timeout=15)
                    if not done:
                        yield ": ping\n\n"
                try:
                    delta = pending.result()
                except StopAsyncIteration:
                    break
                if delta.get("reasoning"):
                    size += len(delta["reasoning"].encode())
                    if size > 12000000:
                        raise AIError("模型回复超过长度限制", 502)
                    reasoning += delta["reasoning"]
                    yield event("reasoning", {"text": delta["reasoning"]})
                if delta.get("text"):
                    size += len(delta["text"].encode())
                    if size > 12000000:
                        raise AIError("模型回复超过长度限制", 502)
                    content += delta["text"]
                    yield event("delta", {"text": delta["text"]})
                if delta.get("fileGeneration"):
                    yield event("file_generation", {"status": "generating"})
                if delta.get("file"):
                    files.append(delta["file"])
                if delta.get("imageGeneration"):
                    yield event("image_generation", {"status": delta["imageGeneration"]})
                finish_reason = delta.get("finishReason", finish_reason)
        summary = ""
        if files:
            summary = "\n\n已生成文件：" + "、".join(file["name"] for file in files)
            content += summary
        metadata = [save_file(session, turn, file) for file in files]
        service.finish(session, turn, content, "completed", reasoning)
        status = "completed"
        if summary:
            yield event("delta", {"text": summary})
        for file in metadata:
            yield event("file", file)
        yield event("done", {"messageId": turn.message_id, "finishReason": finish_reason})
    except (asyncio.CancelledError, GeneratorExit):
        if status != "completed":
            status = "cancelled"
        raise
    except Exception as error:
        code = (
            504
            if isinstance(error, TimeoutError)
            else error.code
            if isinstance(error, AIError)
            else 502
        )
        message = (
            "模型回复超时"
            if code == 504
            else str(error)
            if isinstance(error, AIError)
            else "聊天服务暂时不可用"
        )
        yield event("error", {"statusCode": code, "message": message})
    finally:
        # Starlette 使用取消作用域处理断开，屏蔽清理阶段的重复取消。
        with anyio.CancelScope(shield=True):
            if pending and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            try:
                await stream.aclose()
            finally:
                await manager.__aexit__(None, None, None)
            if status != "completed":
                try:
                    session.rollback()
                    service.finish(session, turn, content, status, reasoning)
                except Exception:
                    session.rollback()
                    logger.error("无法保存回复状态；生成租约过期后将释放会话")


async def prepare_stream(session, user_id, conversation_id, body):
    deadline = asyncio.get_running_loop().time() + settings.ai_timeout_ms / 1000
    turn = None
    manager = None
    entered = False
    try:
        async with asyncio.timeout_at(deadline):
            turn = await service.prepare(session, user_id, conversation_id, body)
            manager = ai.open_stream(
                turn.messages,
                turn.model,
                turn.effort,
                tool_executor=lambda arguments: query_platform(session, user_id, arguments),
            )
            stream = await manager.__aenter__()
            entered = True
        return stream_events(session, turn, stream, manager, deadline)
    except BaseException:
        if entered:
            await manager.__aexit__(None, None, None)
        if turn:
            session.rollback()
            service.finish(session, turn, "", "failed")
        raise
