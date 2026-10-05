"""Shared httpx client used for proxying and health checks."""

from __future__ import annotations

import httpx


def create_http_client(connect_timeout: float, read_timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        follow_redirects=False,
    )
