"""生成文件的消息关联、持久化与下载归属校验。"""

from sqlalchemy import select

from python_backend.modules.ai.errors import AIError
from python_backend.modules.chat.models import GeneratedFile, Message
from python_backend.modules.chat.service import owned


def file_data(row, conversation_id):
    return {
        "id": str(row.id),
        "name": row.name,
        "mimeType": row.mime_type,
        "size": len(row.data),
        "downloadUrl": (
            f"/conversations/{conversation_id}/messages/{row.message_id}/files/{row.id}/download"
        ),
    }


def save_file(session, turn, file):
    row = GeneratedFile(
        message_id=turn.message_id, name=file["name"], mime_type=file["mimeType"], data=file["data"]
    )
    session.add(row)
    session.flush()
    # 与消息完成状态一起提交；发送 done 前必须持久化。
    return file_data(row, turn.conversation_id)


def download(session, user_id, conversation_id, message_id, file_id):
    owned(session, user_id, conversation_id)
    row = session.scalar(
        select(GeneratedFile)
        .join(Message, Message.id == GeneratedFile.message_id)
        .where(
            GeneratedFile.id == file_id,
            Message.id == message_id,
            Message.conversation_id == conversation_id,
        )
    )
    if row is None:
        raise AIError("文件不存在或无权下载", 404)
    return row
