"""Distributed rate limiter backed by Redis Lua scripts.

Both algorithms run atomically inside Redis, so any number of gateway replicas can
share the same counters without races. Time is taken from the Redis server clock
(``TIME``) so replicas with skewed clocks still agree.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

import redis.asyncio as aioredis

# KEYS[1]=key ARGV: 1=window_ms 2=limit 3=member 4=now_ms_override ('' = use server time)
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now
if ARGV[4] == '' then
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
else
  now = tonumber(ARGV[4])
end
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, ARGV[3])
  redis.call('PEXPIRE', key, window)
  return {1, limit - count - 1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = window - (now - tonumber(oldest[2]))
if retry < 1 then retry = 1 end
return {0, 0, retry}
"""

# KEYS[1]=key ARGV: 1=window_ms 2=capacity 3=unused 4=now_ms_override
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now
if ARGV[4] == '' then
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
else
  now = tonumber(ARGV[4])
end
local rate = capacity / window
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end
local delta = now - ts
if delta < 0 then delta = 0 end
tokens = math.min(capacity, tokens + delta * rate)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry = math.ceil((1 - tokens) / rate)
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', key, window * 2)
return {allowed, math.floor(tokens), retry}
"""

Algorithm = Literal["sliding_window", "token_bucket"]


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int  # 0 when allowed
    reset_after_seconds: int  # seconds until the window/bucket is fully restored


class RateLimiter:
    def __init__(
        self, redis: aioredis.Redis, algorithm: Algorithm = "sliding_window", prefix: str = "rl"
    ) -> None:
        self._redis = redis
        self.algorithm = algorithm
        self._prefix = prefix
        self._sliding = redis.register_script(SLIDING_WINDOW_LUA)
        self._bucket = redis.register_script(TOKEN_BUCKET_LUA)

    def _key(self, scope: str, identity: str) -> str:
        return f"{self._prefix}:{self.algorithm}:{scope}:{identity}"

    async def check(
        self,
        scope: str,
        identity: str,
        limit: int,
        window_seconds: int = 60,
        *,
        now_ms: int | None = None,
    ) -> RateLimitResult:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        window_ms = window_seconds * 1000
        override = "" if now_ms is None else str(now_ms)
        key = self._key(scope, identity)
        if self.algorithm == "sliding_window":
            raw = await self._sliding(
                keys=[key], args=[window_ms, limit, uuid.uuid4().hex, override]
            )
        else:
            raw = await self._bucket(keys=[key], args=[window_ms, limit, "", override])
        allowed, remaining, retry_ms = int(raw[0]), int(raw[1]), int(raw[2])
        retry_s = 0 if allowed else max(1, -(-retry_ms // 1000))
        if self.algorithm == "sliding_window":
            reset_s = window_seconds if allowed else retry_s
        else:
            missing = limit - remaining
            reset_s = max(0, -(-int(missing * window_ms / limit) // 1000)) if allowed else retry_s
        return RateLimitResult(bool(allowed), limit, remaining, retry_s, reset_s)

    async def reset(self, scope: str, identity: str) -> None:
        await self._redis.delete(self._key(scope, identity))
