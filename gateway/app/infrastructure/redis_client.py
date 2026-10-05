"""Redis connection factory."""

from __future__ import annotations

import redis.asyncio as aioredis


def create_redis(url: str) -> aioredis.Redis:
    return aioredis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        health_check_interval=30,
    )
