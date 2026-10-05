"""Distributed rate limiting middleware.

Identity is the authenticated user id when a valid access token is present, else the
client IP. Limits depend on role; login/registration get a strict per-IP limit to slow
credential stuffing. Health, metrics and docs endpoints are exempt.
"""

from __future__ import annotations

import logging
import time

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.exceptions import GatewayError, RateLimitExceeded, UpstreamUnavailable, to_response
from app.utils.net import client_ip

logger = logging.getLogger("gateway.ratelimit")

EXEMPT_PREFIXES = ("/health", "/metrics", "/docs", "/redoc", "/openapi.json")
STRICT_PATHS = ("/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh")


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        state = request.app.state
        settings = state.settings
        path = request.url.path
        rid = getattr(request.state, "request_id", None)
        request.state.claims = None
        request.state.auth_error = None

        # Authenticate opportunistically so limits can be per-user (enforcement is per-route).
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            try:
                request.state.claims = await state.auth_service.authenticate(header[7:].strip())
            except GatewayError as exc:
                request.state.auth_error = exc

        if (
            not settings.rate_limit_enabled
            or request.method == "OPTIONS"
            or path.startswith(EXEMPT_PREFIXES)
        ):
            return await call_next(request)

        ip = client_ip(request, settings.trust_forwarded_for)
        claims = request.state.claims
        if path.startswith(STRICT_PATHS):
            scope, identity, limit = "auth", f"ip:{ip}", settings.rate_limit_auth_per_minute
        elif claims:
            limit = (
                settings.rate_limit_admin_per_minute
                if claims.role == "admin"
                else settings.rate_limit_user_per_minute
            )
            scope, identity = "api", f"user:{claims.subject}"
        else:
            scope, identity = "api", f"ip:{ip}"
            limit = settings.rate_limit_anonymous_per_minute

        try:
            result = await state.rate_limiter.check(scope, identity, limit, 60)
        except RedisError as exc:
            state.metrics.observe_rate_limit("error")
            logger.error("rate limiter backend error: %s", exc)
            if settings.rate_limit_fail_open:
                return await call_next(request)
            return to_response(UpstreamUnavailable("Rate limiter unavailable"), rid)

        headers = {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(int(time.time()) + result.reset_after_seconds),
        }
        if not result.allowed:
            state.metrics.observe_rate_limit("limited")
            headers["Retry-After"] = str(result.retry_after_seconds)
            logger.info("rate limited", extra={"identity": identity, "scope": scope})
            return to_response(
                RateLimitExceeded("Rate limit exceeded. Try again later.", headers=headers), rid
            )

        state.metrics.observe_rate_limit("allowed")
        response = await call_next(request)
        response.headers.update(headers)
        return response
