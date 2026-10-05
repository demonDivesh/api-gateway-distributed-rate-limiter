"""Access log + metrics + last-resort error handling."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.exceptions import error_body

logger = logging.getLogger("gateway.access")


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled exception")
            response = JSONResponse(
                status_code=500,
                content=error_body(
                    "internal_error",
                    "Internal server error",
                    getattr(request.state, "request_id", None),
                ),
            )
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        label = getattr(route, "path", None) or "unmatched"
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None and label != "/metrics":
            metrics.observe_request(request.method, label, response.status_code, elapsed)
        claims = getattr(request.state, "claims", None)
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(elapsed * 1000, 2),
                "client": request.client.host if request.client else None,
                "user_id": claims.subject if claims else None,
                "route": label,
            },
        )
        return response
