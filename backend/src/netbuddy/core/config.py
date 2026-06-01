from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NetBuddy"
    debug: bool = False
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://netbuddy:netbuddy@localhost:5432/netbuddy"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    fernet_key: SecretStr


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
