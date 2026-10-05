"""User registration, login, token issuing/refresh/revocation."""

from __future__ import annotations

import logging
import time

import redis.asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    UpstreamUnavailable,
)
from app.core.security import (
    TokenClaims,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import TokenPair

logger = logging.getLogger("gateway.auth")

# Verified when the user does not exist so response time does not reveal valid usernames.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class AuthService:
    def __init__(self, settings: Settings, redis: aioredis.Redis) -> None:
        self._s = settings
        self._redis = redis

    # ---- users -------------------------------------------------------
    async def register(self, session: AsyncSession, username: str, password: str) -> User:
        if not self._s.allow_registration:
            raise AuthorizationError("Registration is disabled")
        existing = await session.scalar(
            select(User).where(func.lower(User.username) == username.lower())
        )
        if existing:
            raise ConflictError("Username already taken")
        user = User(username=username, password_hash=hash_password(password), role="user")
        session.add(user)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ConflictError("Username already taken") from exc
        return user

    async def ensure_admin(self, factory: async_sessionmaker[AsyncSession]) -> None:
        async with factory() as session:
            existing = await session.scalar(
                select(User).where(User.username == self._s.admin_username)
            )
            if existing:
                return
            session.add(
                User(
                    username=self._s.admin_username,
                    password_hash=hash_password(self._s.admin_password),
                    role="admin",
                )
            )
            try:
                await session.commit()
                logger.info("seeded admin user", extra={"username": self._s.admin_username})
            except IntegrityError:
                await session.rollback()  # another replica seeded it first

    async def login(self, session: AsyncSession, username: str, password: str) -> TokenPair:
        user = await session.scalar(select(User).where(User.username == username))
        stored = user.password_hash if user else _DUMMY_HASH
        valid = verify_password(password, stored)
        if not user or not valid or not user.is_active:
            raise AuthenticationError("Invalid username or password")
        return self.issue_pair(user)

    async def get_user(self, session: AsyncSession, user_id: str) -> User:
        user = await session.get(User, user_id)
        if not user or not user.is_active:
            raise AuthenticationError("User no longer exists")
        return user

    # ---- tokens ------------------------------------------------------
    def issue_pair(self, user: User) -> TokenPair:
        common = {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "secret": self._s.jwt_secret,
            "algorithm": self._s.jwt_algorithm,
        }
        return TokenPair(
            access_token=create_token(
                token_type="access", ttl_seconds=self._s.access_token_ttl_seconds, **common
            ),
            refresh_token=create_token(
                token_type="refresh", ttl_seconds=self._s.refresh_token_ttl_seconds, **common
            ),
            expires_in=self._s.access_token_ttl_seconds,
        )

    async def authenticate(self, token: str) -> TokenClaims:
        claims = decode_token(
            token,
            secret=self._s.jwt_secret,
            algorithm=self._s.jwt_algorithm,
            expected_type="access",
        )
        try:
            revoked = await self._redis.exists(self._revoked_key(claims.jti))
        except RedisError as exc:
            logger.error("revocation check failed: %s", exc)
            if not self._s.auth_revocation_fail_open:
                raise UpstreamUnavailable("Authentication backend unavailable") from exc
            return claims
        if revoked:
            raise AuthenticationError("Token has been revoked")
        return claims

    async def refresh(self, session: AsyncSession, refresh_token: str) -> TokenPair:
        claims = decode_token(
            refresh_token,
            secret=self._s.jwt_secret,
            algorithm=self._s.jwt_algorithm,
            expected_type="refresh",
        )
        try:
            if await self._redis.exists(self._revoked_key(claims.jti)):
                raise AuthenticationError("Token has been revoked")
            user = await self.get_user(session, claims.subject)
            await self.revoke(claims)  # rotation: each refresh token is single use
        except RedisError as exc:
            raise UpstreamUnavailable("Authentication backend unavailable") from exc
        return self.issue_pair(user)

    async def revoke(self, claims: TokenClaims) -> None:
        ttl = max(1, claims.expires_at - int(time.time()))
        await self._redis.set(self._revoked_key(claims.jti), "1", ex=ttl)

    async def logout(self, access: TokenClaims, refresh_token: str | None) -> None:
        try:
            await self.revoke(access)
            if refresh_token:
                try:
                    refresh_claims = decode_token(
                        refresh_token,
                        secret=self._s.jwt_secret,
                        algorithm=self._s.jwt_algorithm,
                        expected_type="refresh",
                    )
                    if refresh_claims.subject == access.subject:
                        await self.revoke(refresh_claims)
                except AuthenticationError:
                    pass  # an invalid refresh token needs no revocation
        except RedisError as exc:
            raise UpstreamUnavailable("Authentication backend unavailable") from exc

    @staticmethod
    def _revoked_key(jti: str) -> str:
        return f"auth:revoked:{jti}"
