from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentClaims
from app.infrastructure.database import get_session
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, session: Session) -> UserOut:
    user = await request.app.state.auth_service.register(session, body.username, body.password)
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, request: Request, session: Session) -> TokenPair:
    return await request.app.state.auth_service.login(session, body.username, body.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, request: Request, session: Session) -> TokenPair:
    return await request.app.state.auth_service.refresh(session, body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, request: Request, claims: CurrentClaims) -> None:
    await request.app.state.auth_service.logout(claims, body.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(request: Request, claims: CurrentClaims, session: Session) -> UserOut:
    user = await request.app.state.auth_service.get_user(session, claims.subject)
    return UserOut.model_validate(user)
