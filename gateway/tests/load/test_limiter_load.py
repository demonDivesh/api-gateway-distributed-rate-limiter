"""Run with: pytest -m load tests/load   (excluded from the default run)."""

import asyncio
import time

import fakeredis
import pytest
from app.services.rate_limiter import RateLimiter

pytestmark = pytest.mark.load


@pytest.mark.parametrize("algorithm", ["sliding_window", "token_bucket"])
async def test_thousands_of_concurrent_checks_respect_the_limit(algorithm):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    limiter = RateLimiter(redis, algorithm)
    limit, identities, per_identity = 50, 20, 200

    async def hammer(identity: str) -> int:
        results = await asyncio.gather(
            *(limiter.check("load", identity, limit, 60, now_ms=0) for _ in range(per_identity))
        )
        return sum(r.allowed for r in results)

    started = time.perf_counter()
    allowed = await asyncio.gather(*(hammer(f"user-{i}") for i in range(identities)))
    elapsed = time.perf_counter() - started
    assert allowed == [limit] * identities, "each identity must get exactly its limit, never more"
    print(
        f"{identities * per_identity} checks in {elapsed:.2f}s ({identities * per_identity / elapsed:.0f}/s)"
    )
    await redis.aclose()
