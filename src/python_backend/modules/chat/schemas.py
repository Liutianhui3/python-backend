from pydantic import BaseModel, ConfigDict, Field, model_validator

from python_backend.modules.ai.catalog import Effort
from python_backend.modules.chat.attachments import Attachment


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="新对话", min_length=1, max_length=100)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(default="", max_length=16000)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    reasoningEffort: Effort | None = None
    attachments: list[Attachment] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_content(self):
        if not self.content and self.attachments:
            self.content = "请分析附件内容。"
        if not self.content or "\0" in self.content:
            raise ValueError("消息不能为空或包含空字符")
        if sum(a.byte_size() for a in self.attachments) > 6 * 1024 * 1024:
            raise ValueError("附件总大小不能超过 6 MB")
        return self


class ImageDownloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=8192)
