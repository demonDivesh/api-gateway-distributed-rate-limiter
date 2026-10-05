from __future__ import annotations

from starlette.requests import Request


def client_ip(request: Request, trust_forwarded: bool) -> str:
    if trust_forwarded:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
