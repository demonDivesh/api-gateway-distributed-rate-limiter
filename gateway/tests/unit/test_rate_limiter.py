import asyncio

import pytest
from app.services.rate_limiter import RateLimiter


@pytest.mark.parametrize("algorithm", ["sliding_window", "token_bucket"])
async def test_allows_up_to_limit_then_blocks(redis_client, algorithm):
    limiter = RateLimiter(redis_client, algorithm)
    results = [await limiter.check("api", "user:1", 5, 60, now_ms=1_000) for _ in range(6)]
    assert [r.allowed for r in results] == [True] * 5 + [False]
    assert results[0].remaining == 4
    assert results[4].remaining == 0
    assert results[5].retry_after_seconds >= 1


async def test_sliding_window_recovers_as_entries_expire(redis_client):
    limiter = RateLimiter(redis_client, "sliding_window")
    for i in range(3):
        assert (await limiter.check("api", "u", 3, 10, now_ms=1_000 + i * 1000)).allowed
    blocked = await limiter.check("api", "u", 3, 10, now_ms=5_000)
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 6  # oldest entry (t=1s) expires at t=11s
    assert (await limiter.check("api", "u", 3, 10, now_ms=11_100)).allowed


async def test_token_bucket_refills_over_time(redis_client):
    limiter = RateLimiter(redis_client, "token_bucket")
    for _ in range(10):
        assert (await limiter.check("api", "u", 10, 10, now_ms=0)).allowed
    blocked = await limiter.check("api", "u", 10, 10, now_ms=0)
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 1
    # 10 tokens / 10s = 1 token per second
    assert (await limiter.check("api", "u", 10, 10, now_ms=1_000)).allowed
    assert not (await limiter.check("api", "u", 10, 10, now_ms=1_000)).allowed


@pytest.mark.parametrize("algorithm", ["sliding_window", "token_bucket"])
async def test_identities_and_scopes_are_isolated(redis_client, algorithm):
    limiter = RateLimiter(redis_client, algorithm)
    assert (await limiter.check("api", "a", 1, 60, now_ms=0)).allowed
    assert not (await limiter.check("api", "a", 1, 60, now_ms=0)).allowed
    assert (await limiter.check("api", "b", 1, 60, now_ms=0)).allowed
    assert (await limiter.check("auth", "a", 1, 60, now_ms=0)).allowed


@pytest.mark.parametrize("algorithm", ["sliding_window", "token_bucket"])
async def test_concurrent_requests_never_exceed_limit(redis_client, algorithm):
    limiter = RateLimiter(redis_client, algorithm)
    results = await asyncio.gather(
        *(limiter.check("api", "burst", 20, 60, now_ms=0) for _ in range(100))
    )
    assert sum(r.allowed for r in results) == 20


async def test_shared_state_across_limiter_instances(redis_client):
    """Two 'gateway replicas' sharing Redis enforce one global limit."""
    a, b = RateLimiter(redis_client), RateLimiter(redis_client)
    allowed = 0
    for i in range(10):
        limiter = a if i % 2 == 0 else b
        allowed += (await limiter.check("api", "shared", 6, 60, now_ms=0)).allowed
    assert allowed == 6


async def test_uses_server_time_when_not_overridden(redis_client):
    limiter = RateLimiter(redis_client)
    assert (await limiter.check("api", "srv", 1, 1)).allowed
    assert not (await limiter.check("api", "srv", 1, 1)).allowed
    await asyncio.sleep(1.1)
    assert (await limiter.check("api", "srv", 1, 1)).allowed


async def test_reset_clears_state(redis_client):
    limiter = RateLimiter(redis_client)
    await limiter.check("api", "x", 1, 60, now_ms=0)
    await limiter.reset("api", "x")
    assert (await limiter.check("api", "x", 1, 60, now_ms=0)).allowed


async def test_invalid_arguments(redis_client):
    limiter = RateLimiter(redis_client)
    with pytest.raises(ValueError):
        await limiter.check("api", "x", 0, 60)
    with pytest.raises(ValueError):
        await limiter.check("api", "x", 1, 0)
