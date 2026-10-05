"""Catch-all reverse-proxy routes: /api/<service>/<path>."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.core.exceptions import AuthenticationError, AuthorizationError, RouteNotFoundError
from app.utils.net import client_ip

router = APIRouter(tags=["gateway"])
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


async def _proxy(request: Request, service: str, path: str) -> Response:
    state = request.app.state
    route = state.routes.get(f"/api/{service}")
    if route is None:
        raise RouteNotFoundError(f"No route for '/api/{service}'")

    claims = request.state.claims
    if route.auth_required and request.method != "OPTIONS":
        if claims is None:
            raise request.state.auth_error or AuthenticationError("Authentication required")
        if route.allowed_roles and claims.role not in route.allowed_roles:
            raise AuthorizationError("Insufficient role for this resource")

    ip = client_ip(request, state.settings.trust_forwarded_for)
    return await state.proxy.forward(request, route, path, claims, ip)


@router.api_route("/api/{service}", methods=METHODS, include_in_schema=False)
async def proxy_root(request: Request, service: str) -> Response:
    return await _proxy(request, service, "")


@router.api_route("/api/{service}/{path:path}", methods=METHODS, include_in_schema=False)
async def proxy(request: Request, service: str, path: str) -> Response:
    """Forwards to the upstream pool registered for `/api/{service}`. Requires a Bearer token."""
    return await _proxy(request, service, path)
