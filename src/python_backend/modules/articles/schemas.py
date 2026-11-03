"""文章接口参数及字段校验。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArticleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=300)
    content: str = Field(default="", max_length=200000)
    category: str = Field(default="随笔", max_length=40)
    tags: list[Annotated[str, Field(min_length=1, max_length=24)]] = Field(
        default_factory=list, max_length=8
    )
    cover_url: str = Field(default="", alias="coverUrl", max_length=2000)
    status: Literal["draft", "published"] = "draft"
    version: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("cover_url")
    @classmethod
    def validate_cover(cls, value: str) -> str:
        from urllib.parse import urlsplit

        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("封面需使用 HTTPS 地址")
        return value


class ArticleQuery(BaseModel):
    page: int = Field(default=1, ge=1, le=100000)
    limit: int = Field(default=12, ge=1, le=50)
    q: str = Field(default="", max_length=100)
    status: Literal["", "draft", "published"] = ""
    category: str = Field(default="", max_length=40)
