from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "service-a"
    instance_id: str = "service-a-local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://gateway:gateway@postgres:5432/service_a"
    # Shared with the gateway: proves a request came through it.
    internal_secret: str = "internal-shared-secret-change-me"
    # Shared between backend services for service-to-service calls (reserve/release).
    service_token: str = "service-to-service-token-change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
