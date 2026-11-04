"""附件参数与文件签名校验。"""

import base64
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DOCUMENT_MIMES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/plain",
}


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    type: Literal["image", "document"]
    mime: str
    data: str | None = Field(default=None, max_length=2800000)
    text: str | None = Field(default=None, max_length=100000)

    @model_validator(mode="after")
    def validate_content(self):
        if self.type == "document":
            suffix = Path(self.name).suffix.lower()
            if (
                suffix not in DOCUMENT_MIMES
                or not self.text
                or "\0" in self.text
                or len(self.text.encode()) > 100000
            ):
                raise ValueError("文档内容无效或超过 100 KB")
            self.mime = DOCUMENT_MIMES[suffix]
            self.data = None
        else:
            if self.mime not in ("image/png", "image/jpeg", "image/webp"):
                raise ValueError("图片仅支持 PNG / JPEG / WebP")
            prefix = f"data:{self.mime};base64,"
            if not self.data or not self.data.startswith(prefix):
                raise ValueError("图片数据无效")
            try:
                encoded = self.data[len(prefix) :]
                raw = base64.b64decode(encoded, validate=True)
                if base64.b64encode(raw).decode() != encoded or not 0 < len(raw) <= 2 * 1024 * 1024:
                    raise ValueError("图片最大 2 MB")
                valid = (
                    raw.startswith(b"\x89PNG\r\n\x1a\n")
                    if self.mime == "image/png"
                    else raw.startswith(b"\xff\xd8\xff")
                    if self.mime == "image/jpeg"
                    else raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
                )
                if not valid:
                    raise ValueError("图片内容与格式不符")
            except (ValueError, TypeError) as error:
                raise ValueError("图片数据无效") from error
            self.text = None
        return self

    def byte_size(self):
        return (
            len(self.text.encode())
            if self.type == "document"
            else len(base64.b64decode(self.data.split(",", 1)[1]))
        )
