from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Python Backend"

    db_host: str = Field(default="127.0.0.1", min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="python_backend", min_length=1)
    db_user: str = Field(default="postgres", min_length=1)
    db_password: SecretStr = SecretStr("")


settings = Settings()
