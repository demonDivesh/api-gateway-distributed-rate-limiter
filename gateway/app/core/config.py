"""Gateway configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RouteConfig(BaseModel):
    """A gateway route: a public prefix mapped to a pool of upstream instances."""

    name: str
    prefix: str
    upstreams: list[str]
    auth_required: bool = True
    allowed_roles: list[str] = Field(default_factory=list)  # empty = any role
    strip_prefix: bool = True
    timeout_seconds: float = 10.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "api-gateway"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # Auth
    jwt_secret: str = "change-me-in-production-please-use-32+chars"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 7 * 24 * 3600
    admin_username: str = "admin"
    admin_password: str = "admin-change-me"
    allow_registration: bool = True
    auth_revocation_fail_open: bool = False
    metrics_token: str = ""

    # Storage
    database_url: str = "postgresql+asyncpg://gateway:gateway@postgres:5432/gateway"
    redis_url: str = "redis://redis:6379/0"

    # Upstreams (comma separated URLs)
    service_a_urls: str = "http://service-a-1:8000,http://service-a-2:8000"
    service_b_urls: str = "http://service-b:8000"
    internal_secret: str = "internal-shared-secret-change-me"

    # Proxy
    upstream_connect_timeout: float = 2.0
    upstream_read_timeout: float = 10.0
    proxy_max_retries: int = 2
    max_request_body_bytes: int = 1_048_576
    load_balancer_strategy: Literal["round_robin", "least_connections", "random"] = "round_robin"

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_algorithm: Literal["sliding_window", "token_bucket"] = "sliding_window"
    rate_limit_anonymous_per_minute: int = 30
    rate_limit_user_per_minute: int = 120
    rate_limit_admin_per_minute: int = 600
    rate_limit_auth_per_minute: int = 10
    rate_limit_fail_open: bool = True
    trust_forwarded_for: bool = False

    # Circuit breaker
    cb_failure_threshold: int = 5
    cb_recovery_seconds: float = 15.0
    cb_half_open_max_calls: int = 2

    # Health checks
    health_check_interval_seconds: float = 5.0
    health_check_timeout_seconds: float = 2.0

    # Security
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_length(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("JWT_SECRET must be at least 16 characters")
        return v

    @staticmethod
    def _split(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return self._split(self.cors_origins)

    @property
    def routes(self) -> list[RouteConfig]:
        return [
            RouteConfig(
                name="service-a",
                prefix="/api/service-a",
                upstreams=self._split(self.service_a_urls),
                timeout_seconds=self.upstream_read_timeout,
            ),
            RouteConfig(
                name="service-b",
                prefix="/api/service-b",
                upstreams=self._split(self.service_b_urls),
                timeout_seconds=self.upstream_read_timeout,
            ),
        ]

    def validate_for_production(self) -> None:
        if self.environment != "production":
            return
        weak = {
            "jwt_secret": "change-me",
            "admin_password": "change-me",
            "internal_secret": "change-me",
        }
        for field, marker in weak.items():
            if marker in getattr(self, field):
                raise RuntimeError(f"{field.upper()} must be changed in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
