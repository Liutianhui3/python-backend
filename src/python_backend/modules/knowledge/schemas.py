from pydantic import BaseModel, ConfigDict, Field, model_validator


class BaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)


class ChunkOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunkSize: int = Field(default=500, ge=100, le=2000)
    chunkOverlap: int = Field(default=50, ge=0)

    @model_validator(mode="after")
    def overlap(self):
        if self.chunkOverlap >= self.chunkSize:
            raise ValueError("重叠长度需小于切片长度")
        return self


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20, strict=True)
