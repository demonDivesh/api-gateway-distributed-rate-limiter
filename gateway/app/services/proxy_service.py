"""Reverse proxy: picks an upstream, forwards the request, applies retries + breaker."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import Request
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

from app.core.config import RouteConfig, Settings
from app.core.exceptions import (
    BadRequestError,
    PayloadTooLarge,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from app.core.security import TokenClaims
from app.services.load_balancer import LoadBalancer, UpstreamInstance
from app.utils.metrics import Metrics

logger = logging.getLogger("gateway.proxy")

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
# Never forwarded from the client: credentials, and headers only the gateway may set.
STRIPPED_REQUEST_PREFIXES = ("x-user-", "x-gateway-", "x-forwarded-", "x-real-ip")
STRIPPED_REQUEST_HEADERS = {"authorization", "cookie", "x-request-id"}
IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
RETRYABLE_STATUS = {502, 503, 504}


def validate_path(path: str, raw_path: bytes | None) -> None:
    """Reject traversal attempts and control characters before they reach an upstream."""
    candidates = [path]
    if raw_path:
        candidates.append(raw_path.decode("latin-1").split("?", 1)[0].lower())
    for candidate in candidates:
        lowered = candidate.lower()
        if any(ch in candidate for ch in ("\\", "\x00")) or any(ord(c) < 32 for c in candidate):
            raise BadRequestError("Illegal characters in path")
        if "%2e" in lowered or "%2f" in lowered or "%5c" in lowered or "%00" in lowered:
            raise BadRequestError("Encoded path traversal is not allowed")
        if ".." in candidate.split("/"):
            raise BadRequestError("Path traversal is not allowed")


async def read_limited_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge(f"Request body exceeds {limit} bytes")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLarge(f"Request body exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


class ProxyService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        balancer: LoadBalancer,
        settings: Settings,
        metrics: Metrics,
    ) -> None:
        self._client = client
        self._balancer = balancer
        self._settings = settings
        self._metrics = metrics

    def build_upstream_headers(
        self, request: Request, claims: TokenClaims | None, client_ip: str
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in request.headers.items():
            lname = name.lower()
            if (
                lname in HOP_BY_HOP
                or lname in STRIPPED_REQUEST_HEADERS
                or lname.startswith(STRIPPED_REQUEST_PREFIXES)
            ):
                continue
            headers[lname] = value
        headers["x-request-id"] = getattr(request.state, "request_id", "")
        headers["x-gateway-secret"] = self._settings.internal_secret
        headers["x-forwarded-for"] = client_ip
        headers["x-forwarded-host"] = request.headers.get("host", "")
        headers["x-forwarded-proto"] = request.url.scheme
        if claims:
            headers["x-user-id"] = claims.subject
            headers["x-user-name"] = claims.username
            headers["x-user-role"] = claims.role
        return headers

    async def forward(
        self,
        request: Request,
        route: RouteConfig,
        remainder: str,
        claims: TokenClaims | None,
        client_ip: str,
    ) -> Response:
        pool = self._balancer.pool(route.name)
        body = await read_limited_body(request, self._settings.max_request_body_bytes)
        headers = self.build_upstream_headers(request, claims, client_ip)
        method = request.method.upper()
        path = "/" + remainder.lstrip("/") if route.strip_prefix else request.url.path
        query = request.url.query
        max_attempts = 1 + (self._settings.proxy_max_retries if method in IDEMPOTENT_METHODS else 0)

        tried: set[str] = set()
        last_timeout = False
        for attempt in range(max_attempts):
            instance = pool.select(exclude=tried)
            if instance is None or not instance.breaker.allow_request():
                break
            tried.add(instance.url)
            instance.active_connections += 1
            instance.total_requests += 1
            url = instance.url + path + (f"?{query}" if query else "")
            try:
                upstream_request = self._client.build_request(
                    method,
                    url,
                    headers=headers,
                    content=body or None,
                    timeout=httpx.Timeout(
                        route.timeout_seconds, connect=self._settings.upstream_connect_timeout
                    ),
                )
                response = await self._client.send(upstream_request, stream=True)
            except httpx.TimeoutException:
                self._finish(route, instance, ok=False, outcome="timeout")
                last_timeout = True
                logger.warning(
                    "upstream timeout", extra={"upstream": instance.url, "attempt": attempt}
                )
                continue
            except httpx.TransportError as exc:
                self._finish(route, instance, ok=False, outcome="connection_error")
                last_timeout = False
                logger.warning(
                    "upstream connection error",
                    extra={
                        "upstream": instance.url,
                        "error": type(exc).__name__,
                        "attempt": attempt,
                    },
                )
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < max_attempts - 1:
                await response.aclose()
                self._finish(route, instance, ok=False, outcome="5xx")
                continue

            ok = response.status_code < 500
            self._metrics.observe_upstream(route.name, "success" if ok else "5xx")
            if ok:
                instance.breaker.record_success()
            else:
                instance.breaker.record_failure()
            return self._stream(response, instance, route)

        if last_timeout:
            raise UpstreamTimeout(f"Upstream '{route.name}' timed out")
        raise UpstreamUnavailable(f"No healthy upstream available for '{route.name}'")

    def _finish(
        self, route: RouteConfig, instance: UpstreamInstance, *, ok: bool, outcome: str
    ) -> None:
        instance.active_connections = max(0, instance.active_connections - 1)
        self._metrics.observe_upstream(route.name, outcome)
        if ok:
            instance.breaker.record_success()
        else:
            instance.breaker.record_failure()

    def _stream(
        self, response: httpx.Response, instance: UpstreamInstance, route: RouteConfig
    ) -> Response:
        async def body() -> AsyncIterator[bytes]:
            async for chunk in response.aiter_raw():
                yield chunk

        async def cleanup() -> None:
            await response.aclose()
            instance.active_connections = max(0, instance.active_connections - 1)

        out_headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("connection", "keep-alive", "transfer-encoding", "server")
        }
        out_headers["x-gateway-upstream"] = route.name
        return StreamingResponse(
            body(),
            status_code=response.status_code,
            headers=out_headers,
            background=BackgroundTask(cleanup),
        )
