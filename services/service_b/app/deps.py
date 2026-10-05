from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status


@dataclass(frozen=True)
class Caller:
    user_id: str
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


async def gateway_caller(
    request: Request,
    x_gateway_secret: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_name: Annotated[str | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
) -> Caller:
    """Only requests that came through the gateway (shared secret) are accepted."""
    secret = request.app.state.settings.internal_secret
    if not x_gateway_secret or not _eq(x_gateway_secret, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Requests must come through the gateway")
    if not x_user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing user identity")
    return Caller(x_user_id, x_user_name or "", x_user_role or "user")


async def service_caller(
    request: Request, x_service_token: Annotated[str | None, Header()] = None
) -> None:
    """Service-to-service authentication for internal endpoints."""
    token = request.app.state.settings.service_token
    if not x_service_token or not _eq(x_service_token, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Internal endpoint")


CurrentCaller = Annotated[Caller, Depends(gateway_caller)]
