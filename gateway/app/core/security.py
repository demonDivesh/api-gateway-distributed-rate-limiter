"""Password hashing (scrypt) and JWT helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Literal

import jwt

from app.core.exceptions import AuthenticationError

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return hmac.compare_digest(actual, expected)


TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class TokenClaims:
    subject: str  # user id
    username: str
    role: str
    token_type: TokenType
    jti: str
    expires_at: int


def create_token(
    *,
    user_id: str,
    username: str,
    role: str,
    token_type: TokenType,
    secret: str,
    algorithm: str,
    ttl_seconds: int,
) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(
    token: str, *, secret: str, algorithm: str, expected_type: TokenType
) -> TokenClaims:
    try:
        data = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": ["exp", "sub", "iat", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token") from exc
    if data.get("type") != expected_type:
        raise AuthenticationError(f"Expected {expected_type} token")
    return TokenClaims(
        subject=str(data["sub"]),
        username=str(data.get("username", "")),
        role=str(data.get("role", "user")),
        token_type=expected_type,
        jti=str(data["jti"]),
        expires_at=int(data["exp"]),
    )


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
