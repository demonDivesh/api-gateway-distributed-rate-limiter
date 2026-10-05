from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "service-b"
    instance_id: str = "service-b-local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://gateway:gateway@postgres:5432/service_b"
    internal_secret: str = "internal-shared-secret-change-me"
    service_token: str = "service-to-service-token-change-me"
    # Service A is called directly (bypassing the gateway) on the internal network.
    catalog_url: str = "http://service-a:8000"
    catalog_timeout_seconds: float = 3.0
    catalog_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
