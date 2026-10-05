"""Security headers and basic request validation."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.exceptions import BadRequestError, GatewayError, PayloadTooLarge, to_response
from app.services.proxy_service import validate_path

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, hsts: bool = False) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        h.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if not request.url.path.startswith(DOC_PATHS):
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/v1/auth"):
            h.setdefault("Cache-Control", "no-store")
        if self._hsts:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        if "server" in h:
            del h["server"]
        return response


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Rejects malformed requests before any routing or upstream work happens."""

    def __init__(self, app, max_body_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max_body = max_body_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = getattr(request.state, "request_id", None)
        try:
            if request.method.upper() not in ALLOWED_METHODS:
                raise GatewayError("Method not allowed")
            validate_path(request.url.path, request.scope.get("raw_path"))
            declared = request.headers.get("content-length")
            if declared is not None:
                if not declared.isdigit():
                    raise BadRequestError("Invalid Content-Length header")
                if int(declared) > self._max_body:
                    raise PayloadTooLarge(f"Request body exceeds {self._max_body} bytes")
            if len(request.url.query) > 8192:
                raise BadRequestError("Query string too long")
        except GatewayError as exc:
            if exc.message == "Method not allowed":
                exc.status_code = 405  # type: ignore[assignment]
                exc.code = "method_not_allowed"
            return to_response(exc, rid)
        return await call_next(request)
