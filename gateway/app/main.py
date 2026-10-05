"""Application factory and lifespan wiring."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.routes import auth, gateway, health, metrics
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.infrastructure.database import (
    create_engine,
    create_session_factory,
    init_models,
    wait_for_database,
)
from app.infrastructure.http_client import create_http_client
from app.infrastructure.redis_client import create_redis
from app.middleware.logging import AccessLogMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security import RequestValidationMiddleware, SecurityHeadersMiddleware
from app.services.auth_service import AuthService
from app.services.circuit_breaker import CircuitBreaker
from app.services.health_checker import HealthChecker
from app.services.load_balancer import LoadBalancer, UpstreamInstance, UpstreamPool
from app.services.proxy_service import ProxyService
from app.services.rate_limiter import RateLimiter
from app.utils.metrics import Metrics

logger = logging.getLogger("gateway")


def build_balancer(settings: Settings) -> LoadBalancer:
    pools: dict[str, UpstreamPool] = {}
    for route in settings.routes:
        instances = [
            UpstreamInstance(
                url=url.rstrip("/"),
                breaker=CircuitBreaker(
                    settings.cb_failure_threshold,
                    settings.cb_recovery_seconds,
                    settings.cb_half_open_max_calls,
                ),
            )
            for url in route.upstreams
        ]
        pools[route.name] = UpstreamPool(route.name, instances, settings.load_balancer_strategy)
    return LoadBalancer(pools)


def create_app(
    settings: Settings | None = None,
    *,
    redis: aioredis.Redis | None = None,
    http_client: httpx.AsyncClient | None = None,
    engine: AsyncEngine | None = None,
    start_health_checker: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_production()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        own_redis = redis is None
        own_client = http_client is None
        own_engine = engine is None
        app.state.redis = redis or create_redis(settings.redis_url)
        app.state.http_client = http_client or create_http_client(
            settings.upstream_connect_timeout, settings.upstream_read_timeout
        )
        app.state.engine = engine or create_engine(settings.database_url)
        app.state.session_factory = create_session_factory(app.state.engine)
        await wait_for_database(app.state.engine)
        await init_models(app.state.engine)

        app.state.settings = settings
        app.state.metrics = Metrics()
        app.state.rate_limiter = RateLimiter(app.state.redis, settings.rate_limit_algorithm)
        app.state.auth_service = AuthService(settings, app.state.redis)
        app.state.load_balancer = build_balancer(settings)
        app.state.routes = {r.prefix: r for r in settings.routes}
        app.state.proxy = ProxyService(
            app.state.http_client, app.state.load_balancer, settings, app.state.metrics
        )
        app.state.health_checker = HealthChecker(
            app.state.http_client,
            app.state.load_balancer,
            settings.health_check_interval_seconds,
            settings.health_check_timeout_seconds,
        )
        await app.state.auth_service.ensure_admin(app.state.session_factory)
        if start_health_checker:
            await app.state.health_checker.start()
        logger.info("gateway started", extra={"environment": settings.environment})
        try:
            yield
        finally:
            await app.state.health_checker.stop()
            if own_client:
                await app.state.http_client.aclose()
            if own_redis:
                await app.state.redis.aclose()
            if own_engine:
                await app.state.engine.dispose()
            logger.info("gateway stopped")

    app = FastAPI(
        title="API Gateway & Distributed Rate Limiter",
        version="1.0.0",
        description="JWT-authenticated reverse proxy with Redis-backed distributed rate limiting, "
        "load balancing, health checks and circuit breaking. Any method on "
        "`/api/{service}/{path}` (service-a, service-b) is proxied to the matching upstream "
        "pool and requires a Bearer access token (see API.md).",
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )
    register_exception_handlers(app)

    # add_middleware: the last one added is the outermost.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestValidationMiddleware, max_body_bytes=settings.max_request_body_bytes)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.environment == "production")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
            "X-Gateway-Upstream",
        ],
    )

    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(auth.router)
    app.include_router(gateway.router)
    return app
