"""FastAPI dependencies shared by routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import TokenClaims


async def require_claims(request: Request) -> TokenClaims:
    claims: TokenClaims | None = getattr(request.state, "claims", None)
    if claims is None:
        error = getattr(request.state, "auth_error", None)
        if error is not None:
            raise error
        raise AuthenticationError("Authentication required")
    return claims


async def require_admin(claims: Annotated[TokenClaims, Depends(require_claims)]) -> TokenClaims:
    if claims.role != "admin":
        raise AuthorizationError("Admin role required")
    return claims


CurrentClaims = Annotated[TokenClaims, Depends(require_claims)]
AdminClaims = Annotated[TokenClaims, Depends(require_admin)]
