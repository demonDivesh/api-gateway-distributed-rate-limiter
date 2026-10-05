"""Domain exceptions and uniform JSON error handling."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("gateway.errors")


class GatewayError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers = headers or {}


class AuthenticationError(GatewayError):
    status_code = 401
    code = "unauthenticated"


class AuthorizationError(GatewayError):
    status_code = 403
    code = "forbidden"


class ConflictError(GatewayError):
    status_code = 409
    code = "conflict"


class RouteNotFoundError(GatewayError):
    status_code = 404
    code = "route_not_found"


class RateLimitExceeded(GatewayError):
    status_code = 429
    code = "rate_limited"


class PayloadTooLarge(GatewayError):
    status_code = 413
    code = "payload_too_large"


class BadRequestError(GatewayError):
    status_code = 400
    code = "bad_request"


class UpstreamUnavailable(GatewayError):
    status_code = 503
    code = "upstream_unavailable"


class UpstreamTimeout(GatewayError):
    status_code = 504
    code = "upstream_timeout"


def error_body(
    code: str, message: str, request_id: str | None, details: Any = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details is not None:
        body["error"]["details"] = details
    return body


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def _gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, _rid(request)),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error", "Request validation failed", _rid(request), details
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(f"http_{exc.status_code}", str(exc.detail), _rid(request)),
            headers=getattr(exc, "headers", None),
        )


def to_response(exc: GatewayError, request_id: str | None) -> JSONResponse:
    """Build an error response outside of FastAPI's handler chain (used by middleware)."""
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, request_id),
        headers=exc.headers,
    )
