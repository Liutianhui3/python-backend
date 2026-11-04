from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Python Backend"

    db_host: str = Field(default="127.0.0.1", min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="python_backend", min_length=1)
    db_user: str = Field(default="postgres", min_length=1)
    db_password: SecretStr = SecretStr("")
    redis_url: str = "redis://127.0.0.1:6379/0"
    jwt_secret: SecretStr
    jwt_expire_seconds: int = Field(default=3600, gt=0)

    ai_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("AI_API_KEY", "DASHSCOPE_API_KEY")
    )
    ai_base_url: str = "https://maas.qianwenapi.com/compatible-mode/v1"
    ai_model: str = "qwen3.8-max"
    ai_models: str = ""
    ai_system_prompt: str = "你是一个有帮助的中文助手。"
    ai_timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    ai_max_tokens: int = Field(default=2048, ge=1, le=32768)
    ai_context_max_bytes: int = Field(default=24000, ge=1024, le=1000000)
    ai_image_tools_enabled: bool = True
    ai_image_model: str = "qwen-image-3.0-pro"
    ai_image_base_url: str = ""
    ai_image_api_key: SecretStr = SecretStr("")
    embedding_api_key: SecretStr = SecretStr("")
    embedding_base_url: str = "https://maas.qianwenapi.com/compatible-mode/v1"
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=1024, ge=1, le=4096)


settings = Settings()
