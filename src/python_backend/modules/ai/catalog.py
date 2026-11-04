"""模型白名单与思考档次校验，不向客户端暴露传输配置。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from python_backend.core.config import settings
from python_backend.modules.ai.errors import AIError

Effort = Literal["auto", "low", "medium", "high", "xhigh", "max"]


class ModelDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$")
    label: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=160)
    reasoningEfforts: list[Literal["low", "medium", "high", "xhigh", "max"]] = []
    defaultEffort: Effort = "auto"
    tokenParameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"

    @model_validator(mode="after")
    def validate_effort(self):
        if self.defaultEffort != "auto" and self.defaultEffort not in self.reasoningEfforts:
            raise ValueError("default effort is unsupported")
        if len(set(self.reasoningEfforts)) != len(self.reasoningEfforts):
            raise ValueError("duplicate efforts")
        self.label = self.label or self.id
        return self


def catalog():
    import json

    try:
        raw = json.loads(settings.ai_models) if settings.ai_models else [{"id": settings.ai_model}]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
            raise ValueError()
        models = [ModelDefinition.model_validate(item) for item in raw]
        ids = [m.id for m in models]
        if len(set(ids)) != len(ids) or settings.ai_model not in ids:
            raise ValueError()
        return models
    except (ValueError, TypeError, ValidationError) as error:
        raise AIError("AI_MODELS 配置无效", 503) from error


def models():
    return {
        "defaultModel": settings.ai_model,
        "models": [m.model_dump(exclude={"tokenParameter"}) for m in catalog()],
    }


def resolve(model=None, effort=None):
    selected = next((m for m in catalog() if m.id == (model or settings.ai_model)), None)
    if selected is None:
        raise AIError("所选模型不可用")
    effort = effort if effort is not None else selected.defaultEffort
    if effort != "auto" and effort not in selected.reasoningEfforts:
        raise AIError("当前模型不支持所选思考档次")
    return selected, effort
